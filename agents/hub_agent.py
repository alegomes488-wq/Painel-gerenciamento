#!/usr/bin/env python3
"""Agente genérico do Painel HUB — envia métricas para POST /api/hub/events.

Autenticação: HMAC-SHA256(HUB_AGENT_SECRET, "hub-ingest") no header
X-Hub-Agent-Secret (mesmo padrão dos agentes Android/iOS/n8n).

Uso:
  export HUB_AGENT_SECRET=...
  python hub_agent.py --backend http://localhost:7861 --section app \
      --data '{"crash_rate": 1.2, "apk_version": "4.2.0"}' --source n8n

  python hub_agent.py --backend https://api.seusite.com \
      --section network --data @evento.json --source waf-exporter

Seções válidas: web, app, api, sessions, funnels, tickets, user_context,
apk, network, auth, vulnerabilities.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request


def load_data(raw: str) -> dict:
    """Aceita JSON direto ou @arquivo.json."""
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Agente generico do Painel HUB (Cyber Core IA)")
    parser.add_argument("--backend", required=True, help="URL base do backend (ex.: http://localhost:7861)")
    parser.add_argument("--section", required=True, help="Seção do HUB (web, app, api, apk, network, auth, ...)")
    parser.add_argument("--data", required=True, help='Payload JSON ou @arquivo.json')
    parser.add_argument("--source", default="python-agent", help="Identificação do agente (máx. 60 chars)")
    parser.add_argument("--timeout", type=float, default=15.0, help="Timeout HTTP em segundos")
    args = parser.parse_args()

    secret = (os.environ.get("HUB_AGENT_SECRET") or "").strip()
    if not secret:
        print("ERRO: defina a variável de ambiente HUB_AGENT_SECRET.", file=sys.stderr)
        return 2

    try:
        data = load_data(args.data)
    except (OSError, ValueError) as exc:
        print(f"ERRO: payload inválido: {exc}", file=sys.stderr)
        return 2

    signature = hmac.new(secret.encode("utf-8"), b"hub-ingest", hashlib.sha256).hexdigest()
    payload = json.dumps({
        "section": args.section,
        "source": args.source,
        "data": data,
    }).encode("utf-8")
    url = args.backend.rstrip("/") + "/api/hub/events"
    request = urllib.request.Request(  # nosec B310 — URL do operador, HTTPS em produção
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Agent-Secret": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:  # nosec B310
            body = response.read().decode("utf-8")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"ERRO HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"ERRO de conexão: {exc.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
