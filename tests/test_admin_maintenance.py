"""TAREFA 5.1 — /api/admin/maintenance (GET e POST).

Cobre o requisito central: o painel e o site passam a usar a MESMA fonte de
verdade (`config/maintenance`), com autorizacao server-side e sem possibility
de o painel reportar sucesso quando o RTDB nao confirma a gravacao.

Casos cobertos:
  - 401 sem autenticacao
  - 403 usuario comum (nao admin)
  - 422 `enabled` ausente / string / numero (booleano real exigido)
  - 422 ativar sem `confirm: true`
  - desativar NAO exige confirm (desbloqueio sempre possivel)
  - gravacao real de booleano no no certo
  - confirmacao divergente vira 500 (nao "salvou" silencioso)
  - auditoria gravada
  - 503 quando a leitura falha (read_ok=false => nao assume manutencao)
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """
    Isola este arquivo do rate limiter global em memoria.

    O limiter e um singleton de processo com buckets por IP, e o TestClient usa
    sempre o mesmo IP ("testclient"). O limite de /api/admin e 10 req/min, entao
    esta suíte (que faz mais de 10 chamadas) tombaria em 429 sem este reset.

    IMPORTANTE: isto NAO afrouxa o limite de producao. O reset acontece apenas
    entre testes, para que cada caso comece com a janela limpa. Existe um teste
    dedicado (tests/test_validator.py::test_rate_limit_429) que comprova que o
    429 continua funcionando em producao.
    """
    from app.core.security import rate_limiter

    rate_limiter._buckets.clear()
    yield
    rate_limiter._buckets.clear()


def _persisted(fdb, path):
    node = fdb.data
    for part in path.split("/"):
        if not part:
            continue
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


# --------------------------------------------------------------------------
# Autorizacao
# --------------------------------------------------------------------------

def test_maintenance_post_401_sem_token(app_env, fake_db, fake_auth, client):
    """Sem Authorization => 401 (o middleware admin_auth bloqueia)."""
    r = client.post("/api/admin/maintenance", json={"enabled": True, "confirm": True})
    assert r.status_code == 401


def test_maintenance_post_403_usuario_comum(app_env, fake_db, fake_auth, client):
    """Usuario autenticado sem privilegio admin => 403, e NAO grava nada."""
    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": True, "confirm": True},
        headers={"Authorization": "Bearer valid-user"},  # U2, admin=False
    )
    assert r.status_code == 403
    assert _persisted(fake_db, "config/maintenance") is None


def test_maintenance_get_401_sem_token(app_env, fake_db, fake_auth, client):
    r = client.get("/api/admin/maintenance")
    assert r.status_code == 401


def test_maintenance_get_403_usuario_comum(app_env, fake_db, fake_auth, client):
    r = client.get("/api/admin/maintenance", headers={"Authorization": "Bearer valid-user"})
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Validacao do payload
# --------------------------------------------------------------------------

def test_maintenance_enabled_ausente_422(app_env, fake_db, fake_auth, client):
    fake_db.reference("system/admin_uids/U1").set(True)
    r = client.post(
        "/api/admin/maintenance",
        json={"confirm": True},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 422
    assert "enabled" in r.json()["detail"]


@pytest.mark.parametrize("valor", ["true", "false", 1, 0, "1", "0", None, [], {}])
def test_maintenance_rejeita_nao_booleano(app_env, fake_db, fake_auth, client, valor):
    """
    Rejeita string/numero/null/lista. Motivo operacional: em JS, a string
    "false" e truthy -> o site ficaria em manutencao para sempre mesmo com o
    painel reportando sucesso.
    """
    fake_db.reference("system/admin_uids/U1").set(True)
    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": valor, "confirm": True},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 422, f"valor={valor!r} deveria ser recusado, veio {r.status_code}"
    assert _persisted(fake_db, "config/maintenance") is None


def test_maintenance_ativar_exige_confirm(app_env, fake_db, fake_auth, client):
    """Ativar sem confirm=true => 422 e nada gravado (anti-acionamento)."""
    fake_db.reference("system/admin_uids/U1").set(True)
    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": True},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 422
    assert "confirm" in r.json()["detail"]
    assert _persisted(fake_db, "config/maintenance") is None


def test_maintenance_desativar_nao_exige_confirm(app_env, fake_db, fake_auth, client):
    """
    Desligar NUNCA exige confirm: se exigisse, uma manutencao acidental ficaria
    sem caminho de saida. Pre-condicao: o no esta ligado.
    """
    fake_db.reference("system/admin_uids/U1").set(True)
    fake_db.reference("config/maintenance").set(True)

    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": False},  # sem confirm
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200, r.text
    assert _persisted(fake_db, "config/maintenance") is False


def test_maintenance_reason_acima_do_limite_422(app_env, fake_db, fake_auth, client):
    fake_db.reference("system/admin_uids/U1").set(True)
    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": True, "confirm": True, "reason": "x" * 201},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 422


def test_maintenance_body_nao_objeto_422(app_env, fake_db, fake_auth, client):
    fake_db.reference("system/admin_uids/U1").set(True)
    r = client.post(
        "/api/admin/maintenance",
        json=[True],
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Gravacao + confirmacao
# --------------------------------------------------------------------------

def test_maintenance_grava_no_caminho_correto(app_env, fake_db, fake_auth, client):
    """O no gravado tem de ser EXATAMENTE config/maintenance (fonte do site)."""
    fake_db.reference("system/admin_uids/U1").set(True)

    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": True, "confirm": True, "reason": "deploy"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["maintenance"] is True
    assert body["confirmed"] is True

    stored = _persisted(fake_db, "config/maintenance")
    assert stored is True
    # booleano real, nao string
    assert isinstance(stored, bool)


def test_maintenance_booleano_falso_gravado_como_false(app_env, fake_db, fake_auth, client):
    """`false` precisa virar False no RTDB (nao "false", nao 0)."""
    fake_db.reference("system/admin_uids/U1").set(True)
    fake_db.reference("config/maintenance").set(True)

    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": False, "confirm": True},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200
    stored = _persisted(fake_db, "config/maintenance")
    assert stored is False
    assert isinstance(stored, bool)


def test_maintenance_grava_auditoria(app_env, fake_db, fake_auth, client):
    """Toda acao fica em logs/admin_actions com actor, enabled e motivo."""
    fake_db.reference("system/admin_uids/U1").set(True)

    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": True, "confirm": True, "reason": "deploy 4.2.0"},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 200

    logs = _persisted(fake_db, "logs/admin_actions") or {}
    assert len(logs) >= 1

    found = None
    for entry in logs.values():
        if entry.get("action") == "admin_maintenance":
            found = entry
            break

    assert found is not None, "nenhuma acao admin_maintenance auditada"
    assert found["enabled"] is True
    assert found["reason"] == "deploy 4.2.0"
    assert found["path"] == "config/maintenance"
    assert found["actor_uid"] == "U1"


def test_maintenance_confirmacao_divergente_vira_500(app_env, fake_db, fake_auth, client,
                                                     monkeypatch):
    """
    Se a leitura de confirmacao devolver algo diferente do pedido, a API tem de
    falhar (500) e NAO retornar 'success'. Era exatamente esse o risco de o
    painel dizer "salvou" com o site ainda em manutencao.
    """
    fake_db.reference("system/admin_uids/U1").set(True)

    real_ref_cls = None
    import app.routers.admin as admin_mod

    original_get_db = admin_mod.get_db
    fdb = fake_db

    class DivergentRef:
        def __init__(self, ref):
            self._ref = ref

        def set(self, value):
            # grava, mas a leitura devolve o valor CONTRARIO
            self._ref.set(value)

        def get(self):
            return not self._ref._node()

    class DivergentDB:
        def reference(self, path):
            return DivergentRef(fdb.reference(path))

    monkeypatch.setattr(admin_mod, "get_db", lambda: DivergentDB())

    r = client.post(
        "/api/admin/maintenance",
        json={"enabled": True, "confirm": True},
        headers={"Authorization": "Bearer valid-admin"},
    )
    assert r.status_code == 500
    assert "onfirma" in r.json()["detail"] or "Confirmacao" in r.json()["detail"]


# --------------------------------------------------------------------------
# GET (leitura / reconciliacao)
# --------------------------------------------------------------------------

def test_maintenance_get_reflete_valor_do_rtdb(app_env, fake_db, fake_auth, client):
    fake_db.reference("system/admin_uids/U1").set(True)
    fake_db.reference("config/maintenance").set(True)

    r = client.get("/api/admin/maintenance", headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["read_ok"] is True
    assert body["maintenance"] is True
    assert body["stored_raw_type"] == "bool"


def test_maintenance_get_no_ausente_reporta_operacional(app_env, fake_db, fake_auth, client):
    """No ausente => falsy no site => o painel deve dizer 'operacional'."""
    fake_db.reference("system/admin_uids/U1").set(True)

    r = client.get("/api/admin/maintenance", headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["read_ok"] is True
    assert body["maintenance"] is False
    assert body["stored_raw_type"] == "NoneType"


def test_maintenance_get_falha_leitura_503_read_ok_false(app_env, fake_db, fake_auth,
                                                         client, monkeypatch):
    """
    Falha de leitura => 503 com read_ok=false. O painel usa isso para mostrar
    CONFIG_LOAD_ERROR, e nao para declarar manutencao ativa.
    """
    fake_db.reference("system/admin_uids/U1").set(True)
    import app.routers.admin as admin_mod

    class BrokenDB:
        def reference(self, path):
            raise RuntimeError("PERMISSION_DENIED")

    monkeypatch.setattr(admin_mod, "get_db", lambda: BrokenDB())

    r = client.get("/api/admin/maintenance", headers={"Authorization": "Bearer valid-admin"})
    assert r.status_code == 503
    body = r.json()
    assert body["read_ok"] is False
    assert body["maintenance"] is None
    assert body["status"] == "unavailable"
