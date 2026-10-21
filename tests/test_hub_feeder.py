"""Painel HUB — testes do feeder interno de métricas de API (hub_feeder)."""
import os
import sys

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.middleware import hub_metrics
from app.services import hub_feeder


def _event(status=200, duration_ms=10.0, path="/api/users/123", ts=None):
    return {"method": "GET", "path": path, "status": status, "duration_ms": duration_ms, "ts": ts}


# ─────────────────────────────────────────────────────────────
# AGREGAÇÃO PURA
# ─────────────────────────────────────────────────────────────

def test_aggregate_metricas_basicas():
    events = [
        _event(status=200, duration_ms=10, ts=0),
        _event(status=200, duration_ms=20, ts=5),
        _event(status=500, duration_ms=30, ts=10),
        _event(status=404, duration_ms=40, ts=10),
    ]
    metrics = hub_feeder.aggregate_api_metrics(events)
    assert metrics["_events_total"] == 4
    assert metrics["error_rate"] == 25.0          # 1 de 4 = 25%
    assert metrics["client_error_rate"] == 25.0   # 1 de 4 (404)
    assert 20 <= metrics["latency_p95_ms"] <= 40
    assert metrics["rps"] == pytest.approx(4 / 10)  # 4 eventos em 10s


def test_aggregate_p95_com_muitos_eventos():
    events = [_event(duration_ms=i, ts=0) for i in range(1, 101)]  # 1..100ms
    metrics = hub_feeder.aggregate_api_metrics(events)
    assert 90 <= metrics["latency_p95_ms"] <= 100


def test_aggregate_agrupa_endpoints_com_id():
    events = [
        _event(path="/api/users/111", duration_ms=10, ts=0),
        _event(path="/api/users/222", duration_ms=30, ts=1),
        _event(path="/api/users/333", status=500, duration_ms=50, ts=2),
    ]
    metrics = hub_feeder.aggregate_api_metrics(events)
    endpoints = metrics["endpoints"]
    assert "/api/users/{id}" in endpoints
    agg = endpoints["/api/users/{id}"]
    assert agg["latency_ms"] == pytest.approx(30.0)
    assert agg["error_rate"] == pytest.approx(33.33, abs=0.1)


def test_aggregate_vazio_levanta():
    with pytest.raises(ValueError):
        hub_feeder.aggregate_api_metrics([])


def test_normalize_path():
    assert hub_metrics.normalize_path("/api/projects/abc123def4567890/members") == \
        "/api/projects/{id}/members"
    assert hub_metrics.normalize_path("/api/health") == "/api/health"


# ─────────────────────────────────────────────────────────────
# DRAIN + FEED (com RTDB falso)
# ─────────────────────────────────────────────────────────────

def test_drain_and_feed_publica_no_hub(app_env, fake_db, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "HUB_AGENT_SECRET", "test-hub-secret")
    hub_metrics.drain()  # isola de eventos registrados por outros testes
    hub_metrics.record("GET", "/api/projects/42", 200, 12.5)
    hub_metrics.record("POST", "/api/payments/webhook", 500, 80.0)
    result = hub_feeder.drain_and_feed()
    assert result is not None
    assert result["events"] == 2
    stored = fake_db.reference("hub/performance/api").get()
    assert stored["error_rate"] == 50.0
    assert stored["source"] == "backend-agent"
    # buffer drenado
    assert hub_feeder.drain_and_feed() is None


def test_drain_ignora_proprias_rotas_do_hub(app_env, fake_db):
    hub_metrics.record("POST", "/api/hub/events", 200, 5.0)
    assert hub_metrics.pending_count() == 0
    assert hub_feeder.drain_and_feed() is None


def test_record_noop_quando_desativado(monkeypatch):
    monkeypatch.setattr(hub_metrics, "ENABLED", False)
    hub_metrics.record("GET", "/api/x", 200, 1.0)
    assert hub_metrics.pending_count() == 0
    monkeypatch.setattr(hub_metrics, "ENABLED", True)
