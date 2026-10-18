"""
Routers de projetos/monitoramento — CineCash / CyberCore IA
Correções aplicadas (Agosto/2026):
  • A1: /api/monitor/report público mas com validação e saneamento
  • agent-script exige Bearer admin
  • Sanitização de strings (entidades HTML)
  • Clamping de números (cpu/ram/disk 0-100, load 0-10000)
"""
import os
import re
import html
import time
import secrets
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from firebase_admin import auth as firebase_auth, db
from typing import Optional

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

# ─────────────────────────────────────────────────────────────
# HELPERS DE SANITIZAÇÃO
# ─────────────────────────────────────────────────────────────

def sanitize_string(value: str, max_length: int = 200) -> str:
    """Sanitiza string: escapa HTML, trunca, remove null bytes."""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "")
    value = html.escape(value, quote=True)
    return value[:max_length]


def clamp_number(value, min_val: float, max_val: float) -> float:
    """Limita um número a um intervalo seguro."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return min_val
    return max(min(num, max_val), min_val)


# ─────────────────────────────────────────────────────────────
# REPORT PÚBLICO (agente remoto sem token)
# ─────────────────────────────────────────────────────────────

@router.post("/report")
async def monitor_report(request: Request):
    """
    Recebe heartbeat de agentes remotos.
    Público por design (agente não tem token), mas com validação rigorosa.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    project_id = payload.get("projectId", "")
    if not project_id or not re.match(r"^[a-zA-Z0-9_-]{1,64}$", project_id):
        raise HTTPException(status_code=400, detail="projectId inválido ou ausente")

    # Verifica se o projeto existe no RTDB
    project_ref = db.reference(f"neural/nodes/{project_id}")
    project_data = project_ref.get()
    if not project_data:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # ─────────────────────────────────────────────────────────────
    # TAREFA 2.7: Autenticação do agente por HMAC (X-Agent-Secret)
    # ─────────────────────────────────────────────────────────────
    # O agente envia header `X-Agent-Secret` = HMAC-SHA256(agent_secret, project_id).
    # O segredo é gerado por projeto e guardado em neural/nodes/{id}/agent_secret.
    # Sem segredo OU com segredo inválido -> 401/403 (bloqueia spoofing de telemetria).
    import hmac as _hmac
    import hashlib as _hashlib

    stored_secret = project_data.get("agent_secret", "")

    if not stored_secret:
        # Se ainda não há segredo configurado, gera um agora e grava no projeto.
        # (Compat: permite que o report embrionário exista, mas já registra o segredo.)
        stored_secret = secrets.token_urlsafe(32)
        project_ref.child("agent_secret").set(stored_secret)

    provided_sig = request.headers.get("X-Agent-Secret", "")
    expected_sig = _hmac.new(
        stored_secret.encode(),
        project_id.encode(),
        _hashlib.sha256
    ).hexdigest()

    if not provided_sig or not _hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(status_code=403, detail="Segredo do agente inválido")

    # Sanitiza e clampa todos os campos
    sanitized = {
        "projectId": project_id,
        "status": sanitize_string(payload.get("status", "unknown"), 50),
        "framework": sanitize_string(payload.get("framework", ""), 100),
        "tech_stack": sanitize_string(payload.get("tech_stack", ""), 200),
        "cpu": clamp_number(payload.get("cpu"), 0, 100),
        "ram": clamp_number(payload.get("ram"), 0, 100),
        "disk": clamp_number(payload.get("disk"), 0, 100),
        "load": clamp_number(payload.get("load"), 0, 10000),
        "latency": clamp_number(payload.get("latency"), 0, 60000),
        "timestamp": {".sv": "timestamp"}
    }

    # Grava no RTDB
    project_ref.child("health").update(sanitized)

    return JSONResponse({"status": "ok", "projectId": project_id})


# ─────────────────────────────────────────────────────────────
# AGENT-SCRIPT (PROTEGIDO — exige Bearer admin)
# ─────────────────────────────────────────────────────────────

