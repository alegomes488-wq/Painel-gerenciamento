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

        result = await process_asaas_pix(
            wd["amount"], wd["pixKey"], wd["pixType"],
            f"CineCash - Resgate {wid}"
        )

        if "errors" in result:
            return {"status": "error", "message": result["errors"][0]["description"]}

        uid = wd["uid"]
        asaas_id = result.get("id")
        update_data = {"status": "processing", "sent_at": datetime.now().isoformat(), "asaas_id": asaas_id}

        db.reference(f"withdrawals/{uid}/{wid}").update(update_data)
        db.reference(f"admin/asaas_mappings/{asaas_id}").set({"uid": uid, "wid": wid})
        wd_ref.delete()

        db.reference("logs/financial").push({
            "type": "withdrawal_paid", "wid": wid, "uid": uid,
            "amount": wd["amount"], "timestamp": int(time.time() * 1000),
            "description": f"Saque de R${wd['amount']} pago para {wd.get('fullname')}"
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

        if wd.get("processing_by"):
            return {"status": "error", "message": "Saque já está sendo processado"}

        result = await process_asaas_pix(
            wd["amount"],
            wd["pixKey"],
            wd["pixType"],
            f"CineCash - Resgate Auto {wid}"
        )

        if "errors" in result:
            return {"status": "error", "message": result["errors"][0]["description"]}

        uid = wd["uid"]
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
            "amount": wd["amount"],
            "timestamp": int(time.time() * 1000),
            "description": f"Saque de R${wd['amount']} auto-aprovado via N8N para {wd.get('fullname')}"
        })

        return {"status": "success", "message": "Saque auto-aprovado e processado!", "asaas_id": asaas_id}

    except Exception as e:
        return {"status": "error", "message": "Erro ao processar auto-aprovação"}

@router.post("/webhook")
async def asaas_webhook(request: Request, data: dict = Body(...)):
    webhook_secret = settings.WEBHOOK_SECRET
    if webhook_secret:
        token = request.headers.get("X-Webhook-Token", "")
        if not hmac.compare_digest(token, webhook_secret):
            return {"status": "forbidden"}

    event = data.get("event")
    transfer = data.get("transfer")
    if not transfer or not event:
        return {"status": "ignored"}

    db = get_db()
    asaas_id = transfer.get("id")
    mapping = db.reference(f"admin/asaas_mappings/{asaas_id}").get()

    if not mapping:
        return {"status": "not_found"}

    uid = mapping.get("uid")
    wid = mapping.get("wid")

    if event == "TRANSFER_PAID":
        db.reference(f"withdrawals/{uid}/{wid}").update({
            "status": "paid",
            "paid_at": datetime.now().isoformat(),
            "asaas_details": transfer
        })
    elif event in ["TRANSFER_FAILED", "TRANSFER_CANCELLED"]:
        fail_reason = transfer.get("failReason") or "Cancelado pelo Asaas"
        withdraw_ref = db.reference(f"withdrawals/{uid}/{wid}")
        wd_data = withdraw_ref.get()

        if wd_data and wd_data.get("status") != "refunded":
            amount_to_refund = float(wd_data.get("amount", 0))
            def refund_trans(current):
                if not current: return current
                cd = current if isinstance(current, dict) else {}
                cd["balance"] = float(cd.get("balance", 0)) + amount_to_refund
                return cd
            db.reference(f"users/{uid}").transaction(refund_trans)
            withdraw_ref.update({
                "status": "refunded",
                "error_msg": fail_reason,
                "failed_at": datetime.now().isoformat()
            })

    return {"status": "processed"}
