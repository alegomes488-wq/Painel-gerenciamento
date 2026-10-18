"""
Routers de pagamentos â€” CineCash / CyberCore IA
CorreÃ§Ãµes aplicadas (Agosto/2026):
  â€¢ C2: Webhook Asaas fail-closed (503 sem segredo, 403 token invÃ¡lido)
  â€¢ M5: Lock anti-concorrÃªncia (claim atÃ´mico por transaÃ§Ã£o)
  â€¢ IdempotÃªncia: estorno dentro da transaÃ§Ã£o, estados terminais bloqueiam
"""
import os
import hmac
import hashlib
import json
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from firebase_admin import auth as firebase_auth, db
from typing import Optional

router = APIRouter(prefix="/payments", tags=["payments"])

# TAREFA 3.13: State machine de saques â€” valida transiÃ§Ãµes em toda mudanÃ§a de status.
#   pending -> [blocked_by_audit, processing]
#   processing -> [paid, failed]
#   blocked_by_audit -> [] (terminal)
#   paid -> [] (terminal)
#   failed -> [processing] (retry permitido)
VALID_TRANSITIONS = {
    "pending": {"blocked_by_audit", "processing", "paid", "refunding"},
    "processing": {"paid", "failed", "refunding"},
    "refunding": {"refunded", "processing"},
    "blocked_by_audit": set(),
    "paid": set(),
    "failed": {"processing"},
    "refunded": set(),
}


def _valid_transition(from_status: str, to_status: str) -> bool:
    """Retorna True se a transiÃ§Ã£o de estado Ã© permitida pela state machine."""
    allowed = VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
ASAAS_API_KEY = os.environ.get("ASAAS_API_KEY", "").strip()

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HELPERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def verify_webhook_token(request: Request) -> bool:
    """Valida o token HMAC do webhook Asaas."""
    if not WEBHOOK_SECRET:
        return False
    token = request.headers.get("X-Webhook-Token", "")
    if not token:
        return False
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        request.body or b"",
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, token)


