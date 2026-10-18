import time
import hmac
from datetime import datetime
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from app.services.firebase_service import get_db
from app.services.asaas_service import process_asaas_pix
from app.core.config import settings

router = APIRouter(prefix="/payments", tags=["payments"])


class _TransactionAbort(Exception):
    """Abort a Firebase transaction without returning None (which deletes data)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _claim_withdrawal(wd_ref, owner: str):
    def claim(current):
        if not isinstance(current, dict):
            raise _TransactionAbort("not_found")
        if current.get("processing_by") or current.get("status", "pending") != "pending":
            raise _TransactionAbort("already_processing")
        claimed = dict(current)
        claimed["status"] = "claiming"
        claimed["processing_by"] = owner
        claimed["claimed_at"] = datetime.now().isoformat()
        return claimed

    return wd_ref.transaction(claim)


def _release_claim(wd_ref, owner: str) -> None:
    def release(current):
        if not isinstance(current, dict):
            raise _TransactionAbort("not_found")
        if current.get("processing_by") != owner or current.get("status") != "claiming":
            raise _TransactionAbort("claim_changed")
        released = dict(current)
        released["status"] = "pending"
        released.pop("processing_by", None)
        released.pop("claimed_at", None)
        return released

    try:
        wd_ref.transaction(release)
    except _TransactionAbort:
        pass

@router.post("/approve/{wid}")
async def approve_payment(wid: str, request: Request):
    payment_accepted = False
    owner = getattr(request.state, "user_uid", "admin")
    try:
        db = get_db()
        wd_ref = db.reference(f"admin/pending_withdrawals/{wid}")
        try:
            claimed = _claim_withdrawal(wd_ref, owner)
        except _TransactionAbort as exc:
            message = "Saque não encontrado" if exc.reason == "not_found" else "Saque já está sendo processado"
            return {"status": "ignored", "message": message}

        result = await process_asaas_pix(
            claimed["amount"], claimed["pixKey"], claimed["pixType"],
            f"CineCash - Resgate {wid}", f"withdrawal-{wid}"
        )

        if "errors" in result:
            _release_claim(wd_ref, owner)
            return {"status": "error", "message": result["errors"][0]["description"]}

        uid = claimed["uid"]
        asaas_id = result.get("id")
        if not asaas_id:
            _release_claim(wd_ref, owner)
            return {"status": "error", "message": "Resposta de pagamento sem identificador"}
        payment_accepted = True
        update_data = {
            "status": "simulated" if result.get("simulated") else "processing",
            "sent_at": datetime.now().isoformat(),
            "asaas_id": asaas_id,
        }

        wd_ref.update(update_data)
        db.reference(f"withdrawals/{uid}/{wid}").update(update_data)
        db.reference(f"admin/asaas_mappings/{asaas_id}").set({"uid": uid, "wid": wid})
        wd_ref.delete()

        db.reference("logs/financial").push({
            "type": "withdrawal_paid", "wid": wid, "uid": uid,
            "amount": claimed["amount"], "timestamp": int(time.time() * 1000),
            "description": f"Saque de R${claimed['amount']} pago para {claimed.get('fullname')}"
        })

        mode = "simulado" if result.get("simulated") else "enviado"
        return {"status": "success", "message": f"Saque {mode} com sucesso", "payment_mode": mode}
    except Exception:
        if not payment_accepted and "wd_ref" in locals():
            _release_claim(wd_ref, owner)
        return {"status": "error", "message": "Falha segura ao processar saque"}

@router.post("/process-all")
async def process_all_payments(request: Request):
    db = get_db()
    pending = db.reference("admin/pending_withdrawals").get()
    if not pending:
        return {"status": "success", "message": "Nenhum saque pendente"}

    results = []
    for wid in pending.keys():
        res = await approve_payment(wid, request)
        results.append({"wid": wid, "result": res})

    return {"status": "success", "processed": len(results), "details": results}

@router.post("/auto-approve/{wid}")
async def auto_approve_withdrawal(wid: str, request: Request, data: dict = Body(...)):
    internal_token = request.headers.get("X-Internal-Token", "")
    expected_token = settings.N8N_SHARED_SECRET
    if not expected_token or not hmac.compare_digest(internal_token, expected_token):
        return JSONResponse(status_code=403, content={"status": "error", "message": "Token interno inválido"})

    payment_accepted = False
    owner = "n8n-auto"
    try:
        db = get_db()
        wd_ref = db.reference(f"admin/pending_withdrawals/{wid}")
        try:
            claimed = _claim_withdrawal(wd_ref, owner)
        except _TransactionAbort as exc:
            message = "Saque não encontrado" if exc.reason == "not_found" else "Saque já está sendo processado"
            return {"status": "ignored", "message": message}

        result = await process_asaas_pix(
            claimed["amount"],
            claimed["pixKey"],
            claimed["pixType"],
            f"CineCash - Resgate Auto {wid}",
            f"withdrawal-{wid}",
        )

        if "errors" in result:
            _release_claim(wd_ref, owner)
            return {"status": "error", "message": result["errors"][0]["description"]}

        uid = claimed["uid"]
        asaas_id = result.get("id")
        if not asaas_id:
            _release_claim(wd_ref, owner)
            return {"status": "error", "message": "Resposta de pagamento sem identificador"}
        payment_accepted = True
        update_data = {
            "status": "simulated" if result.get("simulated") else "processing",
            "sent_at": datetime.now().isoformat(),
            "asaas_id": asaas_id,
            "auto_approved": True,
            "approved_by": "n8n-auto"
        }

        wd_ref.update(update_data)
        db.reference(f"withdrawals/{uid}/{wid}").update(update_data)
        db.reference(f"admin/asaas_mappings/{asaas_id}").set({"uid": uid, "wid": wid})
        wd_ref.delete()

        db.reference("logs/financial").push({
            "type": "withdrawal_auto_approved",
            "wid": wid,
            "uid": uid,
            "amount": claimed["amount"],
            "timestamp": int(time.time() * 1000),
            "description": f"Saque de R${claimed['amount']} auto-aprovado via N8N para {claimed.get('fullname')}"
        })

        return {"status": "success", "message": "Saque auto-aprovado e processado!", "asaas_id": asaas_id}

    except Exception:
        if not payment_accepted and "wd_ref" in locals():
            _release_claim(wd_ref, owner)
        return {"status": "error", "message": "Erro ao processar auto-aprovação"}

@router.post("/webhook")
async def asaas_webhook(request: Request, data: dict = Body(...)):
    webhook_secret = settings.WEBHOOK_SECRET
    if not webhook_secret:
        return JSONResponse(status_code=503, content={"status": "error", "message": "Webhook não configurado"})
    token = request.headers.get("X-Webhook-Token", "")
    if not token or not hmac.compare_digest(token, webhook_secret):
        return JSONResponse(status_code=403, content={"status": "error", "message": "Webhook token inválido"})

    event = data.get("event")
    transfer = data.get("transfer")
    if not transfer or not event:
        return {"status": "ignored"}

    if event not in ("TRANSFER_PAID", "TRANSFER_FAILED", "TRANSFER_CANCELLED"):
        return JSONResponse(status_code=400, content={"status": "error", "message": "Evento não suportado"})

    asaas_id = transfer.get("id")
    if not asaas_id:
        return {"status": "ignored"}

    db = get_db()
    mapping = db.reference(f"admin/asaas_mappings/{asaas_id}").get()
    if not mapping:
        return {"status": "not_found"}

    uid = mapping.get("uid")
    wid = mapping.get("wid")
    if not uid or not wid:
        return {"status": "ignored"}

    withdraw_ref = db.reference(f"withdrawals/{uid}/{wid}")
    wd_data = withdraw_ref.get()
    if not wd_data:
        return {"status": "ignored"}

    if event == "TRANSFER_PAID":
        def mark_paid(current):
            if not isinstance(current, dict):
                raise _TransactionAbort("not_found")
            if current.get("status") in ("paid", "refunded", "refund_pending", "blocked_by_audit"):
                raise _TransactionAbort("terminal")
            paid = dict(current)
            paid.update({
                "status": "paid",
                "paid_at": datetime.now().isoformat(),
                "asaas_details": transfer,
            })
            return paid

        try:
            withdraw_ref.transaction(mark_paid)
        except _TransactionAbort:
            return {"status": "ignored"}
        except Exception:
            return {"status": "error", "message": "Confirmação não concluída"}
        db.reference("logs/financial").push({
            "type": "webhook_confirmed",
            "wid": wid,
            "uid": uid,
            "status": "paid",
            "timestamp": int(time.time() * 1000)
        })
        return {"status": "processed"}

    fail_reason = transfer.get("failReason") or "Cancelado pelo Asaas"
    amount_to_refund = float(wd_data.get("amount", 0) or 0)
    if amount_to_refund <= 0:
        return {"status": "ignored"}

    user_ref = db.reference(f"users/{uid}")
    if not user_ref.get():
        return {"status": "ignored"}

    # Estado intermediário idempotente. Exceções abortam sem gravar null.
    def claim_refund(current):
        if not isinstance(current, dict):
            raise _TransactionAbort("not_found")
        cd = dict(current)
        if cd.get("status") in ("refunded", "paid", "blocked_by_audit"):
            raise _TransactionAbort("terminal")
        cd["status"] = "refund_pending"
        cd["error_msg"] = fail_reason
        cd["failed_at"] = datetime.now().isoformat()
        return cd

    try:
        withdraw_ref.transaction(claim_refund)
    except _TransactionAbort:
        return {"status": "ignored"}
    except Exception:
        return {"status": "error", "message": "Estorno não iniciado"}

    def refund_balance(current):
        if not isinstance(current, dict):
            raise _TransactionAbort("user_not_found")
        cd = dict(current)
        refunds = dict(cd.get("withdrawal_refunds") or {})
        if wid in refunds:
            raise _TransactionAbort("already_refunded")
        cd["balance"] = float(cd.get("balance", 0)) + amount_to_refund
        refunds[wid] = {"amount": amount_to_refund, "timestamp": int(time.time() * 1000)}
        cd["withdrawal_refunds"] = refunds
        return cd
    try:
        user_ref.transaction(refund_balance)
    except _TransactionAbort as exc:
        if exc.reason != "already_refunded":
            return {"status": "error", "message": "Estorno não concluído"}
    except Exception:
        return {"status": "error", "message": "Estorno não concluído"}

    withdraw_ref.update({"status": "refunded", "refunded_at": datetime.now().isoformat()})

    db.reference("logs/financial").push({
        "type": "withdrawal_refunded",
        "wid": wid,
        "uid": uid,
        "amount": amount_to_refund,
        "timestamp": int(time.time() * 1000),
        "description": f"Estorno de R${amount_to_refund} para {wd_data.get('fullname')}"
    })

    return {"status": "processed"}
