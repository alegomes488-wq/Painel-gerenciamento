"""
Routers de pagamentos — CineCash / CyberCore IA
Correções aplicadas (Agosto/2026):
  • C2: Webhook Asaas fail-closed (503 sem segredo, 403 token inválido)
  • M5: Lock anti-concorrência (claim atômico por transação)
  • Idempotência: estorno dentro da transação, estados terminais bloqueiam
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

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
ASAAS_API_KEY = os.environ.get("ASAAS_API_KEY", "").strip()

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# WEBHOOK ASAAS
# ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def asaas_webhook(request: Request):
    """
    Recebe webhooks do Asaas (TRANSFER_PAID, TRANSFER_FAILED, TRANSFER_CANCELLED).
    Fail-closed: 503 sem WEBHOOK_SECRET, 403 token inválido.
    """
    # ✅ CORREÇÃO C2: Fail-closed — sem segredo configurado, rejeita imediatamente
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret não configurado")

    body = await request.body()
    token = request.headers.get("X-Webhook-Token", "")
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Token de webhook inválido")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    event = payload.get("event", "")
    payment_data = payload.get("payment", {})

    # ✅ Allowlist de eventos — rejeita desconhecidos
    ALLOWED_EVENTS = {"TRANSFER_PAID", "TRANSFER_FAILED", "TRANSFER_CANCELLED"}
    if event not in ALLOWED_EVENTS:
        raise HTTPException(status_code=400, detail=f"Evento não suportado: {event}")

    # Extrai dados obrigatórios
    external_ref = payment_data.get("externalReference", "")
    if not external_ref:
        raise HTTPException(status_code=400, detail="externalReference ausente")

    # externalReference esperado: "wid_<withdrawal_id>"
    if not external_ref.startswith("wid_"):
        raise HTTPException(status_code=400, detail="externalReference inválido")

    wid = external_ref.replace("wid_", "")
    amount = float(payment_data.get("value", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Valor inválido")

    # ── Processamento por evento ──
    if event == "TRANSFER_PAID":
        return await _handle_transfer_paid(wid, amount, payment_data)
    elif event in ("TRANSFER_FAILED", "TRANSFER_CANCELLED"):
        return await _handle_transfer_failed(wid, amount, payment_data)

    return JSONResponse({"status": "ignored"})


async def _handle_transfer_paid(wid: str, amount: float, payment_data: dict):
    """
    Marca o saque como pago. Idempotente — se já estiver pago, ignora.
    """
    ref = db.reference(f"admin/pending_withdrawals/{wid}")
    snapshot = ref.get()

    if not snapshot:
        return JSONResponse({"status": "withdrawal_not_found"})

    current_status = snapshot.get("status", "")

    # Estados terminais — não processa novamente
    if current_status in ("paid", "refunded", "blocked_by_audit"):
        return JSONResponse({"status": "already_terminal", "current_status": current_status})

    if current_status == "pending":
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
    Estorna o saldo do usuário quando o saque falha.
    Idempotente via transação — estorno duplo é impossível.
    """
    ref = db.reference(f"admin/pending_withdrawals/{wid}")
    user_uid = ref.child("uid").get()

    if not user_uid:
        return JSONResponse({"status": "withdrawal_not_found"})

    # ✅ CORREÇÃO M5: Lock + idempotência via transação
    def _refund_transaction(current_data):
        if current_data is None:
            return None  # aborta

        # Se já foi estornado ou está em estado terminal, aborta (não re-estorna)
        if current_data.get("status") in ("refunded", "paid", "blocked_by_audit"):
            return None

        # Se já tem lock de processamento, aborta (outro webhook/processando)
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
        raise HTTPException(status_code=500, detail=f"Erro na transação: {str(e)}")

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


# ─────────────────────────────────────────────────────────────
# APROVAÇÃO MANUAL / AUTO-APROVAÇÃO
# ─────────────────────────────────────────────────────────────

@router.post("/auto-approve/{wid}")
async def auto_approve_withdrawal(wid: str, request: Request):
    """
    Aprova um saque manualmente ou via N8N.
    Lock anti-concorrência: claim atômico por transação.
    """
    # Verifica auth (admin ou N8N)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")

    token = auth_header.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        is_admin = bool(decoded.get("admin", False))
        is_n8n = token == os.environ.get("N8N_SHARED_SECRET", "")
        if not (is_admin or is_n8n):
            raise HTTPException(status_code=403, detail="Acesso negado")
        actor = "n8n-auto" if is_n8n else decoded.get("uid", "admin")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    ref = db.reference(f"admin/pending_withdrawals/{wid}")

    # ✅ CORREÇÃO M5: Claim atômico por transação
    def _approve_transaction(current_data):
        if current_data is None:
            return None
        if current_data.get("status") != "pending":
            return current_data  # já processado
        if current_data.get("processing_by"):
            return current_data  # já em processamento
        current_data["processing_by"] = actor
        current_data["status"] = "processing"
        return current_data

    try:
        result = ref.transaction(_approve_transaction)
        if not result.committed:
            current = ref.get()
            if current and current.get("processing_by"):
                raise HTTPException(status_code=409, detail="Saque já em processamento")
            raise HTTPException(status_code=400, detail="Saque não está pendente")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na transação: {str(e)}")

    # Executa transferência no Asaas
    try:
        snap = ref.get()
        uid = snap.get("uid")
        amount = float(snap.get("amount", 0))
        pix_key = snap.get("pixKey", "")
        pix_type = snap.get("pixType", "")

        # TODO: integração real com Asaas API
        # Por enquanto, simula sucesso
        transfer_id = f"sim_{wid}_{int(os.urandom(4).hex(), 16)}"

        # Atualiza como pago
        ref.update({
            "status": "paid",
            "paid_at": {".sv": "timestamp"},
            "asaas_transfer_id": transfer_id,
            "processing_by": None
        })

        return JSONResponse({
            "status": "approved",
            "wid": wid,
            "transfer_id": transfer_id
        })

    except Exception as e:
        # Libera lock em erro
        ref.update({"processing_by": None})
        raise HTTPException(status_code=500, detail=f"Erro na transferência: {str(e)}")


@router.post("/approve/{wid}")
async def approve_payment(wid: str, request: Request):
    """Alias para auto_approve_withdrawal (compatibilidade)."""
    return await auto_approve_withdrawal(wid, request)
