import time
import hmac
from datetime import datetime
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from app.services.firebase_service import get_db
from app.services.asaas_service import process_asaas_pix
from app.core.config import settings

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/approve/{wid}")
async def approve_payment(wid: str, request: Request):
    try:
        db = get_db()
        wd_ref = db.reference(f"admin/pending_withdrawals/{wid}")
        wd = wd_ref.get()
        if not wd:
            return {"status": "error", "message": "Saque não encontrado na fila pendente"}

        # Claim atômico anti-concorrência: a checagem de estado acontece DENTRO da
        # transação no nó da fila, garantindo que só um admin pague o mesmo saque.
        user_uid = getattr(request.state, "user_uid", "admin")
        def claim(current):
            if not current:
                return None  # nó removido concorrentemente
            cd = dict(current)
            if cd.get("processing_by") or cd.get("status") != "pending":
                return None  # aborta: já lockado/processado (idempotente)
            cd["processing_by"] = user_uid
            return cd
        claimed = wd_ref.transaction(claim)
        if claimed is None:
            return {"status": "error", "message": "Saque já está sendo processado"}

        result = await process_asaas_pix(
            claimed["amount"], claimed["pixKey"], claimed["pixType"],
            f"CineCash - Resgate {wid}"
        )

        if "errors" in result:
            db.reference(f"admin/pending_withdrawals/{wid}/processing_by").delete()
            return {"status": "error", "message": result["errors"][0]["description"]}

        uid = claimed["uid"]
        asaas_id = result.get("id")
        update_data = {"status": "processing", "sent_at": datetime.now().isoformat(), "asaas_id": asaas_id}

        db.reference(f"withdrawals/{uid}/{wid}").update(update_data)
        db.reference(f"admin/asaas_mappings/{asaas_id}").set({"uid": uid, "wid": wid})
        wd_ref.delete()

        db.reference("logs/financial").push({
            "type": "withdrawal_paid", "wid": wid, "uid": uid,
            "amount": claimed["amount"], "timestamp": int(time.time() * 1000),
            "description": f"Saque de R${claimed['amount']} pago para {claimed.get('fullname')}"
        })

        return {"status": "success", "message": "Saque pago com sucesso via Asaas!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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

    try:
        db = get_db()
        wd_ref = db.reference(f"admin/pending_withdrawals/{wid}")
        wd = wd_ref.get()
        if not wd:
            return {"status": "error", "message": "Saque não encontrado na fila pendente"}

        # Claim atômico anti-concorrência (dono = n8n-auto): evita que o N8N e um
        # admin (ou dois webhooks N8N) paguem o mesmo saque em paralelo.
        def claim(current):
            if not current:
                return None
            cd = dict(current)
            if cd.get("processing_by") or cd.get("status") != "pending":
                return None  # aborta: já lockado/processado (idempotente)
            cd["processing_by"] = "n8n-auto"
            return cd
        claimed = wd_ref.transaction(claim)
        if claimed is None:
            return {"status": "error", "message": "Saque já está sendo processado"}

        result = await process_asaas_pix(
            claimed["amount"],
            claimed["pixKey"],
            claimed["pixType"],
            f"CineCash - Resgate Auto {wid}"
        )

        if "errors" in result:
            db.reference(f"admin/pending_withdrawals/{wid}/processing_by").delete()
            return {"status": "error", "message": result["errors"][0]["description"]}

        uid = claimed["uid"]
        asaas_id = result.get("id")
        update_data = {
            "status": "processing",
            "sent_at": datetime.now().isoformat(),
            "asaas_id": asaas_id,
            "auto_approved": True,
            "approved_by": "n8n-auto"
        }

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

    except Exception as e:
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
        if wd_data.get("status") in ("paid", "refunded", "blocked_by_audit"):
            return {"status": "ignored"}
        withdraw_ref.update({
            "status": "paid",
            "paid_at": datetime.now().isoformat(),
            "asaas_details": transfer
        })
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

    # Claim atômico: a checagem de estado acontece DENTRO da transação,
    # garantindo idempotência mesmo com webhooks duplicados/concorrentes.
    def claim_refund(current):
        if not current:
            return current
        cd = dict(current)
        if cd.get("status") in ("refunded", "paid", "blocked_by_audit"):
            return None  # aborta a transação: já estornado (idempotente)
        cd["status"] = "refunded"
        cd["error_msg"] = fail_reason
        cd["failed_at"] = datetime.now().isoformat()
        return cd

    try:
        claim_result = withdraw_ref.transaction(claim_refund)
    except Exception:
        claim_result = None

    if claim_result is None:
        # Já estornado anteriormente ou nó inexistente — nada a fazer
        return {"status": "ignored"}

    def refund_balance(current):
        if not current:
            return current
        cd = dict(current)
        cd["balance"] = float(cd.get("balance", 0)) + amount_to_refund
        return cd
    user_ref.transaction(refund_balance)

    db.reference("logs/financial").push({
        "type": "withdrawal_refunded",
        "wid": wid,
        "uid": uid,
        "amount": amount_to_refund,
        "timestamp": int(time.time() * 1000),
        "description": f"Estorno de R${amount_to_refund} para {wd_data.get('fullname')}"
    })

    return {"status": "processed"}
