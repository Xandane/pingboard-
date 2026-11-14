"""Все настройки берутся из переменных окружения (принцип 12-factor)."""

import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./pingboard.db")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "pingboard")
API_TOKEN = os.environ.get("API_TOKEN", "")
CHECK_TIMEOUT = float(os.environ.get("CHECK_TIMEOUT", "10"))
WORKER_METRICS_PORT = int(os.environ.get("WORKER_METRICS_PORT", "8001"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
