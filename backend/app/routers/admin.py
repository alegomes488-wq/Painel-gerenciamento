"""
Routers de administraÃ§Ã£o de usuÃ¡rios â€” CyberCore IA

TAREFA 2.2:
  - Endpoint POST /api/admin/ban (action ban|unban) via backend
  - Revoga custom claim admin + refresh tokens
  - Grava status no RTDB via Admin SDK
  - Loga em /logs/admin_actions
  - Self-ban guard
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from firebase_admin import auth as firebase_auth
from app.services.firebase_service import get_auth, get_db
from app.dependencies import get_current_user, is_admin_user, log_admin_action

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/ban")
async def admin_ban(request: Request):
    """
    Bane/desbane um usuÃ¡rio com revogaÃ§Ã£o de claim admin, tokens e auditoria.

    Body JSON: { "uid": "...", "action": "ban" | "unban", "reason": "..." }
    """
    # 1. Autentica o ACTOR (deve ser admin)
    try:
        decoded = get_current_user(request)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    actor_uid = decoded.get("uid", "")
    if not is_admin_user(actor_uid, decoded):
        raise HTTPException(status_code=403, detail="Acesso administrativo exigido")

    # 2. Parse body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON invÃ¡lido")

    target_uid = (body.get("uid") or "").strip()
    action = (body.get("action") or "").strip().lower()
    reason = (body.get("reason") or "").strip()

    if not target_uid:
        raise HTTPException(status_code=400, detail="uid Ã© obrigatÃ³rio")
    if action not in ("ban", "unban"):
        raise HTTPException(status_code=400, detail="action deve ser 'ban' ou 'unban'")

    # 3. Self-ban guard â€” actor nÃ£o pode banir a si mesmo
    if actor_uid == target_uid:
        raise HTTPException(status_code=403, detail="NÃ£o Ã© permitido banir a si mesmo")

    db = get_db()
    try:
        if action == "ban":
            # Revoga claim admin (nÃ£o remove inteiramente, apenas assegura admin=false)
            try:
                u = get_auth().get_user(target_uid)
                claims = u.custom_claims or {}
                claims["admin"] = False
                claims.pop("admin_until", None)
                get_auth().set_custom_user_claims(target_uid, claims)
                # Revoga refresh tokens para forÃ§ar novo login/refetch
                get_auth().revoke_refresh_tokens(target_uid)
            except Exception:
                # Se usuÃ¡rio nÃ£o existe, ainda marka status para consistÃªncia
                pass  # nosec

            # Grava status no RTDB via Admin SDK (bypassa Security Rules)
            db.reference(f"users/{target_uid}/status").set("banido")
        else:  # unban
            db.reference(f"users/{target_uid}/status").set("ativo")
            # NÃ£o restaura claim admin automaticamente (seguranÃ§a: exigir allowlist)

        # 4. Log de auditoria
        log_admin_action(actor_uid, f"admin_{action}", {
            "target_uid": target_uid,
            "reason": reason,
        })

        return JSONResponse({
            "status": "success",
            "action": action,
            "target_uid": target_uid
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao executar {action}: {str(e)}")


# TAREFA 3.4: ConfiguraÃ§Ãµes globais via endpoint com validaÃ§Ã£o (nunca escrita direta
# no RTDB sem validaÃ§Ã£o a partir do frontend).
import re as _re


@router.post("/config")
async def update_config(request: Request):
    """Salva configuraÃ§Ãµes do painel (CPM e WhatsApp admin) com validaÃ§Ã£o.

    Body: { "cpm": number, "adminWhatsapp": string }
    Regras:
      - cpm: 0 < cpm <= 1000
      - adminWhatsapp: E.164 (modelo +5511999999999) ou vazio (permite limpar)
    """
    # 1. Autentica actor (deve ser admin)
    try:
        decoded = get_current_user(request)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    actor_uid = decoded.get("uid", "")
    if not is_admin_user(actor_uid, decoded):
        raise HTTPException(status_code=403, detail="Acesso administrativo exigido")

    # 2. Parse + validaÃ§Ã£o
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON invÃ¡lido")

    cpm = body.get("cpm")
    wa = (body.get("adminWhatsapp") or "").strip()

    # cpm: deve ser nÃºmero em (0, 1000]
    if cpm is None:
        raise HTTPException(status_code=422, detail="cpm Ã© obrigatÃ³rio")
    try:
        cpm_f = float(cpm)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="cpm deve ser numÃ©rico")
    if not (0 < cpm_f <= 1000):
        raise HTTPException(status_code=422, detail="cpm deve estar entre 0 e 1000")

    # WhatsApp: vazio Ã© permitido (limpar); senÃ£o deve ser E.164
    if wa and not _re.match(r"^\+?[1-9]\d{8,14}$", wa):
        raise HTTPException(status_code=422, detail="adminWhatsapp deve ser E.164 (ex: +5511999999999)")

    # 3. Grava via Admin SDK no RTDB
    db = get_db()
    db.reference("config").update({
        "cpm": cpm_f,
        "adminWhatsapp": wa,
    })

    # 4. Auditoria
    log_admin_action(actor_uid, "admin_config", {
        "cpm": cpm_f,
        "adminWhatsapp_masked": (wa[:4] + "****") if wa else "",
    })

    return JSONResponse({"status": "success"})


# ============================================================================
# TAREFA 5.1 — Modo Manutencao: fonte de verdade UNICA compartilhada com o site.
#
# O site (CineCash-por-IA/www/app.js) le `config/maintenance` via onValue e
# exibe o overlay quando o valor e VERDADEIRO. Antes desta rota o painel nao
# possuia nenhuma escrita para esse no: o botao "DESCONECTAR" dos cards apenas
# alterna `neural/nodes/<id>/health/override` (online|offline).
#
# Garantias:
#   - autorizacao server-side (get_current_user + is_admin_user); o booleao do
#     navegador NUNCA decide quem pode gravar;
#   - gravacao apenas via Admin SDK (bypassa Security Rules, cujo nó `config`
#     tem .write restrito a admin) — nunca escrita direta pelo frontend;
#   - `enabled` precisa ser booleano REAL: "true", 1 e "1" sao rejeitados com 422
#     para evitar que o RTDB grave string "true" (que o JS trata como truthy,
#     travando o site em manutencao para sempre);
#   - ATIVAR exige `confirm: true`; DESATIVAR nunca exige confirmacao, para que
#     o painel sempre consiga tirar o site do ar;
#   - falha de gravacao vira 500 visivel — nunca um "salvou" silencioso;
#   - toda acao vai para /logs/admin_actions.
# ============================================================================

MAINTENANCE_PATH = "config/maintenance"
MAINTENANCE_MAX_REASON = 200


def _coerce_strict_bool(value):
    """
    Aceita SOMente booleano real do JSON (True/False).

    Rejeita strings ("true", "false"), numeros (0, 1) e None. O motivo e
    operacional: `config/maintenance` e consumido por `snapshot.val()` no site e
    por `if (isMaintenance)` no painel. Uma string "false" seria truthy em JS e
    manteria o site em manutencao mesmo apos o painel reportar sucesso.
    Retorna (ok, valor_normalizado).
    """
    if isinstance(value, bool):
        return True, value
    return False, None


@router.get("/maintenance")
async def read_maintenance(request: Request):
    """
    Le o estado atual de `config/maintenance`.

    Existe para o painel conseguir reconciliar a UI quando o listener do RTDB
    falha (por exemplo, App Check bloqueando o socket) e para o operador
    distinguir "manutencao ligada" de "nao consegui ler".
    Retorna tambem `read_ok`, para o painel nunca assumir manutencao por
    falha de leitura.
    """
    try:
        decoded = get_current_user(request)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    actor_uid = decoded.get("uid", "")
    if not is_admin_user(actor_uid, decoded):
        raise HTTPException(status_code=403, detail="Acesso administrativo exigido")

    try:
        raw = get_db().reference(MAINTENANCE_PATH).get()
    except Exception as e:
        # Falha de leitura NAO e manutencao. Sinaliza explicitamente.
        return JSONResponse({
            "status": "unavailable",
            "read_ok": False,
            "maintenance": None,
            "detail": f"Falha ao ler {MAINTENANCE_PATH}: {e}",
        }, status_code=503)

    # Snapshot.val() no JS: null/undefined => falsy. Ausente equivale a desligado.
    return JSONResponse({
        "status": "success",
        "read_ok": True,
        "maintenance": raw if isinstance(raw, bool) else bool(raw),
        "stored_raw_type": type(raw).__name__,
    })


@router.post("/maintenance")
async def set_maintenance(request: Request):
    """
    Liga/desliga o modo manutencao global do site.

    Body JSON: { "enabled": true|false, "reason": "opcional", "confirm": true }
    Regras:
      - enabled: obrigatorio e booleano real (422 caso contrario)
      - enabled=true exige confirm=true (anti-acionamento acidental)
      - enabled=false nao exige confirmacao (desbloqueio sempre possivel)
      - reason: opcional, ate 200 caracteres
    """
    # 1. Autentica e autoriza o ACTOR (server-side)
    try:
        decoded = get_current_user(request)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    actor_uid = decoded.get("uid", "")
    if not is_admin_user(actor_uid, decoded):
        raise HTTPException(status_code=403, detail="Acesso administrativo exigido")

    # 2. Parse + validacao
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON invalido")

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body deve ser um objeto JSON")

    if "enabled" not in body:
        raise HTTPException(status_code=422, detail="enabled e obrigatorio")

    ok, enabled = _coerce_strict_bool(body.get("enabled"))
    if not ok:
        raise HTTPException(
            status_code=422,
            detail="enabled deve ser booleano (true/false); string ou numero sao recusados",
        )

    # Anti-acionamento acidental: so ATIVAR exige confirmacao explicita.
    if enabled and body.get("confirm") is not True:
        raise HTTPException(
            status_code=422,
            detail="Ativar manutencao exige confirm=true",
        )

    reason = (body.get("reason") or "").strip()
    if len(reason) > MAINTENANCE_MAX_REASON:
        raise HTTPException(
            status_code=422,
            detail=f"reason deve ter no maximo {MAINTENANCE_MAX_REASON} caracteres",
        )

    # 3. Obtem a reference e grava o booleano real via Admin SDK.
    # A obtencao da reference tambem pode falhar (RTDB indisponivel), entao
    # entra no mesmo try que a escrita: erro de infraestrutura vira 500 visivel,
    # nunca um "success" silencioso nem uma excecao 500 sem corpo.
    try:
        ref = get_db().reference(MAINTENANCE_PATH)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao acessar o RTDB em {MAINTENANCE_PATH}: {e}",
        )

    # Estado anterior (para auditoria). Falha aqui NAO impede a operacao:
    # pode ser a primeira gravacao do no.
    try:
        previous = ref.get()
    except Exception:
        previous = None

    # Grava booleano real
    try:
        ref.set(enabled)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao gravar {MAINTENANCE_PATH}: {e}",
        )

    # 4. Le de volta para confirmar que o que ficou no RTDB e mesmo o pedido
    try:
        stored = ref.get()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Escrita ok, mas leitura de confirmacao falhou: {e}",
        )

    if not isinstance(stored, bool) or stored != enabled:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Confirmacao falhou: gravado={stored!r} "
                f"({type(stored).__name__}), esperado={enabled!r}"
            ),
        )

    # 5. Auditoria
    log_admin_action(actor_uid, "admin_maintenance", {
        "enabled": enabled,
        "previous": previous if isinstance(previous, bool) else None,
        "reason": reason,
        "path": MAINTENANCE_PATH,
    })

    return JSONResponse({
        "status": "success",
        "maintenance": enabled,
        "confirmed": stored,
        "actor_uid": actor_uid,
    })
