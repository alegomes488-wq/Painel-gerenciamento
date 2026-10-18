"""
Rate limiting simples em memória — CyberCore IA

TAREFA 2.5: Limita requisições por IP/UID por rota. Sem dependências externas
(evita pip install), usa buckets de janela fixa em memória. Suficiente para
proteger endpoints sensíveis contra abuso imediato.

Limites configuráveis via dict por prefixo:
  /api/auth/    : 5 req/min por IP
  /api/payments : 10 req/min por IP
  /api/secops   : 30 req/min por IP
  /api/admin    : 10 req/min por IP
  /payments/    : 60 req/min por IP (webhook)
  /health       : 30 req/min por IP
  outros        : 120 req/min por IP
"""
import time
import threading
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets = defaultdict(lambda: {"count": 0, "reset": 0.0})
        self._lock = threading.Lock()

    def _key_for(self, prefix: str, request: Request) -> str:
        # Chave por IP do cliente
        ip = request.client.host if request.client else "unknown"
        return f"{prefix}:{ip}"

    def _limit_for(self, path: str) -> int:
        if path.startswith("/api/auth"):
            return 5
        if path.startswith("/api/payments") or path.startswith("/payments"):
            return 60 if path.startswith("/payments/") else 10
        if path.startswith("/api/secops"):
            return 30
        if path.startswith("/api/admin"):
            return 10
        if path == "/health" or path.startswith("/health"):
            return 30
        return 120

    def check(self, request: Request) -> bool:
        path = request.url.path
        limit = self._limit_for(path)
        key = self._key_for(path, request)
        now = time.time()
        window = 60.0

        with self._lock:
            entry = self._buckets[key]
            if not entry["reset"] or now > entry["reset"]:
                entry["count"] = 0
                entry["reset"] = now + window
            if entry["count"] >= limit:
                return False
            entry["count"] += 1
            return True


rate_limiter = InMemoryRateLimiter()
