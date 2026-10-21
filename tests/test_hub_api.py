"""Painel HUB — testes das rotas /api/hub/* (ingestão HMAC + leitura admin)."""
import hashlib
import hmac
import os

import pytest

HUB_SECRET = "test-hub-secret"
WEB_TOKEN = "test-hub-web-token"


def _ingest_headers():
    sig = hmac.new(HUB_SECRET.encode(), b"hub-ingest", hashlib.sha256).hexdigest()
    return {"X-Hub-Agent-Secret": sig}


def _web_headers():
    return {"X-Hub-Agent-Secret": WEB_TOKEN}


def _admin_headers():
    return {"Authorization": "Bearer valid-admin"}


# ─────────────────────────────────────────────────────────────
# INGESTÃO
# ─────────────────────────────────────────────────────────────

def test_events_sem_secret_403(app_env, fake_db, client):
    r = client.post("/api/hub/events", json={"section": "web", "data": {"lcp_ms": 1000}})
    assert r.status_code == 403


def test_events_secret_errado_403(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers={"X-Hub-Agent-Secret": "abc"},
        json={"section": "web", "data": {"lcp_ms": 1000}},
    )
    assert r.status_code == 403


def test_events_sem_secret_configurado_503(app_env, fake_db, client, monkeypatch):
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "HUB_AGENT_SECRET", "")
    monkeypatch.setattr(cfg.settings, "HUB_WEB_TOKEN", "")
    monkeypatch.delenv("HUB_AGENT_SECRET", raising=False)
    monkeypatch.delenv("HUB_WEB_TOKEN", raising=False)
    r = client.post("/api/hub/events", json={"section": "web", "data": {"lcp_ms": 1000}})
    assert r.status_code == 503


def test_events_grava_dados_saneados(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={
            "section": "web",
            "source": "cinecash-web",
            "data": {"lcp_ms": 99999, "ttfb_ms": "350", "error_rate_5xx": 0.5, "unknown_field": 1},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    # clamp: lcp_ms limitado ao máximo (60000)
    assert body["stored"]["lcp_ms"] == 60000
    assert body["stored"]["ttfb_ms"] == 350
    # campo fora da whitelist é descartado
    assert "unknown_field" not in body["stored"]

    stored = fake_db.reference("hub/performance/web").get()
    assert stored["lcp_ms"] == 60000
    # histórico de série temporal criado
    hist = fake_db.reference("hub/performance/history/web").get()
    assert isinstance(hist, dict) and len(hist) == 1


def test_events_secao_invalida_400(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "hacker", "data": {"x": 1}},
    )
    assert r.status_code == 400


def test_events_payload_sem_campos_validos_400(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "web", "data": {"foo": 1}},
    )
    assert r.status_code == 400


def test_events_hot_ip_validado(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "apk", "data": {"invalid_signature_hits": 2, "hot_ip": "não é ip"}},
    )
    assert r.status_code == 200, r.text
    assert "hot_ip" not in r.json()["stored"]

    r2 = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "apk", "data": {"hot_ip": "198.51.100.7"}},
    )
    assert r2.json()["stored"]["hot_ip"] == "198.51.100.7"


def test_events_funnels_saneado(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={
            "section": "funnels",
            "data": {"steps": [
                {"id": "a<b>", "name": "Login", "entered": 100, "converted": "50"},
                "invalido",
            ]},
        },
    )
    assert r.status_code == 200, r.text
    steps = r.json()["stored"]["steps"]
    assert len(steps) == 1
    assert steps[0]["id"] == "a&lt;b&gt;"
    assert steps[0]["converted"] == 50.0