def get_asaas_client():
    """Retorna client HTTP configurado para a API Asaas."""
    import httpx
    return httpx.Client(
        base_url="https://api.asaas.com/v3",
        headers={"access_token": ASAAS_API_KEY}
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# WEBHOOK ASAAS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/webhook")
async def asaas_webhook(request: Request):
    """
    Recebe webhooks do Asaas (TRANSFER_PAID, TRANSFER_FAILED, TRANSFER_CANCELLED).
    Fail-closed: 503 sem WEBHOOK_SECRET, 403 token invÃ¡lido.
    """
    # âœ… CORREÃ‡ÃƒO C2: Fail-closed â€” sem segredo configurado, rejeita imediatamente
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret nÃ£o configurado")

    body = await request.body()
    token = request.headers.get("X-Webhook-Token", "")
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Token de webhook invÃ¡lido")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload JSON invÃ¡lido")

    event = payload.get("event", "")
    payment_data = payload.get("payment", {})
    event_id = payment_data.get("id", "") or payload.get("id", "") or payload.get("eventId", "")

    # âœ… Allowlist de eventos â€” rejeita desconhecidos
    ALLOWED_EVENTS = {"TRANSFER_PAID", "TRANSFER_FAILED", "TRANSFER_CANCELLED"}
    if event not in ALLOWED_EVENTS:
        raise HTTPException(status_code=400, detail=f"Evento nÃ£o suportado: {event}")

    # âœ… TAREFA 2.6 (d): timestamp freshness â€” rejeita rejogos antigos (>5min de delay)
    # Asaas costuma enviar payment.dateCreated ou similar; usamos um fallback numÃ©rico
    # se disponÃ­vel. Se ausente, toleramos (nÃ£o quebra validade) mas ainda hÃ¡ dedup.
    occ = payment_data.get("dateCreated") or payment_data.get("paymentDate") or ""
    if occ:
        try:
            from datetime import datetime, timezone
            occ_dt = datetime.fromisoformat(occ.replace("Z", "+00:00")).timestamp()
            now_ts = datetime.now(timezone.utc).timestamp()
            delay = now_ts - occ_dt
            if delay > 300:  # > 5 minutos
                raise HTTPException(status_code=400, detail="Evento com timestamp antigo (replay?)")
        except ValueError:
            pass  # formato inesperado â€” nÃ£o bloqueia

    # âœ… TAREFA 2.6 (a/b/c): idempotÃªncia por event_id via transaÃ§Ã£o atÃ´mica em /webhook_events
    if event_id:
        dedup_ref = db.reference(f"webhook_events/{event_id}")

        def _dedup_transaction(current):
            if current is not None:
                return None  # jÃ¡ processado -> aborta transaction, nÃ£o reprocessa
            return {".sv": "timestamp"}

        try:
            dedup_result = dedup_ref.transaction(_dedup_transaction)
            if not dedup_result.committed:
                # Duplicata â€” idempotente: retorna 200 sem reprocessar
                return JSONResponse({"status": "duplicate_ignored", "event_id": event_id})
        except Exception:
            # Em falha do dedup, ainda processa (best-effort) para nÃ£o perder pagamento
            pass  # nosec

    # Extrai dados obrigatÃ³rios
    external_ref = payment_data.get("externalReference", "")
    if not external_ref:
        raise HTTPException(status_code=400, detail="externalReference ausente")

    # externalReference esperado: "wid_<withdrawal_id>"
    if not external_ref.startswith("wid_"):
        raise HTTPException(status_code=400, detail="externalReference invÃ¡lido")

    wid = external_ref.replace("wid_", "")
    amount = float(payment_data.get("value", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Valor invÃ¡lido")

    # â”€â”€ Processamento por evento â”€â”€
    if event == "TRANSFER_PAID":
        return await _handle_transfer_paid(wid, amount, payment_data)
    elif event in ("TRANSFER_FAILED", "TRANSFER_CANCELLED"):
        return await _handle_transfer_failed(wid, amount, payment_data)

    return JSONResponse({"status": "ignored"})


async def _handle_transfer_paid(wid: str, amount: float, payment_data: dict):
    """
    Marca o saque como pago. Idempotente â€” se jÃ¡ estiver pago, ignora.
    """
    ref = db.reference(f"admin/pending_withdrawals/{wid}")
    snapshot = ref.get()

    if not snapshot:
        return JSONResponse({"status": "withdrawal_not_found"})

    current_status = snapshot.get("status", "")

    # Estados terminais â€” nÃ£o processa novamente
    if current_status in ("paid", "refunded", "blocked_by_audit"):
        return JSONResponse({"status": "already_terminal", "current_status": current_status})

    # TAREFA 3.13: valida transiÃ§Ã£o via state machine (pending/processing -> paid)
    if not _valid_transition(current_status, "paid"):
        return JSONResponse({"status": "invalid_transition", "current_status": current_status})

    if current_status in ("pending", "processing", "refunding"):
        ref.update({
            "status": "paid",
            "paid_at": {".sv": "timestamp"},
            "asaas_transfer_id": payment_data.get("id", ""),
            "paid_amount": amount
        })
        # Log financeiro
        db.reference("logs/financial").push({
            "type": "withdrawal_paid",
            "wid": wid,
            "amount": amount,
            "timestamp": {".sv": "timestamp"}
        })

    return JSONResponse({"status": "paid", "wid": wid})


async def _handle_transfer_failed(wid: str, amount: float, payment_data: dict):
    """
    Estorna o saldo do usuÃ¡rio quando o saque falha.
    Idempotente via transaÃ§Ã£o â€” estorno duplo Ã© impossÃ­vel.
    """
    ref = db.reference(f"admin/pending_withdrawals/{wid}")
    user_uid = ref.child("uid").get()

    if not user_uid:
        return JSONResponse({"status": "withdrawal_not_found"})

    # âœ… CORREÃ‡ÃƒO M5: Lock + idempotÃªncia via transaÃ§Ã£o
    # TAREFA 3.13: valida transiÃ§Ã£o imediata (pending/processing -> refunding)
    def _refund_transaction(current_data):
        if current_data is None:
            return None  # aborta

        # Se jÃ¡ foi estornado ou estÃ¡ em estado terminal, aborta (nÃ£o re-estorna)
        if not _valid_transition(current_data.get("status"), "refunding"):
            return None

        # Se jÃ¡ tem lock de processamento, aborta (outro webhook/processando)
        if current_data.get("processing_by"):
            return None

        # Marca como processando (lock)
        current_data["processing_by"] = "webhook-asaas"
        current_data["status"] = "refunding"
        return current_data

    try:
        result = ref.transaction(_refund_transaction)
        if not result.committed:
            return JSONResponse({"status": "already_processed_or_locked"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na transaÃ§Ã£o: {str(e)}")

    # Agora que temos o lock, executa o estorno
    try:
        user_balance_ref = db.reference(f"users/{user_uid}/balance")
        current_balance = user_balance_ref.get() or 0
        user_balance_ref.set(current_balance + amount)

        # Marca como estornado e libera o lock
        ref.update({
            "status": "refunded",
            "refunded_at": {".sv": "timestamp"},
            "refund_amount": amount,
            "processing_by": None  # libera lock
        })

        # Log
        db.reference("logs/financial").push({
            "type": "withdrawal_refunded",
            "wid": wid,
            "uid": user_uid,
            "amount": amount,
            "timestamp": {".sv": "timestamp"}
        })

        return JSONResponse({"status": "refunded", "wid": wid, "amount": amount})

    except Exception as e:
        # Em erro, libera o lock para permitir retry
        ref.update({"processing_by": None})
        raise HTTPException(status_code=500, detail=f"Erro no estorno: {str(e)}")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# APROVAÃ‡ÃƒO MANUAL / AUTO-APROVAÃ‡ÃƒO
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/auto-approve/{wid}")
async def auto_approve_withdrawal(wid: str, request: Request):
    """
    Aprova um saque manualmente ou via N8N.
    Lock anti-concorrÃªncia: claim atÃ´mico por transaÃ§Ã£o.

    TAREFA 2.4: N8N agora Ã© validado PRIMEIRO via header X-N8N-Secret (timing-safe),
    sem precisar de Firebase ID token. SÃ³ cai no fluxo Firebase se NÃƒO for N8N.
    """
    import hmac as _hmac
    import hashlib as _hashlib

    # â”€â”€ 1. Tenta fluxo N8N (X-N8N-Secret) primeiro â”€â”€
    n8n_secret = os.environ.get("N8N_SHARED_SECRET", "").strip()
    provided_n8n = request.headers.get("X-N8N-Secret", "")
    is_n8n = bool(n8n_secret) and _hmac.compare_digest(n8n_secret.encode(), (provided_n8n or "").encode())

    actor = "n8n-auto"

    if not is_n8n:
        # â”€â”€ 2. SenÃ£o, exige Firebase ID token de admin â”€â”€
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Token nÃ£o fornecido")

        token = auth_header.split(" ", 1)[1]
        try:
            decoded = firebase_auth.verify_id_token(token, check_revoked=True)
            # TAREFA 2.3: admin por claim OU allowlist (via dependencies)
            from app.dependencies import is_admin_user
            if not is_admin_user(decoded.get("uid", ""), decoded):
                raise HTTPException(status_code=403, detail="Acesso negado")
            actor = decoded.get("uid", "admin")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Token invÃ¡lido")

    ref = db.reference(f"admin/pending_withdrawals/{wid}")

    # âœ… CORREÃ‡ÃƒO M5: Claim atÃ´mico por transaÃ§Ã£o
    # TAREFA 3.13: valida transiÃ§Ã£o via state machine (pending -> processing)
    def _approve_transaction(current_data):
        if current_data is None:
            return None
        current_status = current_data.get("status")
        # TransiÃ§Ã£o invÃ¡lida -> aborta (deixa como estÃ¡)
        if not _valid_transition(current_status, "processing"):
            return current_data  # jÃ¡ processado / terminal
        if current_data.get("processing_by"):
            return current_data  # jÃ¡ em processamento
        current_data["processing_by"] = actor
        current_data["status"] = "processing"
        return current_data

    try:
        result = ref.transaction(_approve_transaction)
        if not result.committed:
            current = ref.get()
            if current and current.get("processing_by"):
                raise HTTPException(status_code=409, detail="Saque jÃ¡ em processamento")
            raise HTTPException(status_code=400, detail="Saque nÃ£o estÃ¡ pendente")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na transaÃ§Ã£o: {str(e)}")

    # Executa transferÃªncia no Asaas
    try:
        snap = ref.get()
        uid = snap.get("uid")
        amount = float(snap.get("amount", 0))
        pix_key = snap.get("pixKey", "")
        pix_type = snap.get("pixType", "")

        # TAREFA 3.3: MODO SIMULAÃ‡ÃƒO explÃ­cito.
        # Se SIMULATION_MODE=true (padrÃ£o), NUNCA chama a API real do Asaas.
        # Se SIMULATION_MODE=false, chama process_asaas_pix (PIX real).
        from app.core.config import settings as _settings
        if _settings.SIMULATION_MODE or not _settings.ASAAS_API_KEY:
            # SimulaÃ§Ã£o â€” gera ID prefixado com SIM_
            transfer_id = f"SIM_{wid}_{int(os.urandom(4).hex(), 16)}"
        else:
            from app.services.asaas_service import process_asaas_pix
            asaas_resp = await process_asaas_pix(
                amount=amount,
                pix_key=pix_key,
                pix_type=pix_type,
                description=f"Saque {wid} â€” painel admin",
                external_ref=f"wid_{wid}",
            )
            if asaas_resp and asaas_resp.get("errors"):
                # Falha no PIX real: libera lock e mantÃ©m pendente (NUNCA marca paid)
                ref.update({"processing_by": None})
                raise HTTPException(status_code=502, detail=asaas_resp["errors"][0].get("description", "Erro no Asaas"))
            transfer_id = asaas_resp.get("id", f"T{int(os.urandom(4).hex(), 16)}")

        # Atualiza como pago
        ref.update({
            "status": "paid",
            "paid_at": {".sv": "timestamp"},
            "asaas_transfer_id": transfer_id,
            "processing_by": None,
            "simulation": bool(_settings.SIMULATION_MODE or not _settings.ASAAS_API_KEY),
        })

        # TAREFA 3.6: log de auditoria da aprovaÃ§Ã£o (JSON estruturado)
        try:
            from app.dependencies import log_admin_action
            log_admin_action(actor, "withdrawal_approved", {
                "wid": wid,
                "target_uid": uid,
                "amount": amount,
                "transfer_id": transfer_id,
                "simulation": bool(_settings.SIMULATION_MODE or not _settings.ASAAS_API_KEY),
            })
        except Exception:
            pass  # nosec

        return JSONResponse({
            "status": "approved",
            "wid": wid,
            "transfer_id": transfer_id
        })

    except Exception as e:
        # Libera lock em erro
        ref.update({"processing_by": None})
        raise HTTPException(status_code=500, detail=f"Erro na transferÃªncia: {str(e)}")


@router.post("/approve/{wid}")
async def approve_payment(wid: str, request: Request):
    """Alias para auto_approve_withdrawal (compatibilidade)."""
    return await auto_approve_withdrawal(wid, request)
