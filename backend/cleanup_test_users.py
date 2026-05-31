import firebase_admin
from firebase_admin import credentials, db
import os
import sys

# Adiciona o diretório atual ao path
backend_dir = os.path.dirname(__file__)
sys.path.append(backend_dir)

# Configuração Firebase
project_root = os.path.dirname(backend_dir)
cred_path = os.path.join(project_root, "firebase-secrets", "firebase-adminsdk.json")

if not os.path.exists(cred_path):
    cred_path = os.path.join(backend_dir, "firebase-adminsdk.json")

if not os.path.exists(cred_path):
    print("❌ Erro: Arquivo de credenciais não encontrado!")
    exit()

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})

def cleanup():
    print("🧹 Iniciando limpeza de usuários de teste...")

    users_ref = db.reference('users')
    users = users_ref.get()

    if not users:
        print("Nenhum usuário encontrado.")
        return

    deleted_count = 0
    for uid in users:
        if uid.startswith("SUSPECT_USER_"):
            print(f"Removendo: {uid}")
            users_ref.child(uid).delete()
            deleted_count += 1

    print(f"✅ Concluído! {deleted_count} usuários de teste removidos.")

if __name__ == "__main__":
    cleanup()