def test_events_dispara_quarentena_autonoma_em_correlacao_critica(app_env, fake_db, client):
    """Assinatura inválida + rps em massa => quarentena automática do IP."""
    client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "api", "data": {"rps": 200}},
    )
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "apk", "data": {"invalid_signature_hits": 9, "hot_ip": "203.0.113.5"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correlations"] >= 1
    actions = body["autonomous_actions"]
    assert any(a.get("action") == "quarantine_ip" for a in actions)

    quarantine = fake_db.reference("hub/security/quarantine").get()
    assert isinstance(quarantine, dict) and len(quarantine) == 1
    log = fake_db.reference("hub/actions").get()
    assert any(a.get("type") == "quarantine_ip" for a in log.values())


# ─────────────────────────────────────────────────────────────
# LEITURA (admin)
# ─────────────────────────────────────────────────────────────

def test_overview_exige_token(client):
    r = client.get("/api/hub/overview")
    assert r.status_code == 401


def test_overview_negue_nao_admin(app_env, fake_db, client, fake_auth):
    r = client.get("/api/hub/overview", headers={"Authorization": "Bearer valid-user"})
    assert r.status_code == 403


def test_overview_ok_para_admin(app_env, fake_db, fake_auth, client):
    client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "sessions", "data": {"active_now": 42, "web": 30, "app": 12}},
    )
    r = client.get("/api/hub/overview", headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["health"]["score"] == 100
    assert body["pillars"]["tracking"]["sessions"]["active_now"] == 42
    assert body["correlations"] == []


def test_pilar_desconhecido_404(app_env, fake_db, fake_auth, client):
    r = client.get("/api/hub/qualquer", headers=_admin_headers())
    assert r.status_code == 404


def test_pilares_ok(app_env, fake_db, fake_auth, client):
    for pillar in ("performance", "tracking", "security"):
        r = client.get(f"/api/hub/{pillar}", headers=_admin_headers())
        assert r.status_code == 200, r.text
        assert r.json()["pillar"] == pillar


def test_correlations_endpoint(app_env, fake_db, fake_auth, client):
    client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "auth", "data": {"impossible_travel": 2}},
    )
    r = client.get("/api/hub/correlations", headers=_admin_headers())
    assert r.status_code == 200
    items = r.json()["correlations"]
    assert items and items[0]["severity"] == "high"


# ─────────────────────────────────────────────────────────────
# AÇÕES
# ─────────────────────────────────────────────────────────────

def test_action_quarantine_ip_manual(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "quarantine_ip", "params": {"ip": "192.0.2.10"}, "reason": "suspeita"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"]["status"] == "applied"
    quarantine = fake_db.reference("hub/security/quarantine").get()
    assert len(quarantine) == 1
    # trilha de auditoria administrativa
    audit = fake_db.reference("logs/admin_actions").get()
    assert any(a.get("action") == "hub_action_quarantine_ip" for a in audit.values())


def test_action_release_ip(app_env, fake_db, fake_auth, client):
    client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "quarantine_ip", "params": {"ip": "192.0.2.11"}},
    )
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "release_ip", "params": {"ip": "192.0.2.11"}},
    )
    assert r.status_code == 200
    assert r.json()["result"]["status"] == "applied"
    assert fake_db.reference("hub/security/quarantine").get() in (None, {})


def test_action_revoke_access(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "revoke_access", "params": {"uid": "U9"}, "reason": "conta roubada"},
    )
    assert r.status_code == 200
    assert fake_db.reference("hub/access_revoked/U9").get()["active"] is True


def test_action_tipo_invalido_400(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "drop_database", "params": {}},
    )
    assert r.status_code == 400


def test_action_ip_invalido_400(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "quarantine_ip", "params": {"ip": "999.999.999.999"}},
    )
    assert r.status_code == 400


def test_actions_log_endpoint(app_env, fake_db, fake_auth, client):
    client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "quarantine_ip", "params": {"ip": "192.0.2.12"}},
    )
    r = client.get("/api/hub/actions", headers=_admin_headers())
    assert r.status_code == 200
    assert len(r.json()["actions"]) >= 1


def test_quarentena_duplicada_e_skipped(app_env, fake_db, fake_auth, client):
    payload = {"type": "quarantine_ip", "params": {"ip": "192.0.2.13"}}
    client.post("/api/hub/actions", headers=_admin_headers(), json=payload)
    r = client.post("/api/hub/actions", headers=_admin_headers(), json=payload)
    assert r.status_code == 200
    assert r.json()["result"]["status"] == "skipped"


# ─────────────────────────────────────────────────────────────
# AGENTE WEB (token restrito)
# ─────────────────────────────────────────────────────────────

