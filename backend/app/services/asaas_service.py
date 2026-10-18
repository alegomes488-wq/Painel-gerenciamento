import hashlib

import httpx

from app.core.config import settings
# Importado para compatibilidade com tests/conftest.py (fixture fake_db faz
# monkeypatch em app.services.asaas_service.get_db). NÃO é usado para obter a
# credencial — segredo vem só de env (settings.ASAAS_API_KEY).
from app.services.firebase_service import get_db  # noqa: F401


async def process_asaas_pix(
    amount: float,
    pix_key: str,
    pix_type: str,
    description: str,
    external_ref: str = "",
):
    """Cria uma transferência PIX no Asaas (dinheiro real).

    A credencial vem SOMENTE de ``settings.ASAAS_API_KEY`` (env). Nunca de
    ``config/asaasKey`` no RTDB — segredo não pode morar em banco acessível
    ao cliente.
    """
    # Defense in depth: em simulação (ou sem chave) NUNCA abre cliente HTTP.
    if settings.SIMULATION_MODE or not settings.ASAAS_API_KEY:
        sim_id = "sim_" + hashlib.sha256(
            (external_ref or f"{pix_key}:{amount}").encode("utf-8")
        ).hexdigest()[:24]
        return {"id": sim_id, "status": "SIMULATED", "simulated": True}

    asaas_key = settings.ASAAS_API_KEY
    if not asaas_key:
        return {"errors": [{"description": "Chave API Asaas não configurada"}]}

    url = "https://www.asaas.com/api/v3/transfers"
    pix_mapping = {
        "CPF": "CPF", "CNPJ": "CNPJ", "EMAIL": "EMAIL",
        "PHONE": "PHONE", "EVP": "RANDOM_KEY",
    }

    # Idempotência: mesma referência externa (wid) nunca gera transferência dupla,
    # mesmo com retry do painel/N8N.
    idem = hashlib.sha256(
        (external_ref or f"{pix_key}:{amount}:{description}").encode("utf-8")
    ).hexdigest()

    headers = {
        "access_token": asaas_key,
        "Content-Type": "application/json",
        "asaas-idempotency-key": idem,
    }
    payload = {
        "value": amount,
        "pixAddressKey": pix_key,
        "pixAddressKeyType": pix_mapping.get(pix_type, "RANDOM_KEY"),
        "description": description,
    }
    if external_ref:
        payload["externalReference"] = external_ref

    async with httpx.AsyncClient(follow_redirects=False) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=30.0)
            return resp.json()
        except Exception as e:
            return {"errors": [{"description": f"Erro de conexão com Asaas: {type(e).__name__}"}]}
