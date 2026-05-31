import firebase_admin
from firebase_admin import credentials, db
import os
import uuid
from datetime import datetime

# Configuração do Firebase
project_root = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(project_root, "firebase-secrets", "firebase-adminsdk.json")

if not os.path.exists(cred_path):
    print("ERRO: Chave do Firebase não encontrada.")
    exit()

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'
    })

def create_test_withdrawal():
    # Dados do saque simulado
    test_uid = "USER_TESTE_CYBERCORE"
    withdrawal_id = str(uuid.uuid4())[:8]

    withdrawal_data = {
        "amount": 50.00,
        "fullname": "Usuário Teste CyberCore",
        "pixKey": "teste@cybercore.com",
        "pixKeyType": "email",
        "status": "pending",
        "timestamp": {".sv": "timestamp"},
        "method": "PIX"
    }

    print(f"Enviando pedido de saque simulado ({withdrawal_id})...")

    try:
        # Insere o saque no Firebase
        db.reference(f'withdrawals/{test_uid}/{withdrawal_id}').set(withdrawal_data)

        # Também cria um log de atividade para o Sentinel detectar
        db.reference('logs/activity').push({
            "timestamp": {".sv": "timestamp"},
            "user": "SISTEMA",
            "action": f"Novo pedido de saque simulado gerado para {test_uid}"
        })

        print("\n✅ SUCESSO!")
        print(f"UID: {test_uid}")
        print(f"WID: {withdrawal_id}")
        print("\nVerifique a aba 'Saques PIX' no seu Painel Premium.")
    except Exception as e:
        print(f"❌ ERRO ao inserir no Firebase: {e}")

if __name__ == "__main__":
    create_test_withdrawal()