def test_web_token_aceita_secao_web(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_web_headers(),
        json={"section": "web", "source": "site", "data": {"lcp_ms": 1800, "cls": 0.05}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stored"]["lcp_ms"] == 1800


def test_web_token_nega_secao_seguranca(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_web_headers(),
        json={"section": "apk", "data": {"invalid_signature_hits": 1}},
    )
    assert r.status_code == 403
    assert fake_db.reference("hub/security/apk").get() is None


def test_web_token_nega_secao_user_context(app_env, fake_db, client):
    """Anti-spoofing: token estático do navegador não pode forjar contexto de terceiros."""
    r = client.post(
        "/api/hub/events",
        headers=_web_headers(),
        json={"section": "user_context", "data": {"uid": "U1", "root": 1}},
    )
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────
# USER_CONTEXT (contexto do usuário para o suporte)
# ─────────────────────────────────────────────────────────────

def test_user_context_grava_por_uid(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={
            "section": "user_context",
            "source": "android-agent",
            "data": {"uid": "U77", "platform": "android", "app_version": "4.2.0",
                     "network_type": "wifi", "root": 1, "last_screen": "Pagamento"},
        },
    )
    assert r.status_code == 200, r.text
    stored = fake_db.reference("hub/tracking/user_context/U77").get()
    assert stored["platform"] == "android"
    assert stored["root"] == 1
    assert stored["app_version"] == "4.2.0"


def test_user_context_sem_uid_400(app_env, fake_db, client):
    r = client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "user_context", "data": {"platform": "ios"}},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────
# COPILOT CONTEXTUAL (brief do atendimento)
# ─────────────────────────────────────────────────────────────

def test_copilot_brief_completo(app_env, fake_db, fake_auth, client):
    fake_db.reference("users/U42").set({"email": "maria@test.com", "fullname": "Maria"})
    client.post(
        "/api/hub/events",
        headers=_ingest_headers(),
        json={"section": "user_context",
              "data": {"uid": "U42", "platform": "android", "app_version": "4.2.0",
                       "network_type": "4g", "root": 1, "last_screen": "Pagamento"}},
    )
    client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "revoke_access", "params": {"uid": "U42"}, "reason": "teste"},
    )
    r = client.get("/api/hub/copilot?query=U42", headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["uid"] == "U42"
    assert "ROOT_DEVICE" in body["flags"]
    assert "ACCESS_REVOKED" in body["flags"]
    assert "Root" in body["summary"]


def test_copilot_resolve_por_email(app_env, fake_db, fake_auth, client):
    fake_db.reference("users/U42").set({"email": "maria@test.com"})
    r = client.get("/api/hub/copilot?query=maria@test.com", headers=_admin_headers())
    assert r.status_code == 200
    assert r.json()["uid"] == "U42"


def test_copilot_usuario_nao_encontrado_404(app_env, fake_db, fake_auth, client):
    r = client.get("/api/hub/copilot?query=nao-existe", headers=_admin_headers())
    assert r.status_code == 404


def test_copilot_query_vazia_400(app_env, fake_db, fake_auth, client):
    r = client.get("/api/hub/copilot", headers=_admin_headers())
    assert r.status_code == 400


def test_copilot_exige_admin(client):
    r = client.get("/api/hub/copilot?query=x")
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────
# ROLLOUT (block/unblock + consulta do agente)
# ─────────────────────────────────────────────────────────────

def test_action_block_e_unblock_rollout(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "block_rollout", "params": {"app_version": "4.3.0"}, "reason": "crash em massa"},
    )
    assert r.status_code == 200, r.text
    assert fake_db.reference("hub/performance/blocked_rollouts/4.3.0").get()["active"] is True

    r2 = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "unblock_rollout", "params": {"app_version": "4.3.0"}},
    )
    assert r2.status_code == 200
    assert r2.json()["result"]["status"] == "applied"
    assert fake_db.reference("hub/performance/blocked_rollouts/4.3.0").get() is None


def test_action_block_rollout_sem_versao_400(app_env, fake_db, fake_auth, client):
    r = client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "block_rollout", "params": {}},
    )
    assert r.status_code == 400


def test_agent_rollout_status_com_hmac(app_env, fake_db, fake_auth, client):
    client.post(
        "/api/hub/actions",
        headers=_admin_headers(),
        json={"type": "block_rollout", "params": {"app_version": "4.4.0"}},
    )
    r = client.get("/api/hub/agent/rollout/4.4.0", headers=_ingest_headers())
    assert r.status_code == 200, r.text
    assert r.json()["blocked"] is True

    r2 = client.get("/api/hub/agent/rollout/9.9.9", headers=_ingest_headers())
    assert r2.status_code == 200
    assert r2.json()["blocked"] is False


def test_agent_rollout_status_sem_secret_403(client):
    r = client.get("/api/hub/agent/rollout/1.0.0")
    assert r.status_code == 403


def test_hub_web_agent_servido_publico(client):
    r = client.get('/hub-web-agent.js')
    assert r.status_code == 200
    assert 'javascript' in r.headers['content-type']
    assert '/api/hub/events' in r.text