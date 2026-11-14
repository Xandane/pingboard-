"""PostgreSQL хранит список сайтов, MongoDB хранит результаты проверок."""

from datetime import UTC, datetime

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

CHECKS_TTL_SECONDS = 30 * 24 * 3600


class Base(DeclarativeBase):
    pass


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048))
    interval_sec: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def init_db() -> None:
    # Временное решение: таблицы создаются при старте api.
    # Отдельной задачей этапа 1 заменить на миграции Alembic.
    Base.metadata.create_all(engine)


_mongo_client: MongoClient | None = None


def mongo_db() -> Database:
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True)
    return _mongo_client[config.MONGO_DB]


def init_mongo() -> None:
    checks = mongo_db().checks
    # TTL-индекс: MongoDB сама удаляет записи старше 30 дней.
    checks.create_index([("ts", ASCENDING)], expireAfterSeconds=CHECKS_TTL_SECONDS)
    checks.create_index([("target_id", ASCENDING), ("ts", DESCENDING)])
