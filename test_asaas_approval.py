import firebase_admin
from firebase_admin import credentials, db
import os
import requests
from datetime import datetime

# Configuração do Firebase
project_root = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(project_root, "firebase-secrets", "firebase-adminsdk.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'
    })

def approve_payment_test(wid):
    print(f"Iniciando teste de aprovação para saque: {wid}")
    try:
        config = db.reference('config').get() or {}
        api_key = config.get('asaasKey') or os.environ.get('ASAAS_API_KEY', '')
        if not api_key:
            print("ERRO: Chave Asaas não encontrada.")
            return

        is_prod = config.get('production', False)
        print(f"Modo Produção: {is_prod}")

        withdraw_data = None
        target_uid = None
        all_withdrawals = db.reference('withdrawals').get() or {}

        for uid, ws in all_withdrawals.items():
            if isinstance(ws, dict) and wid in ws:
                withdraw_data = ws[wid]
                target_uid = uid
                break

        if not withdraw_data:
            print("ERRO: Saque não localizado no Firebase.")
            return

        amount = float(withdraw_data.get('amount', 0))
        pix_key = withdraw_data.get('pixKey', '')
        pix_type_raw = withdraw_data.get('pixKeyType', 'EVP').upper()

        pix_type_map = {
            "EMAIL": "EMAIL", "CPF": "CPF", "CNPJ": "CNPJ",
            "PHONE": "PHONE", "TELEFONE": "PHONE", "EVP": "EVP", "ALEATORIA": "EVP"
        }
        pix_key_type = pix_type_map.get(pix_type_raw, "EVP")

        print(f"Dados do Saque: Valor={amount}, Chave={pix_key}, Tipo={pix_key_type}")

        asaas_url = "https://www.asaas.com/api/v3/transfers" if is_prod else "https://sandbox.asaas.com/api/v3/transfers"
        headers = {"access_token": api_key.strip(), "Content-Type": "application/json"}
        payload = {
            "value": amount,
            "pixAddressKey": pix_key,
            "pixAddressKeyType": pix_key_type,
            "description": f"CineCash Teste #{wid}"
        }

        print(f"Enviando requisição para: {asaas_url}")
        # Usaremos timeout curto para não travar
        resp = requests.post(asaas_url, json=payload, headers=headers, timeout=20)

        print(f"Resposta Asaas (Status {resp.status_code}): {resp.text}")

        if resp.status_code == 200:
            db.reference(f'withdrawals/{target_uid}/{wid}').update({
                "status": "paid",
                "paid_at": datetime.now().isoformat(),
                "test_execution": True
            })
            print("✅ Sucesso: Pagamento liquidado e Firebase atualizado.")
        else:
            print(f"❌ Erro no Asaas: {resp.text}")

    except Exception as e:
        print(f"❌ Erro inesperado: {e}")

if __name__ == "__main__":
    approve_payment_test("02d19685")
