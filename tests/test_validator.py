"""TAREFA 5: Validador integrado (usa as fixtures fake_db/fake_auth do conftest)."""
import hmac
import hashlib
import json
import pytest


def _webhook_hmac(payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest(), body


# ── SEGURANÇA ──
def test_security_headers_present(app_env, client):
    r = client.get("/health")
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "Referrer-Policy" in r.headers


def test_auth_no_token_401(app_env, client):
    assert client.get("/api/secops/health-audit").status_code == 401


def test_auth_invalid_token_401(app_env, fake_auth, client):
    assert client.get("/api/secops/health-audit",
                      headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_n8n_wrong_secret_401(app_env, fake_db, fake_auth, client):
    assert client.post("/payments/auto-approve/W_N8N",
                       headers={"X-N8N-Secret": "errado"}).status_code == 401


def test_report_without_agent_secret_rejected(app_env, fake_db, client):
    r = client.post("/api/monitor/report", json={"projectId": "X", "cpu": 1})
    # 403 (segredo errado/ausente) OU 404 (projeto não existe). NUNCA 200 sem secret.
    assert r.status_code in (403, 404)


def test_rate_limit_429(app_env, client):
    for _ in range(35):
        r = client.get("/health")
    assert r.status_code == 429


# ── FINANCEIRO ──
def test_webhook_wrong_hmac_403(app_env, client):
    r = client.post("/payments/webhook", json={"event": "TRANSFER_PAID", "payment": {}},
                    headers={"X-Webhook-Token": "errado"})
    assert r.status_code == 403


def test_webhook_correct_hmac(app_env, fake_db, client):
    payload = {"event": "TRANSFER_PAID",
               "payment": {"id": "val-idemp", "externalReference": "wid_VAL", "value": 10.0}}
    sig, body = _webhook_hmac(payload)
    r = client.post("/payments/webhook", content=body,
                    headers={"X-Webhook-Token": sig, "Content-Type": "application/json"})
    assert r.status_code == 200, r.text


def test_webhook_replay_idempotent(app_env, fake_db, client):
    fake_db.reference("admin/pending_withdrawals/W_RP").set({
        "uid": "U1", "amount": 10.0, "pixKey": "000.000.000-00",
        "pixType": "CPF", "status": "pending", "fullname": "T",
    })
    payload = {"event": "TRANSFER_PAID",
               "payment": {"id": "ev-replay", "externalReference": "wid_W_RP", "value": 10.0}}
    sig, body = _webhook_hmac(payload)
    r1 = client.post("/payments/webhook", content=body,
                     headers={"X-Webhook-Token": sig, "Content-Type": "application/json"})
    r2 = client.post("/payments/webhook", content=body,
                     headers={"X-Webhook-Token": sig, "Content-Type": "application/json"})
    assert r1.status_code == 200
    assert r2.status_code == 200  # duplicata idempotente


# ── FUNCIONAL ──
def test_secops_endpoint_ok(app_env, fake_auth, client):
    r = client.get("/api/secops/health-audit", headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 200


def test_watch_endpoints_exist(app_env, fake_db, fake_auth, client):
    for ep in ["/api/project/analyze", "/api/project/save", "/api/project/remove", "/api/project/toggle"]:
        r = client.post(ep, json={}, headers={"Authorization": "Bearer valid-admin"})
        assert r.status_code not in (404, 500)


# ── QUALIDADE ──
def test_reads_public_rules_justified(app_env):
    import json as _json
    rules = _json.load(open("database.rules.json"))["rules"]
    # /status foi apertado para auth != null (não mais público)
    assert "true" not in str(rules.get("status", {}).get(".read", ""))
    # Apenas vapidKey e maintenance permanecem públicos (justificados)
    public_config = rules["config"].get(".read", "")
    assert rules["config"]["vapidKey"].get(".read") is True
    assert rules["config"]["maintenance"].get(".read") is True


def test_allowed_amounts_externalized():
    content = open("functions/index.js").read()
    assert "allowedAmounts" in content and "config/withdrawals" in content