@router.get("/agent-script")
async def get_agent_script(request: Request):
    """
    Retorna o script de instalação do agente de monitoramento.
    ✅ CORREÇÃO A1: Agora exige Bearer admin (não é mais público).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")

    token = auth_header.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        if not decoded.get("admin", False):
            raise HTTPException(status_code=403, detail="Acesso administrativo exigido")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    # Script Python do agente (sem comandos de execução perigosos)
    script = """#!/usr/bin/env python3
# Agent Sentinel — Monitoramento CyberCore IA
# NÃO execute como root. Use um usuário dedicado.
# TAREFA 2.7: o agente envia X-Agent-Secret = HMAC-SHA256(AGENT_SECRET, PROJECT_ID).

import sys
import os
import json
import time
import hmac
import hashlib
import urllib.request
import urllib.error
import psutil

PROJECT_ID = sys.argv[1] if len(sys.argv) > 1 else "default"
AGENT_SECRET = "TROCAR_PELO_SEGREDO_DO_PROJETO"  # gerado pelo backend e informado na instalação
REPORT_URL = "https://seu-backend.com/api/monitor/report"
INTERVAL = 60  # segundos

def report_signature():
    # HMAC do project_id usando o segredo do projeto
    return hmac.new(AGENT_SECRET.encode(), PROJECT_ID.encode(), hashlib.sha256).hexdigest()

def collect_metrics():
    return {
        "projectId": PROJECT_ID,
        "status": "online",
        "cpu": psutil.cpu_percent(interval=1),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "load": os.getloadavg()[0] if hasattr(os, "getloadavg") else 0,
        "timestamp": int(time.time())
    }

def send_report(data):
    try:
        req = urllib.request.Request(
            REPORT_URL,
            data=json.dumps(data).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Agent-Secret": report_signature(),
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERR] {e}")
        return False

if __name__ == "__main__":
    print(f"[Agent] Projeto: {PROJECT_ID}")
    while True:
        metrics = collect_metrics()
        if send_report(metrics):
            print(f"[OK] {metrics['timestamp']}")
        else:
            print("[FAIL] Report não enviado")
        time.sleep(INTERVAL)
"""
    return PlainTextResponse(content=script, media_type="text/x-python")


# ─────────────────────────────────────────────────────────────
# LISTAR PROJETOS (admin)
# ─────────────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects(request: Request):
    """Lista todos os projetos monitorados."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")

    token = auth_header.split(" ", 1)[1]
    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        if not decoded.get("admin", False):
            raise HTTPException(status_code=403, detail="Acesso administrativo exigido")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    nodes = db.reference("neural/nodes").get() or {}
    projects = []
    for pid, data in nodes.items():
        projects.append({
            "id": pid,
            "name": sanitize_string(data.get("name", pid), 100),
            "status": sanitize_string(data.get("health", {}).get("status", "unknown"), 50),
            "last_seen": data.get("health", {}).get("timestamp", 0)
        })

    return JSONResponse({"projects": projects})


# ─────────────────────────────────────────────────────────────
# TAREFA 3.1: Endpoints CRUD de projetos (Opção A) — geram ID no servidor,
# whitelist de campos e validação de identifier. Protegidos pelo middleware
# admin_auth_middleware (exige admin para /api/*).
# Router separado com prefix /api/project (coincide com as chamadas de watch.js).
# ─────────────────────────────────────────────────────────────

project_router = APIRouter(prefix="/api/project", tags=["project"])


def _validate_identifier(identifier: str) -> bool:
    """Valida identifier como URL/domínio seguro (allowlist de esquemas)."""
    if not identifier or len(identifier) > 300:
        return False
    low = identifier.lower()
    if low.startswith("http://"):
        return False  # rejeitar HTTP inseguro
    if low.startswith("https://"):
        return bool(re.match(r"^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?(/.*)?$", low))
    # domínio simples ou any valid package/app id
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,199}$", identifier))


