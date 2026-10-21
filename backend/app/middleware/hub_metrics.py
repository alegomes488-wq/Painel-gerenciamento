"""Buffer em memória de métricas de API para o painel HUB.

O middleware em main.py grava cada requisição /api/* (método, rota, status,
duração). O hub_feeder drena o buffer a cada ciclo do telemetry worker e
publica a seção "api" do HUB (latência p95, throughput, taxa de erro).

Desativável via HUB_METRICS=false. O buffer é limitado (ring buffer) para
não consumir memória sob carga.
"""
import os
import re
import threading
import time
from collections import deque

ENABLED = os.environ.get("HUB_METRICS", "true").lower() in ("1", "true", "yes")
BUFFER_MAX = 5000

# Exclui o próprio HUB (evita loop: ingestão de eventos virar métrica de API)
_EXCLUDED_PREFIXES = ("/api/hub",)

_buffer = deque(maxlen=BUFFER_MAX)
_lock = threading.Lock()

# Normaliza segmentos numéricos/ids para agrupar rotas: /users/123 -> /users/{id}
_ID_SEGMENT = re.compile(r"^[0-9a-f]{8,}$|^\d+$")


def normalize_path(path: str) -> str:
    """Agrupa rotas com ids em um template para agregação por endpoint."""
    parts = []
    for segment in path.split("/"):
        if not segment:
            continue
        parts.append("{id}" if _ID_SEGMENT.match(segment) else segment)
    return "/" + "/".join(parts)


def record(method: str, path: str, status_code: int, duration_ms: float) -> None:
    """Registra uma requisição no buffer (thread-safe, no-op se desativado)."""
    if not ENABLED:
        return
    if path.startswith(_EXCLUDED_PREFIXES):
        return
    event = {
        "method": str(method)[:8],
        "path": normalize_path(path)[:200],
        "status": int(status_code),
        "duration_ms": max(0.0, float(duration_ms)),
        "ts": time.time(),
    }
    with _lock:
        _buffer.append(event)


def drain() -> list:
    """Remove e retorna todos os eventos acumulados."""
    with _lock:
        events = list(_buffer)
        _buffer.clear()
    return events


def pending_count() -> int:
    with _lock:
        return len(_buffer)
