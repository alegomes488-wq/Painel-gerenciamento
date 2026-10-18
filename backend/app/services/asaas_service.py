import httpx
from app.core.config import settings
from app.services.firebase_service import get_db

async def process_asaas_pix(amount: float, pix_key: str, pix_type: str, description: str, external_ref: str = ""):
    asaas_key = settings.ASAAS_API_KEY
    if not asaas_key:
        config = get_db().reference("config").get() or {}
        asaas_key = config.get("asaasKey") or config.get("asaas_key")

    if not asaas_key:
        return {"errors": [{"description": "Chave API Asaas não configurada"}]}

    url = "https://www.asaas.com/api/v3/transfers"
    pix_mapping = {
        "CPF": "CPF", "CNPJ": "CNPJ", "EMAIL": "EMAIL",
        "PHONE": "PHONE", "EVP": "RANDOM_KEY"
    }
    headers = {
        "access_token": asaas_key,
        "Content-Type": "application/json"
    }
    payload = {
        "value": amount,
        "pixAddressKey": pix_key,
        "pixAddressKeyType": pix_mapping.get(pix_type, "RANDOM_KEY"),
        "description": description
    }
    if external_ref:
        payload["externalReference"] = external_ref
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=30.0)
            return resp.json()
        except Exception as e:
            return {"errors": [{"description": f"Erro de conexão com Asaas: {str(e)}"}]}
