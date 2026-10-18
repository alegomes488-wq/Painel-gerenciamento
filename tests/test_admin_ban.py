"""TAREFA 2.2: POST /api/admin/ban — claim revocation, self-ban guard, auditoria."""
import pytest
from app.services.firebase_service import get_db


def _persisted(fdb, path):
    node = fdb.data
    for part in path.split("/"):
        if not part:
            continue
        node = node.get(part)
        if node is None:
            return None
    return node


@pytest.fixture
def fake_auth_admin_api(monkeypatch):
    """Mock de auth do Admin SDK para o router admin (get_user/set_claims/revoke)."""
    calls = {"ban": [], "unban": [], "revoked": [], "get_user": 0}

    class FakeUser:
        def __init__(self, uid, claims):
            self.uid = uid
            self.custom_claims = claims

    def _get_user(uid):
        calls["get_user"] += 1
        return FakeUser(uid, {"admin": True})

    def _set_claims(uid, claims):
        calls["ban" if not claims.get("admin") else "unban"].append((uid, claims))

    def _revoke(uid):
        calls["revoked"].append(uid)

    import firebase_admin.auth as fa
    monkeypatch.setattr(fa, "get_user", _get_user)
    monkeypatch.setattr(fa, "set_custom_user_claims", _set_claims)
    monkeypatch.setattr(fa, "revoke_refresh_tokens", _revoke)
    return calls


def test_admin_ban_revokes_claims_and_logs(app_env, fake_db, fake_auth, fake_auth_admin_api, client):
    """Admin bane usuário => claim admin removida, tokens revogados, log gravado."""
    fake_db.reference("system/admin_uids/U1").set(True)  # actor admin na allowlist
    fake_db.reference("users/TARGET").set({"email": "t@t.com"})

    # U1 é admin pela allowlist; token "valid-admin" decodifica para U1
    r = client.post(
        "/api/admin/ban",
        json={"uid": "TARGET", "action": "ban", "reason": "fraude"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "ban"

    # Claim removida + tokens revogados
    assert fake_auth_admin_api["revoked"] == ["TARGET"]
    assert any(uid == "TARGET" for uid, _ in fake_auth_admin_api["ban"])

    # Status no RTDB
    assert _persisted(fake_db, "users/TARGET/status") == "banido"

    # Log de auditoria
    logs = _persisted(fake_db, "logs/admin_actions") or {}
    assert len(logs) >= 1


def test_admin_ban_self_ban_403(app_env, fake_db, fake_auth, fake_auth_admin_api, client):
    """Self-ban: actor não pode banir a si mesmo => 403."""
    fake_db.reference("system/admin_uids/U1").set(True)
    r = client.post(
        "/api/admin/ban",
        json={"uid": "U1", "action": "ban", "reason": "teste"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 403
    assert "si mesmo" in r.json()["detail"]


def test_admin_ban_non_admin_403(app_env, fake_db, fake_auth, fake_auth_admin_api, client):
    """Actor sem admin (U2) => 403."""
    fake_db.reference("system/admin_uids/U2").set(False)  # não admin
    r = client.post(
        "/api/admin/ban",
        json={"uid": "TARGET", "action": "ban", "reason": "x"},
        headers={"Authorization": "Bearer valid-user"},  # U2
    )
    assert r.status_code == 403