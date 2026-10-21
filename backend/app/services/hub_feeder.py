"""Agente de coleta interna do painel HUB — seção "api" (Desempenho).

Drena o buffer do middleware hub_metrics, agrega em métricas de saúde da
API (latência p95, throughput, taxa de erro, endpoints) e publica no HUB
via hub_service.ingest_and_correlate. Funções puras (aggregate_*) são
testáveis sem RTDB.
"""
import re
from datetime import datetime, timezone

from app.middleware import hub_metrics
from app.services import hub_service

SOURCE = "backend-agent"
# Janela mínima para calcular rps (evita divisão por zero em 1 evento)
MIN_WINDOW_S = 1.0
_STATUS_SEGMENT = re.compile(r"^[0-9a-f]{8,}$|^\d+$")


def _percentile(sorted_values: list, pct: float):
    """Percentil simples por interpolação linear (lista já ordenada)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def aggregate_api_metrics(events: list, now: datetime | None = None) -> dict:
    """
    Agrega eventos brutos do middleware em métricas da seção "api".
    events: [{"method", "path", "status", "duration_ms"}, ...]
    Retorna dict com latency_p95_ms, rps, error_rate e endpoints.
    """
    if not isinstance(events, list) or not events:
        raise ValueError("Nenhum evento de API para agregar")

    now = now or datetime.now(timezone.utc)  # noqa: UP017 — Python 3.10 no Dockerfile
    durations = sorted(float(e.get("duration_ms") or 0) for e in events)
    errors = sum(1 for e in events if int(e.get("status") or 0) >= 500)
    client_errors = sum(1 for e in events if 400 <= int(e.get("status") or 0) < 500)

    # Janela real entre o primeiro e o último evento (ts gravado pelo middleware).
    timestamps = [float(e["ts"]) for e in events if isinstance(e.get("ts"), (int, float))]
    window_s = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else MIN_WINDOW_S
    window_s = max(window_s, MIN_WINDOW_S)
    rps = len(events) / window_s

    p95 = _percentile(durations, 95)
    error_rate = (errors / len(events)) * 100.0

    # Top endpoints por volume (latência média + taxa de erro).
    # normalize_path é idempotente — o middleware já normaliza, mas protege
    # eventos gravados por versões antigas do buffer.
    by_path = {}
    for e in events:
        path = hub_metrics.normalize_path(e.get("path") or "?")[:200]
        bucket = by_path.setdefault(path, {"count": 0, "errors": 0, "total_ms": 0.0})
        bucket["count"] += 1
        bucket["total_ms"] += float(e.get("duration_ms") or 0)
        if int(e.get("status") or 0) >= 500:
            bucket["errors"] += 1
    endpoints = {}
    for path, b in sorted(by_path.items(), key=lambda kv: kv[1]["count"], reverse=True)[:20]:
        endpoints[path] = {
            "latency_ms": round(b["total_ms"] / b["count"], 1),
            "error_rate": round((b["errors"] / b["count"]) * 100.0, 2),
            "rps": round(b["count"] / window_s, 2),
        }

    return {
        "latency_p95_ms": round(p95, 1) if p95 is not None else 0.0,
        "rps": round(rps, 2),
        "error_rate": round(error_rate, 2),
        "client_error_rate": round((client_errors / len(events)) * 100.0, 2),
        "endpoints": endpoints,
        "_events_total": len(events),
    }


def drain_and_feed() -> dict | None:
    """
    Drena o buffer e publica a seção "api" no HUB (com correlações + ações
    autônomas). Retorna None se o buffer estiver vazio.
    """
    events = hub_metrics.drain()
    if not events:
        return None
    metrics = aggregate_api_metrics(events)
    total = metrics.pop("_events_total", len(events))
    result = hub_service.ingest_and_correlate("api", metrics, source=SOURCE)
    return {"events": total, **result}
