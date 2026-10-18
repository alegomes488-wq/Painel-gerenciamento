"""TAREFA 2.8: headers de segurança presentes em todas as respostas."""
import pytest


def test_security_headers_on_health(app_env, client):
    """/health expõe todos os headers de segurança."""
    r = client.get("/health")
    assert "content-security-policy" in r.headers
    assert "x-frame-options" in r.headers
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-content-type-options" in r.headers
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "referrer-policy" in r.headers


def test_security_headers_on_api(app_env, client):
    """Rota de API também carrega headers (ex: /api/monitor/projects com admin)."""
    r = client.get(
        "/api/monitor/projects",
        headers={"Authorization": "Bearer valid-admin"},
    )
    # Pode ser 200 (fake_db vazio) ou 401/403 — o importante é que headers existam
    assert "content-security-policy" in r.headers
    assert "x-frame-options" in r.headers