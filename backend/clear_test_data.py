import firebase_admin
from firebase_admin import credentials, db
import os

# --- CONFIGURAÇÃO FIREBASE ---
backend_dir = os.path.dirname(__file__)
cred_path = os.path.join(backend_dir, 'serviceAccountKey.json')

if os.path.exists(cred_path):
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'
    })

    print("🚀 Iniciando limpeza de dados de teste...")

    # 1. Limpar Histórico de Saques (withdrawals)
    db.reference('withdrawals').delete()
    print("✅ Histórico de saques (withdrawals) removido.")

    # 2. Limpar Fila de Pendentes (admin/pending_withdrawals)
    db.reference('admin/pending_withdrawals').delete()
    print("✅ Fila de saques pendentes removida.")

    # 3. Limpar logs de atividade (opcional, mas recomendado para limpeza total)
    db.reference('logs/activity').delete()
    db.reference('logs/cybercore_live').delete()
    print("✅ Logs de atividade e CyberCore Live limpos.")

    print("\n✨ Limpeza concluída com sucesso!")
else:
    print("❌ Erro: Arquivo serviceAccountKey.json não encontrado.")
