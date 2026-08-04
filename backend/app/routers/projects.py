import time
import uuid
from urllib.parse import urlparse
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.services.firebase_service import get_db

router = APIRouter(prefix="/api", tags=["projects"])

TRUSTED_HEADERS = ("x-powered-by", "server", "x-aspnet-version", "x-nginx-version")
STATIC_MARKERS = ("/static/", "/assets/", "/_next/", "/dist/")


def _normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


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
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        resp = await client.get(identifier)
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
    except httpx.HTTPError:
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
import platform
import time
import urllib.request

BASE_URL = "http://localhost:7861"
PROJECT_ID = "PRJ_EXAMPLE"
INTERVAL = 30

try:
    import psutil
except ImportError:
    raise SystemExit("Requer: pip install psutil requests")


def collect():
    return {
        "projectId": PROJECT_ID,
        "hostname": platform.node(),
        "platform": platform.system() + " " + platform.release(),
        "cpu": psutil.cpu_percent(interval=1),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "load": psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else None,
        "ts": int(time.time() * 1000),
    }


def report(payload):
    req = urllib.request.Request(
        f"{BASE_URL}/api/monitor/report",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
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


@router.post("/monitor/report")
async def monitor_report(request: Request, payload: dict):
    project_id = payload.get("projectId") or ""
    if not project_id:
        return {"status": "error", "msg": "projectId ausente"}

    try:
        db = get_db()
        db.reference(f"neural/nodes/{project_id}/health").set({
            "status": "online",
            "cpu": payload.get("cpu"),
            "ram": payload.get("ram"),
            "disk": payload.get("disk"),
            "load": payload.get("load"),
            "hostname": payload.get("hostname"),
            "platform": payload.get("platform"),
            "last_report": datetime.now().isoformat(),
        })
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}
