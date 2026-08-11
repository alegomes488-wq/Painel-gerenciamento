"""T-04B — App Check middleware (enforcement).

Cobre os 3 estados:
- DESATIVADO (APP_CHECK_REQUIRED=false): rotas de API funcionam sem header.
- ATIVADO + header ausente: 401.
- ATIVADO + token validado: 200.
- ATIVADO + token inválido: 401.
- Exceções (health/docs/webhook/OPTIONS) nunca exigem App Check.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def appcheck_app(monkeypatch):
    """App FastAPI mínimo com apenas a rota /api/probe protegida por AppCheck."""
    from app.middleware.appcheck import AppCheckMiddleware

    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-proj")
    monkeypatch.setenv("FIREBASE_APP_ID", "test-app")

    app = FastAPI()

    @app.get("/api/probe")
    async def probe():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "online"}

    @app.get("/payments/webhook/asaas")
    async def webhook():
        return {"status": "ok"}

    app.add_middleware(AppCheckMiddleware)
    return app


@pytest.fixture
def stub_verify(monkeypatch, appcheck_app):
    """Stuba a validação real (sem rede/credenciais). Retorna app com stub ativo."""
    import app.middleware.appcheck as ac

    def _apply(result):
        monkeypatch.setattr(
            ac.AppCheckMiddleware, "_verify_appcheck_token", lambda self, token: result
        )
        return appcheck_app

    return _apply


def test_disabled_mode_passes_without_header(app_env, monkeypatch, appcheck_app):
    """APP_CHECK_REQUIRED=false: sem header, rota de API continua respondendo 200."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "false")
    c = TestClient(appcheck_app)
    r = c.get("/api/probe")
    assert r.status_code == 200, r.text


def test_enabled_rejects_missing_header(app_env, monkeypatch, appcheck_app):
    """APP_CHECK_REQUIRED=true: sem X-Firebase-AppCheck → 401."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    c = TestClient(appcheck_app)
    r = c.get("/api/probe")
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "X-Firebase-AppCheck header required"


def test_enabled_accepts_verified_token(app_env, monkeypatch, appcheck_app, stub_verify):
    """APP_CHECK_REQUIRED=true: token verificado com sucesso → 200."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    stub_verify(result=True)
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "token-ok"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_enabled_rejects_invalid_token(app_env, monkeypatch, appcheck_app, stub_verify):
    """APP_CHECK_REQUIRED=true: token presente mas inválido → 401."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    stub_verify(result=False)
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "token-invalido"})
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "App Check token invalid"


def test_enabled_returns_503_when_service_unavailable(app_env, monkeypatch, appcheck_app, stub_verify):
    """Falha de rede na validação → 503 (não 500)."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    stub_verify(result=None)
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "token-ok"})
    assert r.status_code == 503, r.text


def test_enabled_never_blocks_excluded_routes(app_env, monkeypatch, appcheck_app, stub_verify):
    """Exceções (health/webhook) continuam acessíveis mesmo com enforcement ativo."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    stub_verify(result=False)
    c = TestClient(appcheck_app)
    assert c.get("/health").status_code == 200
    assert c.get("/payments/webhook/asaas").status_code == 200


def test_enabled_passes_options_without_header(app_env, monkeypatch, appcheck_app, stub_verify):
    """OPTIONS (preflight CORS) nunca exige App Check."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    stub_verify(result=False)
    c = TestClient(appcheck_app)
    r = c.options("/api/probe")
    assert r.status_code in (200, 405)


def test_static_frontend_not_blocked(app_env, monkeypatch, appcheck_app, stub_verify):
    """Frontend estático (fora de /api/ e /payments/) não é bloqueado."""
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    stub_verify(result=False)

    app = FastAPI()

    @app.get("/admin/index.html")
    async def page():
        return "<html></html>"

    from app.middleware.appcheck import AppCheckMiddleware

    app.add_middleware(AppCheckMiddleware)
    c = TestClient(app)
    assert c.get("/admin/index.html").status_code == 200
