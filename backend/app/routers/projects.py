import hmac
import ipaddress
import socket
import time
import uuid
from urllib.parse import urljoin, urlparse
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import settings
from app.services.firebase_service import get_db

router = APIRouter(prefix="/api", tags=["projects"])

TRUSTED_HEADERS = ("x-powered-by", "server", "x-aspnet-version", "x-nginx-version")
STATIC_MARKERS = ("/static/", "/assets/", "/_next/", "/dist/")
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
BLOCKED_METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "instance-data.ec2.internal",
}


class UnsafeTargetError(ValueError):
    pass


def _normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeTargetError("URL HTTP(S) inválida")
    if parsed.username or parsed.password:
        raise UnsafeTargetError("Credenciais na URL não são permitidas")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in BLOCKED_METADATA_HOSTS or hostname.endswith(".internal"):
        raise UnsafeTargetError("Destino interno bloqueado")

    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
            }
        except (socket.gaierror, UnicodeError) as exc:
            raise UnsafeTargetError("Host não resolvido") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeTargetError("Endereço privado, local ou reservado bloqueado")
    return url


def _detect_framework(headers: dict, body: str) -> str:
    for h in TRUSTED_HEADERS:
        value = headers.get(h, "").lower()
        if "nginx" in value:
            return "nginx"
        if "asp.net" in value:
            return "ASP.NET"
        if "express" in value:
            return "Express.js"
    low = body.lower()
    if "_next/" in low or "nextdata" in low:
        return "Next.js"
    if "__nuxt" in low:
        return "Nuxt.js"
    if "ng-version" in low or "angular.io" in low:
        return "Angular"
    if "reactroot" in low or "react-dom" in low:
        return "React"
    if "vue" in low and "vuedata" in low:
        return "Vue.js"
    if "django" in low or "csrfmiddlewaretoken" in low:
        return "Django"
    if "flask" in low or "werkzeug" in low:
        return "Flask"
    return "Desconhecido"


async def _probe(identifier: str, probe_type: str) -> dict:
    start = time.perf_counter()
    current_url = _validate_public_url(identifier)
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            # Re-resolve and validate every hop; redirects never inherit trust.
            _validate_public_url(current_url)
            resp = await client.get(current_url, headers={"User-Agent": "CyberCore-Monitor/1.0"})
            if resp.status_code not in REDIRECT_STATUSES:
                break
            location = resp.headers.get("location")
            if not location or redirect_count == MAX_REDIRECTS:
                raise UnsafeTargetError("Cadeia de redirecionamento inválida")
            current_url = urljoin(str(resp.url), location)
        else:  # pragma: no cover - loop always exits or raises
            raise UnsafeTargetError("Redirecionamentos excessivos")

        latency_ms = int((time.perf_counter() - start) * 1000)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.text[:200_000]
        framework = _detect_framework(headers, body)

        health_status = "online"
        if resp.status_code >= 500:
            health_status = "degraded"

        health = {
            "status": health_status,
            "http_status": resp.status_code,
            "latency_ms": latency_ms,
            "framework": framework,
            "last_checked": datetime.now().isoformat(),
            "last_report": datetime.now().isoformat(),
        }

        # Extrai nome amigável a partir do título/meta do site
        name = None
        if probe_type == "website":
            for marker in ('<title', 'og:title'):
                idx = body.lower().find(marker)
                if idx != -1:
                    name = body[idx:idx + 220].split(">", 1)[-1].split("<", 1)[0].strip()
                    if name:
                        break
            if name and len(name) > 80:
                name = name[:80]

        return {"status": "success", "name": name, "framework": framework, "health": health}


@router.post("/project/analyze")
async def analyze_project(request: Request, payload: dict):
    probe_type = payload.get("type") or "website"
    identifier = payload.get("identifier") or ""
    if not identifier:
        return {"status": "error", "msg": "Identificador não informado"}

    try:
        if probe_type in ("website", "api"):
            url = _normalize_url(identifier)
            return await _probe(url, probe_type)
        # Android / local: sem probe HTTP — apenas registra
        return {
            "status": "success",
            "name": identifier,
            "framework": "mobile" if probe_type == "android" else "local",
            "health": {"status": "offline", "last_checked": datetime.now().isoformat()},
        }
    except (httpx.HTTPError, UnsafeTargetError):
        return {
            "status": "error",
            "msg": "Falha ao analisar — URL inacessível ou site fora do ar.",
        }
    except Exception as e:
        return {"status": "error", "msg": f"Erro ao analisar: {str(e)}"}


