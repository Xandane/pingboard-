"""Фоновый процесс: по расписанию проверяет все сайты и пишет результаты в MongoDB."""

import logging
import math
import signal
import time
from concurrent.futures import ThreadPoolExecutor

from prometheus_client import Counter, Gauge, start_http_server
from sqlalchemy import select

from . import checks, config, db
from .log import setup_logging

log = logging.getLogger("pingboard.worker")

LABELS = ["target_id", "name"]
TARGET_UP = Gauge("pingboard_target_up", "1 if the target answered with status < 400", LABELS)
RESPONSE_SECONDS = Gauge("pingboard_response_seconds", "Response time of the last check", LABELS)
CERT_DAYS_LEFT = Gauge("pingboard_cert_days_left", "Days until the TLS certificate expires", LABELS)
CHECKS_TOTAL = Counter("pingboard_checks_total", "Checks performed", ["result"])
LOOP_ERRORS = Counter("pingboard_worker_errors_total", "Errors in the worker loop")

TICK_SECONDS = 5
stopping = False


def handle_sigterm(signum, frame):
    # docker stop отправляет SIGTERM: дожидаемся текущих проверок и выходим.
    global stopping
    stopping = True
    log.info("shutdown requested")


def run_check(target_id: int, name: str, url: str) -> None:
    try:
        result = checks.check_url(url, config.CHECK_TIMEOUT)
        result.update({"target_id": target_id, "name": name})
        db.mongo_db().checks.insert_one(result)

        labels = (str(target_id), name)
        TARGET_UP.labels(*labels).set(1 if result["up"] else 0)
        if result["response_seconds"] is not None:
            RESPONSE_SECONDS.labels(*labels).set(result["response_seconds"])
        if result["cert_days_left"] is not None:
            CERT_DAYS_LEFT.labels(*labels).set(result["cert_days_left"])
        CHECKS_TOTAL.labels("up" if result["up"] else "down").inc()

        log.info(
            "check done",
            extra={"fields": {k: result[k] for k in ("target_id", "up", "status_code", "error")}},
        )
    except Exception:
        LOOP_ERRORS.inc()
        log.exception("check failed", extra={"fields": {"target_id": target_id}})


def forget_target(target_id: int, name: str) -> None:
    for gauge in (TARGET_UP, RESPONSE_SECONDS, CERT_DAYS_LEFT):
        try:
            gauge.remove(str(target_id), name)
        except KeyError:
            pass


def main() -> None:
    setup_logging()
    signal.signal(signal.SIGTERM, handle_sigterm)
    start_http_server(config.WORKER_METRICS_PORT)
    log.info("worker started", extra={"fields": {"metrics_port": config.WORKER_METRICS_PORT}})

    last_run: dict[int, float] = {}
    known: dict[int, str] = {}
    in_flight: set[int] = set()

    with ThreadPoolExecutor(max_workers=10) as pool:
        while not stopping:
            try:
                with db.SessionLocal() as session:
                    targets = list(session.scalars(select(db.Target)))
                now = time.monotonic()

                for t in targets:
                    known[t.id] = t.name
                    due = now - last_run.get(t.id, -math.inf) >= t.interval_sec
                    if due and t.id not in in_flight:
                        last_run[t.id] = now
                        in_flight.add(t.id)
                        future = pool.submit(run_check, t.id, t.name, t.url)
                        future.add_done_callback(lambda _f, tid=t.id: in_flight.discard(tid))

                current_ids = {t.id for t in targets}
                for tid in list(known):
                    if tid not in current_ids:
                        forget_target(tid, known.pop(tid))
                        last_run.pop(tid, None)
            except Exception:
                LOOP_ERRORS.inc()
                log.exception("worker loop error")

            time.sleep(TICK_SECONDS)

    log.info("worker stopped")


if __name__ == "__main__":
    main()
