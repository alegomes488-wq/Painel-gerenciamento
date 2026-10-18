import hashlib

import httpx

from app.core.config import settings

async def process_asaas_pix(
    amount: float,
    pix_key: str,
    pix_type: str,
    description: str,
    idempotency_key: str,
):
    if not settings.real_payments_enabled:
        simulation_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
        return {"id": f"sim_{simulation_id}", "status": "SIMULATED", "simulated": True}

    asaas_key = settings.ASAAS_API_KEY
    if not asaas_key:
        return {"errors": [{"description": "Pagamento real bloqueado: credencial Asaas ausente"}]}

    url = "https://www.asaas.com/api/v3/transfers"
    pix_mapping = {
        "CPF": "CPF", "CNPJ": "CNPJ", "EMAIL": "EMAIL",
        "PHONE": "PHONE", "EVP": "RANDOM_KEY"
    }
    headers = {
        "access_token": asaas_key,
        "asaas-idempotency-key": idempotency_key,
        "Content-Type": "application/json"
    }
    payload = {
        "value": amount,
        "pixAddressKey": pix_key,
        "pixAddressKeyType": pix_mapping.get(pix_type, "RANDOM_KEY"),
        "description": description
    }
    async with httpx.AsyncClient(follow_redirects=False) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=30.0)
            resp.raise_for_status()
            result = resp.json()
            if not isinstance(result, dict):
                raise ValueError("Resposta inválida")
            return result
        except (httpx.HTTPError, ValueError):
            return {"errors": [{"description": "Falha segura na comunicação com Asaas"}]}
