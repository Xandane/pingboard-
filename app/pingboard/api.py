"""HTTP API: управление списком сайтов, статусы, /health и /metrics."""

import html
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select, text

from . import config, db
from .log import setup_logging

log = logging.getLogger("pingboard.api")

REQUESTS = Counter(
    "pingboard_api_requests_total", "HTTP requests handled by the API", ["method", "status"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    db.init_db()
    db.init_mongo()
    log.info("api started")
    yield


app = FastAPI(title="Pingboard", lifespan=lifespan)


@app.middleware("http")
async def count_requests(request: Request, call_next):
    response = await call_next(request)
    REQUESTS.labels(request.method, str(response.status_code)).inc()
    return response


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = config.API_TOKEN
    if not expected:
        raise HTTPException(status_code=500, detail="API_TOKEN is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if not secrets.compare_digest(authorization.removeprefix("Bearer "), expected):
        raise HTTPException(status_code=401, detail="Invalid token")


class TargetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    interval_sec: int = Field(default=60, ge=30, le=3600)


class TargetOut(BaseModel):
    id: int
    name: str
    url: str
    interval_sec: int


def to_out(t: db.Target) -> TargetOut:
    return TargetOut(id=t.id, name=t.name, url=t.url, interval_sec=t.interval_sec)


@app.post("/targets", status_code=201, dependencies=[Depends(require_token)])
def create_target(body: TargetIn) -> TargetOut:
    with db.SessionLocal() as session:
        target = db.Target(name=body.name, url=str(body.url), interval_sec=body.interval_sec)
        session.add(target)
        session.commit()
        log.info("target created", extra={"fields": {"target_id": target.id}})
        return to_out(target)


@app.get("/targets", dependencies=[Depends(require_token)])
def list_targets() -> list[TargetOut]:
    with db.SessionLocal() as session:
        return [to_out(t) for t in session.scalars(select(db.Target).order_by(db.Target.id))]


@app.delete("/targets/{target_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_target(target_id: int) -> Response:
    with db.SessionLocal() as session:
        target = session.get(db.Target, target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Target not found")
        session.delete(target)
        session.commit()
    return Response(status_code=204)


@app.get("/targets/{target_id}/status", dependencies=[Depends(require_token)])
def target_status(target_id: int) -> dict:
    with db.SessionLocal() as session:
        if session.get(db.Target, target_id) is None:
            raise HTTPException(status_code=404, detail="Target not found")

    checks = db.mongo_db().checks
    last = checks.find_one({"target_id": target_id}, {"_id": 0}, sort=[("ts", -1)])
    since = datetime.now(UTC) - timedelta(hours=24)
    total = checks.count_documents({"target_id": target_id, "ts": {"$gte": since}})
    ok = checks.count_documents({"target_id": target_id, "ts": {"$gte": since}, "up": True})
    uptime = round(ok / total * 100, 2) if total else None
    return {"target_id": target_id, "uptime_24h_percent": uptime, "last_check": last}


@app.get("/health")
def health() -> JSONResponse:
    status = {"postgres": "ok", "mongo": "ok"}
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        status["postgres"] = f"error: {exc.__class__.__name__}"
    try:
        db.mongo_db().command("ping")
    except Exception as exc:
        status["mongo"] = f"error: {exc.__class__.__name__}"
    healthy = all(v == "ok" for v in status.values())
    return JSONResponse(status, status_code=200 if healthy else 503)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Публичная страница только для чтения: показывает имена и статусы, без управления.
    with db.SessionLocal() as session:
        targets = list(session.scalars(select(db.Target).order_by(db.Target.id)))
    checks = db.mongo_db().checks
    rows = []
    for t in targets:
        last = checks.find_one({"target_id": t.id}, sort=[("ts", -1)]) or {}
        state = "нет данных" if not last else ("UP" if last.get("up") else "DOWN")
        code = last.get("status_code", "")
        seconds = last.get("response_seconds", "")
        rows.append(
            f"<tr><td>{html.escape(t.name)}</td><td>{html.escape(t.url)}</td>"
            f"<td>{state}</td><td>{code}</td><td>{seconds}</td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan='5'>Сайтов пока нет</td></tr>"
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Pingboard</title><style>body{font-family:sans-serif;margin:2rem}"
        "table{border-collapse:collapse}td,th{border:1px solid #999;padding:.4rem .8rem}"
        "</style></head><body><h1>Pingboard</h1><table><tr><th>Имя</th><th>URL</th>"
        f"<th>Статус</th><th>Код</th><th>Время, с</th></tr>{body}</table></body></html>"
    )
