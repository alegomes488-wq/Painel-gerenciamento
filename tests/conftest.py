"""Conftest — AUDIT 00 harness (painel). RTDB in-memory + env mock. Sem rede."""
import os
import sys
import time
import uuid
import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

# Routers leem estas chaves de os.environ NO IMPORT (payments.py). Setamos antes de
# qualquer import de app.* para que os módulos sejam carregados já configurados.
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("N8N_SHARED_SECRET", "test-n8n-secret")
os.environ.setdefault("ASAAS_API_KEY", "test-asaas-key")


class FakeTransactionResult:
    """Espelha o TransactionResult do firebase-admin (committed + value)."""

    def __init__(self, committed, value):
        self.committed = committed
        self.value = value


class FakeReference:
    """Mock mínimo do Firebase RTDB Reference (API subset usada pelo painel)."""

    def __init__(self, store, path):
        self.store = store
        self.path = path

    def _node(self):
        cur = self.store
        for part in self.path.split("/"):
            if part:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(part)
        return cur

    def get(self):
        return self._node()

    def set(self, value):
        cur = self.store
        parts = [p for p in self.path.split("/") if p]
        for part in parts[:-1]:
            if not isinstance(cur, dict):
                raise TypeError("caminho pai não é objeto")
            cur.setdefault(part, {})
            cur = cur[part]
        if parts:
            cur[parts[-1]] = value

    def update(self, value):
        cur = self._node()
        if isinstance(cur, dict):
            cur.update(value)
        elif cur is None:
            self.set(value)

    def child(self, child_path):
        return FakeReference(self.store, f"{self.path}/{child_path}")

    def delete(self):
        cur = self.store
        parts = [p for p in self.path.split("/") if p]
        for part in parts[:-1]:
            if not isinstance(cur, dict):
                return
            cur = cur[part]
        if parts and isinstance(cur, dict):
            cur.pop(parts[-1], None)

    def push(self, value=None):
        key = f"k{uuid.uuid4().hex[:8]}"
        self.child(key).set(value or {})
        return FakeReference(self.store, f"{self.path}/{key}")

    def transaction(self, fn):
        current = self._node()
        result = fn(current)
        if result is None:
            return FakeTransactionResult(committed=False, value=None)
        self.set(result)
        return FakeTransactionResult(committed=True, value=result)


class FakeDB:
    def __init__(self):
        self.data = {}

    def reference(self, path):
        return FakeReference(self.data, path)


@pytest.fixture
def fake_db(monkeypatch):
    """Mocka o acesso ao RTDB nos módulos atuais (routers usam firebase_admin.db direto;
    services usam get_db)."""
    fdb = FakeDB()
    monkeypatch.setattr("app.routers.payments.db", fdb)
    monkeypatch.setattr("app.routers.projects.db", fdb)
    monkeypatch.setattr("app.routers.secops.get_db", lambda: fdb)
    monkeypatch.setattr("app.services.asaas_service.get_db", lambda: fdb)
    monkeypatch.setattr("app.services.secops_agent.get_db", lambda: fdb)
    return fdb


@pytest.fixture
def fake_auth(monkeypatch):
    """Mocka verify_id_token globalmente (firebase_admin.auth) — cobre o middleware
    (get_auth) e os routers (firebase_auth), que apontam para o mesmo módulo."""
    def _verify(token, check_revoked=False):
        if token == "valid-admin":
            return {"uid": "U1", "email": "admin@test.com", "admin": True}
        if token == "valid-user":
            return {"uid": "U2", "email": "user@test.com", "admin": False}
        raise Exception("ID token inválido")
    monkeypatch.setattr("firebase_admin.auth.verify_id_token", _verify)
    return _verify


@pytest.fixture
def app_env(monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setattr(cfg.settings, "N8N_SHARED_SECRET", "test-n8n-secret")
    monkeypatch.setattr(cfg.settings, "ASAAS_API_KEY", "test-asaas-key")
    return cfg.settings


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
