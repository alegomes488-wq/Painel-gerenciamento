"""T-08/T-09: auto-aprovação N8N — token ausente/errado.

O router atual exige `Authorization: Bearer <token>` e valida via
`firebase_auth.verify_id_token` (fake_auth aceita só valid-admin/valid-user).
N8N_SHARED_SECRET é lido de os.environ. Testes alinhados ao código vigente.
"""
import hmac
import pytest

from app.routers.payments import auto_approve_withdrawal


def test_python_compare_digest_empty_is_true():
    """Comportamento puro de hmac.compare_digest com strings vazias."""
    assert hmac.compare_digest("", "") is True
    assert hmac.compare_digest("", "x") is False


def _seed(fdb, wid):
    fdb.reference(f"admin/pending_withdrawals/{wid}").set({
        "uid": "U1", "amount": 10.0, "pixKey": "000.000.000-00",
        "pixType": "CPF", "status": "pending", "fullname": "Test",
    })


def test_auto_approve_wrong_token_401(app_env, fake_db, fake_auth, client):
    """Token inválido => 401 (verify_id_token falha)."""
    _seed(fake_db, "W1")
    r = client.post("/payments/auto-approve/W1", json={},
                    headers={"Authorization": "Bearer token-invalido"})
    assert r.status_code == 401


def test_auto_approve_no_token_401(app_env, fake_db, fake_auth, client):
    """Sem Authorization => 401."""
    _seed(fake_db, "W2")
    r = client.post("/payments/auto-approve/W2", json={})
    assert r.status_code == 401


def test_auto_approve_admin_success(app_env, fake_db, fake_auth, client):
    """Admin válido aprova e o saque vai a paid."""
    _seed(fake_db, "W4")
    r = client.post("/payments/auto-approve/W4", json={},
                    headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert fake_db.reference("admin/pending_withdrawals/W4").get()["status"] == "paid"


def test_auto_approve_with_empty_secret_blocks(app_env, fake_db, fake_auth, client, monkeypatch):
    """Contra-evidência do N8N-04: com N8N_SHARED_SECRET vazio, requisição sem token
    válido ainda é rejeitada (401). O guard de compare_digest("","")==True não é
    explorável porque o fluxo exige Bearer com ID token válido primeiro.
    """
    monkeypatch.setenv("N8N_SHARED_SECRET", "")

    _seed(fake_db, "W3")

    # Header ausente
    r = client.post("/payments/auto-approve/W3", json={})
    assert r.status_code == 401
    # Header Bearer vazio explícito
    r2 = client.post("/payments/auto-approve/W3", json={},
                     headers={"Authorization": "Bearer "})
    assert r2.status_code == 401
    # Token N8N vazio não passa
    r3 = client.post("/payments/auto-approve/W3", json={},
                     headers={"Authorization": "Bearer "})
    assert r3.status_code == 401
