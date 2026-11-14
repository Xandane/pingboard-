import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient  # noqa: E402

from pingboard import api, config  # noqa: E402

client = TestClient(api.app)


def test_targets_require_token(monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "secret")
    assert client.get("/targets").status_code == 401


def test_wrong_token_rejected(monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "secret")
    response = client.get("/targets", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_interval_is_validated(monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "secret")
    response = client.post(
        "/targets",
        headers={"Authorization": "Bearer secret"},
        json={"name": "example", "url": "https://example.com", "interval_sec": 5},
    )
    assert response.status_code == 422


def test_metrics_are_public():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "pingboard_api_requests_total" in response.text
