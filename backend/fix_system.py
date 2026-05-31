import firebase_admin
from firebase_admin import credentials, db
import os

backend_dir = os.path.dirname(__file__)
cred_path = os.path.join(backend_dir, 'serviceAccountKey.json')

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})

# 1. Ajustar CPM
db.reference('config/cpm').set(1.50)
print("✅ CPM ajustado para 1.50")

# 2. Verificar Fraudes
frauds = db.reference('logs/frauds').get()
if frauds:
    print("\n🚨 RELATÓRIO DE FRAUDES:")
    for uid, f_data in frauds.items():
        print(f"Usuário: {uid} - {len(f_data)} incidentes detectados.")
else:
    print("\n🛡️ Nenhuma fraude detectada.")

# 3. Verificar Saúde Financeira
users = db.reference('users').get() or {}
total_debt = sum([float(u.get('balance', 0)) for u in users.values() if isinstance(u, dict)])
print(f"\n💰 Dívida Total Atual: R$ {total_debt:.2f}")
