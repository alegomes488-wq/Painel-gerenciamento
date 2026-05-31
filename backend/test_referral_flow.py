import firebase_admin
from firebase_admin import credentials, db
import time
from datetime import datetime
import os
import asyncio
from unittest.mock import MagicMock

# Configuração Firebase
backend_dir = os.path.dirname(__file__)
cred_path = os.path.join(backend_dir, "serviceAccountKey.json")

if not os.path.exists(cred_path):
    print("❌ Credenciais não encontradas!")
    exit()

cred = credentials.Certificate(cred_path)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'
    })

def test_flow():
    sponsor_uid = "SPONSOR_TEST_REF"
    referred_uid = "REFERRED_TEST_REF"

    print(f"🚀 Iniciando teste de indicação...")

    # Limpeza prévia
    db.reference(f'users/{sponsor_uid}').delete()
    db.reference(f'users/{referred_uid}').delete()
    db.reference(f'active_sessions/{referred_uid}').delete()

    # 1. Criar Padrinho
    db.reference(f'users/{sponsor_uid}').set({
        "fullname": "Padrinho de Teste",
        "firstname": "Padrinho",
        "balance": 0.0,
        "referralBonus": 0.0,
        "validReferrals": 0,
        "status": "ativo",
        "legal_acceptance": {"accepted": True}
    })
    print(f"✅ Padrinho criado: {sponsor_uid}")

    # 2. Criar Indicado com link do Padrinho
    db.reference(f'users/{referred_uid}').set({
        "fullname": "Indicado de Teste",
        "firstname": "Indicado",
        "referredBy": sponsor_uid,
        "videosWatched": 0,
        "balance": 0.0,
        "status": "ativo",
        "legal_acceptance": {"accepted": True}
    })
    print(f"✅ Indicado criado: {referred_uid} (Indicado por {sponsor_uid})")

    # Importa a função do main.py
    import sys
    sys.path.append(backend_dir)
    from main import complete_video

    async def simulate_completion():
        print(f"🎬 Simulando 15 vídeos para o indicado...")
        mock_request = MagicMock()
        mock_request.headers = {"X-Forwarded-For": "127.0.0.1"}
        mock_request.client.host = "127.0.0.1"

        for i in range(1, 16):
            db.reference(f'active_sessions/{referred_uid}').set({
                "startTime": time.time() - 35, # Garante que passou os 28s
                "status": "watching"
            })
            # Chama a função do backend
            await complete_video(referred_uid, mock_request)
            if i % 5 == 0:
                print(f"📹 Progresso: {i}/15 vídeos.")

    asyncio.run(simulate_completion())

    # 4. Verificar Resultados
    sponsor_data = db.reference(f'users/{sponsor_uid}').get()
    referred_data = db.reference(f'users/{referred_uid}').get()

    print("\n--- RESULTADOS ---")
    s_bal = sponsor_data.get('balance', 0)
    s_bonus = sponsor_data.get('referralBonus', 0)
    s_refs = sponsor_data.get('validReferrals', 0)
    r_bal = referred_data.get('balance', 0)

    print(f"Saldo Padrinho: R$ {s_bal:.2f}")
    print(f"Bônus Indicação Padrinho: R$ {s_bonus:.2f}")
    print(f"Indicações Válidas Padrinho: {s_refs}")
    print(f"Saldo Indicado: R$ {r_bal:.2f}")

    # Validação
    if s_bal == 0.50 and s_bonus == 0.50 and s_refs == 1 and r_bal >= 0.55:
        print("\n✅ TESTE BEM SUCEDIDO: O Padrinho recebeu R$ 0,50 e o Indicado atingiu bônus de ativação!")
    else:
        print("\n❌ TESTE FALHOU: Os valores não correspondem ao esperado.")
        if s_bal != 0.50: print(f"Motivo: Saldo padrinho {s_bal} != 0.50")
        if r_bal < 0.55: print(f"Motivo: Saldo indicado {r_bal} < 0.55")

if __name__ == "__main__":
    test_flow()
