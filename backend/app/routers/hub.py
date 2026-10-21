"""
Painel HUB — rotas de operação (Desempenho / Acompanhamento / Segurança).

Todas as rotas de leitura exigem admin (middleware de main.py). A única rota
pública é POST /api/hub/events (ingestão de agentes), autenticada por
HMAC X-Hub-Agent-Secret e isenta no middleware — mesmo padrão de
/api/monitor/report.
"""
import hashlib
import hmac
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.dependencies import log_admin_action, require_admin
from app.services import hub_service

router = APIRouter(prefix="/api/hub", tags=["hub"])

VALID_ACTION_TYPES = (
    "quarantine_ip", "release_ip", "revoke_access", "block_rollout", "unblock_rollout",
)

# Token web (navegador do site/app) só pode enviar telemetria de observação —
# nunca eventos de segurança ou contexto de outros usuários (anti-spoofing:
# qualquer cliente poderia forjar contexto de terceiros com um token estático).
WEB_INGEST_SECTIONS = ("web",)


def _admin(request: Request) -> dict:
    """Valida admin com mensagens HTTP amigáveis."""
    try:
        return require_admin(request)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _verify_ingest_secret(request: Request) -> str:
    """
    Autenticação do canal de ingestão (agentes sem token Firebase).
    Retorna o escopo: "full" (agente com HUB_AGENT_SECRET, todas as seções)
    ou "web" (HUB_WEB_TOKEN do navegador, apenas WEB_INGEST_SECTIONS).
    """
    agent_secret = (settings.HUB_AGENT_SECRET or os.environ.get("HUB_AGENT_SECRET") or "").strip()
    web_token = (settings.HUB_WEB_TOKEN or os.environ.get("HUB_WEB_TOKEN") or "").strip()
    provided = request.headers.get("X-Hub-Agent-Secret", "")

    if not agent_secret and not web_token:
        raise HTTPException(status_code=503, detail="Canal de ingestão HUB não configurado (HUB_AGENT_SECRET)")

    if agent_secret and provided:
        expected = hmac.new(agent_secret.encode("utf-8"), b"hub-ingest", hashlib.sha256).hexdigest()
        if hmac.compare_digest(provided, expected):
            return "full"
    if web_token and provided and hmac.compare_digest(provided, web_token):
        return "web"
    raise HTTPException(status_code=403, detail="Segredo do agente HUB inválido")


# ─────────────────────────────────────────────────────────────
# INGESTÃO (pública + HMAC) — declarada ANTES das rotas com {pillar}
# ─────────────────────────────────────────────────────────────

@router.post("/events")
async def hub_ingest_event(request: Request):
    """
    Recebe métricas/eventos dos agentes do site, PWA/iOS, APK e back-end.
    Body: { "section": "web|app|api|sessions|funnels|tickets|apk|network|auth|vulnerabilities",
            "data": {...}, "source": "cinecash-web" }
    Após gravar, roda o correlator da Cyber Core IA e aplica ações autônomas
    críticas (quarentena de IP) quando aplicável.
    """
    scope = _verify_ingest_secret(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    section = payload.get("section", "")
    data = payload.get("data")
    source = payload.get("source", "agent")

    if not isinstance(section, str) or not section:
        raise HTTPException(status_code=400, detail="Campo 'section' ausente")
    if scope == "web" and section not in WEB_INGEST_SECTIONS:
        raise HTTPException(
            status_code=403,
            detail=f"Token web restrito às seções: {', '.join(WEB_INGEST_SECTIONS)}",
        )

    try:
        result = hub_service.ingest_and_correlate(section, data, source=str(source))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse({
        "status": "ok",
        "section": section,
        "stored": result["stored"],
        "correlations": result["correlations"],
        "autonomous_actions": result["autonomous_actions"],
    })


# ─────────────────────────────────────────────────────────────
# LEITURA (admin)
# ─────────────────────────────────────────────────────────────

@router.get("/overview")
async def hub_overview(request: Request):
    """Visão consolidada dos 3 pilares + correlações + score de saúde."""
    _admin(request)
    return hub_service.build_overview()


@router.get("/correlations")
async def hub_correlations(request: Request, limit: int = 20):
    """Correlações recentes detectadas pela Cyber Core IA."""
    _admin(request)
    items = hub_service.list_correlations(limit)
    return JSONResponse({"status": "success", "total": len(items), "correlations": items})


@router.get("/actions")
async def hub_actions(request: Request, limit: int = 30):
    """Log de ações (autônomas e manuais) executadas no HUB."""
    _admin(request)
    items = hub_service.list_actions(limit)
    return JSONResponse({"status": "success", "actions": items})


@router.post("/actions")
async def hub_execute_action(request: Request):
    """
    Executa uma ação de segurança sob demanda do operador.
    Body: { "type": "quarantine_ip|release_ip|revoke_access", "params": {...}, "reason": "" }
    """
    viewer = _admin(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    action_type = payload.get("type", "")
    params = payload.get("params") or {}
    reason = payload.get("reason", "")
    if action_type not in VALID_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo de ação inválido. Use: {', '.join(VALID_ACTION_TYPES)}")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="'params' deve ser um objeto")

    try:
        result = hub_service.apply_autonomous_action(
            action_type, params, actor=viewer.get("uid", "admin"), reason=str(reason)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_admin_action(viewer.get("uid", "?"), f"hub_action_{action_type}", {"params": params, "result": result.get("status")})
    return JSONResponse({"status": "success", "result": result})


# ─────────────────────────────────────────────────────────────
# COPILOT DO AGENTE DE SUPORTE (admin) — ANTES do catch-all /{pillar}
# ─────────────────────────────────────────────────────────────

@router.get("/copilot")
async def hub_copilot(request: Request, query: str = ""):
    """
    Brief contextual de um usuário para o atendimento de suporte.
    Aceita uid ou e-mail em ?query=. Combina cadastro, contexto de
    dispositivo/rede, bloqueios, saques pendentes e flags de risco.
    """
    _admin(request)
    if not query.strip():
        raise HTTPException(status_code=400, detail="Informe ?query=<uid ou e-mail>")
    try:
        brief = hub_service.build_agent_brief(query)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return JSONResponse(brief)


# ─────────────────────────────────────────────────────────────
# CANAL DE AGENTES (HMAC) — consultas dos apps sem token Firebase
# ─────────────────────────────────────────────────────────────

@router.get("/agent/rollout/{app_version}")
async def hub_agent_rollout_status(app_version: str, request: Request):
    """
    Consulta de bloqueio de rollout para o app (antes de atualizar/promover
    uma versão do APK). Autenticado pelo mesmo HMAC dos agentes.
    """
    _verify_ingest_secret(request)
    return JSONResponse(hub_service.is_rollout_blocked(app_version))


@router.get("/{pillar}")
async def hub_pillar(pillar: str, request: Request):
    """Dados consolidados de um pilar: performance | tracking | security."""
    _admin(request)
    try:
        data = hub_service.read_pillar(pillar)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return JSONResponse({"status": "success", "pillar": pillar, "data": data})
