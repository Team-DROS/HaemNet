"""Request IDs, JSON logs and deep health."""

import json
import logging

import httpx

from backend import observability
from backend.api import health
from backend.config import settings


def test_response_carries_a_request_id_and_honours_a_safe_incoming_one(client):
    assert len(client.get("/api/health").headers["x-request-id"]) == 32
    res = client.get("/api/health", headers={"X-Request-ID": "trace-abc12345"})
    assert res.headers["x-request-id"] == "trace-abc12345"


def test_unsafe_incoming_ids_are_replaced(client):
    res = client.get("/api/health", headers={"X-Request-ID": "bad id\twith spaces!"})
    assert res.headers["x-request-id"] != "bad id\twith spaces!" and len(res.headers["x-request-id"]) == 32


def test_access_log_has_the_request_id_and_no_query_string(client, caplog):
    with caplog.at_level(logging.INFO, logger="haemnet.access"):
        client.get("/api/health?donor=secret-donor-id")
    line = [r for r in caplog.records if r.name == "haemnet.access"][-1].getMessage()
    assert "/api/health" in line and "secret-donor-id" not in line


def test_json_formatter_emits_one_object_with_request_id():
    token = observability.request_id_var.set("rid-12345678")
    try:
        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
        observability.RequestIdFilter().filter(record)
        out = json.loads(observability.JsonFormatter().format(record))
    finally:
        observability.request_id_var.reset(token)
    assert out["message"] == "hello world" and out["request_id"] == "rid-12345678" and out["level"] == "WARNING"


def test_deep_health_reports_sarvam_down(client, monkeypatch):
    async def db_ok():
        return {"status": "connected", "backend": "mongodb"}

    class Down:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(health, "db_health", db_ok)
    monkeypatch.setattr(settings, "sarvam_api_key", "key")
    monkeypatch.setattr(httpx, "AsyncClient", Down)
    body = client.get("/api/health/deep").json()
    assert body["status"] == "degraded" and body["checks"]["sarvam"] is False and body["checks"]["database"] is True
