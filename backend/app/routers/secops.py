from fastapi import APIRouter, Request, HTTPException
from app.services.secops_agent import SecOpsSentinelAgent
from app.services.firebase_service import get_db

router = APIRouter(prefix="/api/secops", tags=["secops"])

@router.get("/health-audit")
async def get_health_audit(request: Request):
    """
    Executa o checkup completo de cibersegurança e saúde da infraestrutura.
    """
    return SecOpsSentinelAgent.audit_system_security()

@router.get("/risk-analysis/{wid}")
async def get_risk_analysis(wid: str, request: Request):
    """
    Realiza a análise profunda de risco para um saque pendente específico.
    """
    try:
        db = get_db()
        wd_data = db.reference(f"admin/pending_withdrawals/{wid}").get()
        if not wd_data:
            # Fallback para o histórico de saques do usuário se já tiver sido movido
            wd_data = db.reference(f"withdrawals").get() or {}
            # Busca recursiva se necessário
            found_wd = None
            for uid, user_wds in wd_data.items():
                if isinstance(user_wds, dict) and wid in user_wds:
                    found_wd = user_wds[wid]
                    break
            wd_data = found_wd

        if not wd_data:
            raise HTTPException(status_code=404, detail="Saque não encontrado para análise")

        analysis = SecOpsSentinelAgent.evaluate_withdrawal_risk(wid, wd_data)
        return {"status": "success", "analysis": analysis}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao analisar risco: {str(e)}")

@router.get("/summary")
async def get_secops_summary(request: Request):
    """
    Retorna a síntese do estado de risco de todos os saques pendentes na fila.
    """
    try:
        db = get_db()
        pending = db.reference("admin/pending_withdrawals").get() or {}
        
        total_pending = len(pending)
        low_risk = 0
        medium_risk = 0
        high_risk = 0
        critical_risk = 0
        analyzed_list = []

        for wid, wd_data in pending.items():
            if isinstance(wd_data, dict):
                analysis = SecOpsSentinelAgent.evaluate_withdrawal_risk(wid, wd_data)
                level = analysis.get("risk_level", "LOW")
                if level == "LOW":
                    low_risk += 1
                elif level == "MEDIUM":
                    medium_risk += 1
                elif level == "HIGH":
                    high_risk += 1
                else:
                    critical_risk += 1
                
                analyzed_list.append({
                    "wid": wid,
                    "fullname": analysis.get("fullname"),
                    "amount": analysis.get("amount"),
                    "trust_score": analysis.get("trust_score"),
                    "risk_level": level,
                    "recommendation": analysis.get("recommendation")
                })

        audit_summary = SecOpsSentinelAgent.audit_system_security()

        return {
            "status": "success",
            "agent": "SecOps Sentinel AI v1.0",
            "total_pending": total_pending,
            "risk_counts": {
                "low": low_risk,
                "medium": medium_risk,
                "high": high_risk,
                "critical": critical_risk
            },
            "system_secure": audit_summary.get("system_secure", True),
            "pending_items": analyzed_list
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar resumo SecOps: {str(e)}")