@router.post("/project/save")
async def save_project(request: Request, payload: dict):
    project_id = payload.get("id") or f"PRJ{uuid.uuid4().hex[:8].upper()}"
    data = payload.get("data") or {}
    if not data.get("identifier"):
        return {"status": "error", "msg": "Dados do projeto incompletos"}

    try:
        db = get_db()
        node = {"id": project_id, **data}
        db.reference(f"neural/nodes/{project_id}").set(node)
        return {"status": "success", "id": project_id}
    except Exception as e:
        return {"status": "error", "msg": f"Erro ao salvar: {str(e)}"}


@router.post("/project/remove")
async def remove_project(request: Request, payload: dict):
    project_id = payload.get("id") or ""
    if not project_id:
        return {"status": "error", "msg": "ID do projeto não informado"}

    try:
        db = get_db()
        db.reference(f"neural/nodes/{project_id}").delete()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "msg": f"Erro ao remover: {str(e)}"}


AGENT_SCRIPT = r'''#!/usr/bin/env python3
# Brasil Hexa Monitor Agent — reporta CPU/RAM/disco ao painel admin.
import json
import os
import time
import urllib.request

BASE_URL = os.environ.get("CYBERCORE_BASE_URL", "http://localhost:7861").rstrip("/")
PROJECT_ID = os.environ.get("CYBERCORE_PROJECT_ID", "")
MONITOR_TOKEN = os.environ.get("CYBERCORE_MONITOR_TOKEN", "")
INTERVAL = 30

try:
    import psutil
except ImportError:
    raise SystemExit("Requer: pip install psutil requests")


def collect():
    return {
        "projectId": PROJECT_ID,
        "cpu": psutil.cpu_percent(interval=1),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "load": psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else None,
        "ts": int(time.time() * 1000),
    }


def report(payload):
    if not PROJECT_ID or not MONITOR_TOKEN:
        raise RuntimeError("CYBERCORE_PROJECT_ID e CYBERCORE_MONITOR_TOKEN são obrigatórios")
    req = urllib.request.Request(
        f"{BASE_URL}/api/monitor/report",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Monitor-Token": MONITOR_TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


if __name__ == "__main__":
    while True:
        try:
            report(collect())
        except Exception as e:
            print("[AGENT] falha:", e)
        time.sleep(INTERVAL)
'''


@router.get("/monitor/agent-script", response_class=PlainTextResponse)
async def agent_script(request: Request):
    return AGENT_SCRIPT


def _safe_float(value, lo, hi):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if lo <= num <= hi else None


@router.post("/monitor/report")
async def monitor_report(request: Request, payload: dict):
    expected_token = settings.MONITOR_SHARED_SECRET
    supplied_token = request.headers.get("X-Monitor-Token", "")
    if not expected_token:
        return JSONResponse(status_code=503, content={"status": "error", "msg": "Telemetria não configurada"})
    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        return JSONResponse(status_code=403, content={"status": "error", "msg": "Token de telemetria inválido"})

    project_id = payload.get("projectId") or ""
    if not project_id:
        return {"status": "error", "msg": "projectId ausente"}

    try:
        db = get_db()
        node_ref = db.reference(f"neural/nodes/{project_id}")
        if not node_ref.get():
            return {"status": "error", "msg": "Projeto não encontrado"}

        db.reference(f"neural/nodes/{project_id}/health").set({
            "status": "online",
            "cpu": _safe_float(payload.get("cpu"), 0, 100),
            "ram": _safe_float(payload.get("ram"), 0, 100),
            "disk": _safe_float(payload.get("disk"), 0, 100),
            "load": _safe_float(payload.get("load"), 0, 10000),
            "last_report": datetime.now().isoformat(),
        })
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}