@project_router.post("/analyze")
async def analyze_project(request: Request):
    """Analisa um identificador e retorna metadados básicos (sem gravar)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    identifier = (body.get("identifier") or "").strip()
    ptype = (body.get("type") or "website").strip()

    if ptype not in ("website", "android", "api"):
        raise HTTPException(status_code=400, detail="Tipo inválido (website|android|api)")
    if not _validate_identifier(identifier):
        raise HTTPException(status_code=400, detail="Identificador inválido (URL ou domínio)")

    framework = "—"
    name = identifier
    # best-effort: extrai hostname para exibição amigável
    m = re.match(r"^https?://([^/]+)", name.lower())
    if m:
        name = m.group(1)

    real_status = "offline"
    real_latency = 0
    try:
        test_url = identifier if identifier.startswith(("http://", "https://")) else f"https://{identifier}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            start = time.time()
            resp = await client.head(test_url, follow_redirects=True)
            real_latency = int((time.time() - start) * 1000)
            real_status = "online" if resp.status_code < 400 else "degraded"
    except Exception:
        pass

    return JSONResponse({
        "status": "success",
        "name": sanitize_string(name, 120),
        "identifier": identifier,
        "framework": framework,
        "health": {
            "status": real_status,
            "last_checked": {".sv": "timestamp"},
            "latency_ms": real_latency,
        }
    })


@project_router.post("/save")
async def save_project(request: Request):
    """Persiste um projeto monitorado. O ID é gerado no SERVIDOR (NUNCA no cliente)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    identifier = (body.get("identifier") or "").strip()
    ptype = (body.get("type") or "website").strip()
    name = (body.get("name") or identifier).strip()

    if ptype not in ("website", "android", "api"):
        raise HTTPException(status_code=400, detail="Tipo inválido (website|android|api)")
    if not _validate_identifier(identifier):
        raise HTTPException(status_code=400, detail="Identificador inválido (URL ou domínio)")

    # Verificar duplicidade
    existing = db.reference("neural/nodes").get() or {}
    for pid, pdata in existing.items():
        if pdata.get("identifier") == identifier:
            raise HTTPException(status_code=409, detail="Projeto já conectado")

    # Whitelist de campos — ignora qualquer coisa além destes (anti mass assignment)
    project_id = db.reference("neural/nodes").push().key  # UUID gerado pelo Firebase
    project_data = {
        "id": project_id,
        "name": sanitize_string(name, 120),
        "type": ptype,
        "identifier": sanitize_string(identifier, 300),
        "framework": sanitize_string(body.get("framework") or "—", 100),
        "addedAt": {".sv": "timestamp"},
        "health": {
            "status": "pending",
            "last_checked": {".sv": "timestamp"},
        }
    }
    db.reference(f"neural/nodes/{project_id}").set(project_data)

    return JSONResponse({"status": "success", "id": project_id})


@project_router.post("/remove")
async def remove_project(request: Request):
    """Remove um projeto monitorado."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    project_id = (body.get("id") or "").strip()
    if not re.match(r"^[-a-zA-Z0-9_]{1,64}$", project_id):
        raise HTTPException(status_code=400, detail="id inválido")

    ref = db.reference(f"neural/nodes/{project_id}")
    if not ref.get():
        return JSONResponse({"status": "not_found"})
    ref.delete()
    return JSONResponse({"status": "success"})


@project_router.post("/toggle")
async def toggle_project(request: Request):
    """
    TAREFA 3.2: Conecta/desconecta um projeto via servidor (não escreve direto
    no RTDB, contornando a regra neural/nodes/$projectId.write:false).
    Body: { "id": "...", "status": "online" | "offline" }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    project_id = (body.get("id") or "").strip()
    status = (body.get("status") or "").strip()

    if not re.match(r"^[-a-zA-Z0-9_]{1,64}$", project_id):
        raise HTTPException(status_code=400, detail="id inválido")
    if status not in ("online", "offline"):
        raise HTTPException(status_code=400, detail="status deve ser online|offline")

    ref = db.reference(f"neural/nodes/{project_id}")
    node = ref.get()
    if not node:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Mantém health.reported (agente) e grava health.override (operador) separados,
    # então o estado do agente não é corrompido pelo toggle manual.
    ref.child("health/override").set({"status": status, "by": "operator"})

    return JSONResponse({"status": "success", "id": project_id, "override": status})
