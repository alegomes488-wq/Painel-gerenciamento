"""T-04 — App Check enforcement ausente no backend.

O frontend ativa App Check (reCAPTCHA Enterprise em config.js), mas o backend
NÃO valida o header X-Firebase-AppCheck em nenhuma rota. Este teste prova a
brecha com evidência (baseline para a correção).
"""
import pytest


def test_protected_route_accepts_request_without_appcheck(app_env, fake_db, fake_auth, client):
    """T-04: rota protegida retorna 200 com Bearer admin válido e SEM X-Firebase-AppCheck.

    Se o App Check fosse enforced, retornaria 401/403 (token ausente). O 200 prova a brecha.
    """
    fake_db.reference("neural/nodes").set({})
    r = client.get(
        "/api/monitor/projects",
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200, r.text
    assert "projects" in r.json()


def test_public_route_still_works_without_appcheck(app_env, fake_db, fake_auth, client):
    """Controle: /health e /docs permanecem acessíveis (não devem ser bloqueadas)."""
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200


def test_middleware_has_no_appcheck_enforcement(app_env, fake_db, fake_auth, client):
    """Evidência estática: o middleware admin_auth_middleware não referencia App Check."""
    from app.main import admin_auth_middleware
    import inspect
    src = inspect.getsource(admin_auth_middleware)
    assert "X-Firebase-AppCheck" not in src
    assert "app_check" not in src
