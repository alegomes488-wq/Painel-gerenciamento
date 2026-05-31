import firebase_admin
from firebase_admin import credentials, db
import os
import asyncio
import sys

# Garante que o Python encontre o main.py
backend_dir = os.path.dirname(__file__)
sys.path.append(backend_dir)

def init_firebase():
    # Tenta vários nomes de arquivos comuns
    possible_creds = ['firebase-adminsdk.json', 'serviceAccountKey.json']
    for filename in possible_creds:
        path = os.path.join(backend_dir, filename)
        if os.path.exists(path):
            if not firebase_admin._apps:
                cred = credentials.Certificate(path)
                firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
            return True

    # Se não achar arquivo, tenta variável de ambiente
    cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    if cred_json:
        cred_dict = json.loads(cred_json)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
        return True

    print("❌ Erro: Nenhuma credencial Firebase encontrada (JSON ou ENV).")
    return False

async def run_validation_test():
    print("🚀 [CYBERCORE] INICIANDO VALIDAÇÃO PROFUNDA...")
    if not init_firebase(): return

    try:
        from main import auto_approve_withdrawals

        # Auditoria prévia manual
        withdrawals = db.reference('withdrawals').get() or {}
        print(f"📦 Analisando {len(withdrawals)} UIDs no banco...")

        found_any = False
        for uid, user_ws in withdrawals.items():
            if isinstance(user_ws, dict):
                for wid, data in user_ws.items():
                    status = data.get('status')
                    amount = data.get('amount')
                    print(f"   🔍 Saque {wid}: Status='{status}', Valor=R${amount}")
                    if status == 'pending': found_any = True

        if not found_any:
            print("⚠️ Nenhum saque PENDENTE real. Criando um para teste forçado...")
            test_wid = f"TEST_{int(asyncio.get_event_loop().time())}"
            db.reference(f'withdrawals/test_user_nexus/{test_wid}').set({
                "amount": 1.10,
                "pixKey": "teste@pix.com",
                "status": "pending",
                "timestamp": {".sv": "timestamp"}
            })
            print(f"✅ Saque de teste criado: {test_wid}")

        print("\n⚙️ Chamando 'process_all_payments' (Sentinel Sentinel 2.0)...")
        result = await auto_approve_withdrawals(force=True)
        print(f"\n📊 RESULTADO FINAL: {result}")

    except Exception as e:
        print(f"💥 Erro: {e}")

if __name__ == "__main__":
    asyncio.run(run_validation_test())
