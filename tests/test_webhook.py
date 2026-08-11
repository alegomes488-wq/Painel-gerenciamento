"""T-10: webhook Asaas — token ausente/errado => 403. T-11/T-12: idempotência.

O router atual lê WEBHOOK_SECRET de os.environ (no import) e espera payload com
`payment.externalReference` no formato "wid_<wid>" + `payment.value`. O token é
HMAC-SHA256(secret, body) em X-Webhook-Token.
"""
import hmac
import hashlib
import json

import pytest


def _body(payload: dict) -> bytes:
    # Mesma serialização do httpx (TestClient envia json= assim):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def _sign(payload: dict) -> str:
    return hmac.new(b"test-webhook-secret", _body(payload), hashlib.sha256).hexdigest()


def _post(client, payload: dict, sign: bool = True):
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Webhook-Token"] = _sign(payload)
    else:
        headers["X-Webhook-Token"] = "errado"
    return client.post("/payments/webhook", content=_body(payload), headers=headers)


def _paid_body(wid="W1", value=10.0):
    return {
        "event": "TRANSFER_PAID",
        "payment": {"id": "A1", "externalReference": f"wid_{wid}", "value": value},
    }


def _failed_body(wid="W1", value=10.0):
    return {
        "event": "TRANSFER_FAILED",
        "payment": {"id": "A1", "externalReference": f"wid_{wid}", "value": value},
    }


def _seed_pending(fdb, wid="W1"):
    fdb.reference(f"admin/pending_withdrawals/{wid}").set({
        "uid": "U1", "amount": 10.0, "pixKey": "000.000.000-00",
        "pixType": "CPF", "status": "pending", "fullname": "Test",
    })


def test_webhook_no_token_403(app_env, fake_db, client):
    r = client.post("/payments/webhook", json={"event": "TRANSFER_PAID", "payment": {}})
    assert r.status_code == 403


def test_webhook_wrong_token_403(app_env, fake_db, client):
    r = _post(client, {"event": "TRANSFER_PAID", "payment": {}}, sign=False)
    assert r.status_code == 403


def test_webhook_transfer_paid_sets_status(app_env, fake_db, client):
    _seed_pending(fake_db)
    r = _post(client, _paid_body())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"
    assert fake_db.reference("admin/pending_withdrawals/W1").get()["status"] == "paid"


def test_webhook_transfer_paid_replay_idempotent(app_env, fake_db, client):
    """T-11: segundo webhook TRANSFER_PAID é ignorado (estado terminal)."""
    _seed_pending(fake_db)
    body = _paid_body()
    assert _post(client, body).status_code == 200
    paid_at_1 = fake_db.reference("admin/pending_withdrawals/W1").get().get("paid_at")
    assert _post(client, body).status_code == 200
    paid_at_2 = fake_db.reference("admin/pending_withdrawals/W1").get().get("paid_at")
    assert paid_at_1 == paid_at_2


def test_webhook_transfer_failed_refund_once(app_env, fake_db, client):
    """T-12: estorno idempotente — segundo TRANSFER_FAILED não credita de novo."""
    _seed_pending(fake_db)
    fake_db.reference("users/U1").set({"balance": 100.0})
    body = _failed_body()
    assert _post(client, body).status_code == 200
    assert fake_db.reference("users/U1").get()["balance"] == 110.0
    assert _post(client, body).status_code == 200
    assert fake_db.reference("users/U1").get()["balance"] == 110.0
    assert fake_db.reference("admin/pending_withdrawals/W1").get()["status"] == "refunded"


def test_webhook_unknown_mapping_not_found(app_env, fake_db, client):
    """T-13: wid sem saque correspondente."""
    r = _post(client, _paid_body("NAO_EXISTE"))
    assert r.status_code == 200
    assert r.json()["status"] == "withdrawal_not_found"
