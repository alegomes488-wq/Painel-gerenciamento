#!/usr/bin/env python3
"""Sincroniza tickets de suporte (Zendesk) para a seção "tickets" do HUB.

Puxa chamados abertos + tags e o tempo médio de atendimento (TMA) de
chamados recentemente resolvidos, e publica via POST /api/hub/events
(autenticação HMAC — requer HUB_AGENT_SECRET).

Variáveis de ambiente:
  ZENDESK_SUBDOMAIN  ex.: "minhaempresa" (-> minhaempresa.zendesk.com)
  ZENDESK_EMAIL      e-mail do usuário de API
  ZENDESK_TOKEN      token de API do Zendesk
  HUB_AGENT_SECRET   segredo HMAC do canal de ingestão do HUB
  HUB_BACKEND        URL base do backend (padrão http://localhost:7861)

Sem as variáveis do Zendesk o script apenas avisa e sai com código 0 —
a integração é opcional e nunca quebra o pipeline.

Agende via cron/n8n a cada 5–15 min:
  */10 * * * * cd /opt/painel && .venv/bin/python agents/hub_tickets_sync.py
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BACKEND = os.environ.get("HUB_BACKEND", "http://localhost:7861").rstrip("/")
SOLVED_WINDOW_DAYS = 30


def _zendesk_get(path: str, params: dict) -> dict:
    subdomain = os.environ["ZENDESK_SUBDOMAIN"]
    email = os.environ["ZENDESK_EMAIL"]
    token = os.environ["ZENDESK_TOKEN"]
    url = f"https://{subdomain}.zendesk.com/api/v2/{path}?{urllib.parse.urlencode(params)}"
    creds = base64.b64encode(f"{email}/token:{token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(  # nosec B310 — URL oficial do Zendesk
        url, headers={"Authorization": f"Basic {creds}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def collect() -> dict:
    """Agrega tickets abertos (volume + tags) e TMA dos resolvidos recentes."""
    open_page = _zendesk_get("tickets.json", {"status": "open", "per_page": 100})
    open_tickets = open_page.get("tickets") or []

    reasons: dict = {}
    for ticket in open_tickets:
        for tag in (ticket.get("tags") or []):
            reasons[tag] = reasons.get(tag, 0) + 1

    solved_page = _zendesk_get("tickets.json", {"status": "solved", "per_page": 100})
    now = datetime.now(timezone.utc)
    minutes = []
    for ticket in solved_page.get("tickets") or []:
        created = ticket.get("created_at")
        solved = ticket.get("solved_at") or ticket.get("updated_at")
        if not created or not solved:
            continue
        try:
            t_created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            t_solved = datetime.fromisoformat(solved.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - t_created).days > SOLVED_WINDOW_DAYS:
            continue
        minutes.append(max(0.0, (t_solved - t_created).total_seconds() / 60.0))

    payload = {
        "open": len(open_tickets),
        "top_reasons": dict(sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:20]),
    }
    if minutes:
        payload["avg_minutes"] = round(sum(minutes) / len(minutes), 1)
    return payload


def publish(data: dict) -> None:
    secret = os.environ["HUB_AGENT_SECRET"].encode("utf-8")
    signature = hmac.new(secret, b"hub-ingest", hashlib.sha256).hexdigest()
    body = json.dumps({"section": "tickets", "source": "zendesk-sync", "data": data}).encode("utf-8")
    request = urllib.request.Request(  # nosec B310 — URL do operador
        BACKEND + "/api/hub/events",
        data=body,
        headers={"Content-Type": "application/json", "X-Hub-Agent-Secret": signature},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
        print(response.read().decode("utf-8"))


def main() -> int:
    missing = [name for name in ("ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_TOKEN")
               if not os.environ.get(name)]
    if missing:
        print(f"[hub-tickets-sync] Integração Zendesk não configurada ({', '.join(missing)}). Pulando.")
        return 0
    if not os.environ.get("HUB_AGENT_SECRET"):
        print("[hub-tickets-sync] ERRO: HUB_AGENT_SECRET ausente.", file=sys.stderr)
        return 2
    try:
        data = collect()
        publish(data)
        print(f"[hub-tickets-sync] Publicado: open={data.get('open')} tma={data.get('avg_minutes', '—')}min")
        return 0
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        print(f"[hub-tickets-sync] Falha (não fatal): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
