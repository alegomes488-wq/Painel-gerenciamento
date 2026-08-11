"""T-06/T-07: monitor/report público (A-01) e validação de projectId. T-23/T-24/T-25: sanitização."""
import pytest


def _seed_node(fdb, pid="PRJ1"):
    fdb.reference(f"neural/nodes/{pid}").set({"id": pid, "identifier": "x.com"})


def test_monitor_report_bypass_auth(app_env, fake_db, client):
    """A-01: /api/monitor/report não exige token (allowlist) — confirma o bypass."""
    _seed_node(fake_db)
    r = client.post("/api/monitor/report", json={
        "projectId": "PRJ1",
        "status": "<script>alert(1)</script>",
        "cpu": 50, "ram": 60, "disk": 70,
    })
    assert r.status_code == 200, r.text
    health = fake_db.reference("neural/nodes/PRJ1/health").get()
    assert health["status"] == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_monitor_report_project_not_found(app_env, fake_db, client):
    """T-07: projectId inexistente => 404 (não grava)."""
    r = client.post("/api/monitor/report", json={"projectId": "PRJ_X", "cpu": 1})
    assert r.status_code == 404
    assert r.json()["detail"] == "Projeto não encontrado"


def test_monitor_report_without_project_id(app_env, fake_db, client):
    r = client.post("/api/monitor/report", json={})
    assert r.status_code == 400
    assert "projectId" in r.json()["detail"]


def test_monitor_report_invalid_project_id(app_env, fake_db, client):
    """projectId com caracteres inválidos é rejeitado (regex ^[a-zA-Z0-9_-]{1,64}$)."""
    _seed_node(fake_db)
    r = client.post("/api/monitor/report", json={"projectId": "PRJ X; DROP", "cpu": 1})
    assert r.status_code == 400


def test_monitor_report_clamps_values(app_env, fake_db, client):
    """T-25: cpu/ram/disk são clampados em 0-100."""
    _seed_node(fake_db)
    r = client.post("/api/monitor/report", json={
        "projectId": "PRJ1", "cpu": 999, "ram": -5, "disk": "abc",
    })
    assert r.status_code == 200, r.text
    health = fake_db.reference("neural/nodes/PRJ1/health").get()
    assert health["cpu"] == 100
    assert health["ram"] == 0
    assert health["disk"] == 0


def test_sanitize_string_escapes_html():
    from app.routers.projects import sanitize_string
    assert sanitize_string('<img src=x onerror=alert(1)>') == "&lt;img src=x onerror=alert(1)&gt;"
    assert sanitize_string('a"b\'c&d') == "a&quot;b&#x27;c&amp;d"


def test_sanitize_string_truncates_and_strips_nulls():
    from app.routers.projects import sanitize_string
    assert sanitize_string("a\x00b", max_length=10) == "ab"
    assert len(sanitize_string("x" * 500, max_length=50)) == 50


def test_clamp_number_bounds():
    from app.routers.projects import clamp_number
    assert clamp_number(200, 0, 100) == 100.0
    assert clamp_number("50", 0, 100) == 50.0
    assert clamp_number("abc", 0, 100) == 0.0
    assert clamp_number(-3, 0, 100) == 0.0
