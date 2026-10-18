"""TAREFA 3.1/3.2: endpoints CRUD + toggle de projetos (server-side, ID do servidor)."""
import pytest


def _seed_project(fdb, pid="PRJ_A", secret=None):
    data = {"id": pid, "name": "Site A", "type": "website", "identifier": "https://a.com"}
    if secret:
        data["agent_secret"] = secret
    fdb.reference(f"neural/nodes/{pid}").set(data)


def test_analyze_project_invalid_identifier(app_env, fake_db, fake_auth, client):
    """identificador malicioso (javascript:) é rejeitado."""
    r = client.post(
        "/api/project/analyze",
        json={"type": "website", "identifier": "javascript:alert(1)"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 400


def test_analyze_project_ok(app_env, fake_db, fake_auth, client):
    """URL válida retorna metadados sem gravar."""
    r = client.post(
        "/api/project/analyze",
        json={"type": "website", "identifier": "https://meusite.com.br"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert r.json()["identifier"] == "https://meusite.com.br"


def test_save_project_generates_server_id(app_env, fake_db, fake_auth, client):
    """save gera ID no servidor (push key) e grava com whitelist de campos."""
    mock_push = {"key": "SERV-1"}

    class _Ref:
        def __init__(self, fl):
            self.fl = fl

    # monkeypatch push().key para retornar id estável
    import app.routers.projects as prj
    orig_ref = prj.db.reference

    class FakePush:
        key = "SRVKEY123"
        def set(self, v): fake_db.reference("neural/nodes/SRVKEY123").set(v)

    class FakeParent:
        def push(self): return FakePush()
        def get(self): return orig_ref("neural/nodes").get()

    def fake_reference(path):
        if path == "neural/nodes":
            return FakeParent()
        return orig_ref(path)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(prj.db, "reference", fake_reference)
    try:
        r = client.post(
            "/api/project/save",
            json={"type": "android", "identifier": "com.app.id", "name": "App X",
                  "malicious_field": "hack"},
            headers={"Authorization": "Bearer valid-admin"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["id"] == "SRVKEY123"
        # Whitelist: campo extra não foi gravado
        saved = fake_db.reference("neural/nodes/SRVKEY123").get()
        assert saved["identifier"] == "com.app.id"
        assert "malicious_field" not in saved
    finally:
        monkeypatch.undo()


def test_toggle_project_status(app_env, fake_db, fake_auth, client):
    """toggle grava em health/override (não em health direto) separando agente/operador."""
    _seed_project(fake_db)
    r = client.post(
        "/api/project/toggle",
        json={"id": "PRJ_A", "status": "offline"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200, r.text
    node = fake_db.reference("neural/nodes/PRJ_A/health/override").get()
    assert node == {"status": "offline", "by": "operator"}


def test_toggle_project_not_found(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/project/toggle",
        json={"id": "NAOEXISTE", "status": "online"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 404


def test_remove_project(app_env, fake_db, fake_auth, client):
    _seed_project(fake_db)
    r = client.post(
        "/api/project/remove",
        json={"id": "PRJ_A"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert fake_db.reference("neural/nodes/PRJ_A").get() is None