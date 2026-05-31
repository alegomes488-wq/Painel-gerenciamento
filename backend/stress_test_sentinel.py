import firebase_admin
from firebase_admin import credentials, db
import os
import time
import sys

# Adiciona o diretório atual ao path para importar o main
backend_dir = os.path.dirname(__file__)
sys.path.append(backend_dir)

# Configuração Firebase
# Tenta encontrar no diretório de segredos do projeto ou no diretório local
project_root = os.path.dirname(backend_dir)
possible_creds = [
    os.path.join(project_root, "firebase-secrets", "firebase-adminsdk.json"),
    os.path.join(backend_dir, "firebase-adminsdk.json")
]

cred_path = None
for p in possible_creds:
    if os.path.exists(p):
        cred_path = p
        break

if not cred_path:
    print(f"❌ Erro: firebase-adminsdk.json não encontrado nos caminhos: {possible_creds}")
    exit()

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})

from main import tool_sentinel_enforcement

def run_stress_test():
    print("🛡️ INICIANDO SIMULAÇÃO DE ATAQUE DE FRAUDE (STRESS TEST)...")

    test_uids = [f"SUSPECT_USER_{i}" for i in range(1, 11)]

    # 1. Injetar usuários suspeitos
    print(f"💉 Injetando {len(test_uids)} perfis com Risk Score crítico...")
    for uid in test_uids:
        db.reference(f'users/{uid}').set({
            "fullname": f"Atacante Simulado {uid[-1]}",
            "balance": 5000.0,  # Saldo impossível
            "videosWatched": 10,
            "risk_score": 100,
            "status": "ativo",
            "createdAt": {".sv": "timestamp"}
        })

    # 2. Registrar tentativa no log de atividade (para aparecer na Sala de Guerra)
    db.reference('logs/activity').push({
        "user": "SISTEMA",
        "action": "🚨 ALERTA: Tentativa de Injeção de Saldo em Massa Detectada!",
        "timestamp": {".sv": "timestamp"}
    })

    print("🔍 Sentinel 2.0 entrando em modo de contenção...")
    time.sleep(2)

    # 3. Executar o Enforcement
    result = tool_sentinel_enforcement()
    print(f"⚡ Resultado do Sentinel: {result}")

    # 4. Verificar se foram banidos
    banned_count = 0
    for uid in test_uids:
        user = db.reference(f'users/{uid}').get()
        if user and user.get('status') == 'banido':
            banned_count += 1

    print(f"\n--- RELATÓRIO FINAL DO TESTE ---")
    print(f"Usuários Injetados: {len(test_uids)}")
    print(f"Usuários Neutralizados: {banned_count}")

    if banned_count == len(test_uids):
        print("✅ SUCESSO TOTAL: O Sentinel 2.0 protegeu o sistema contra o ataque em massa.")
    else:
        print("⚠️ ALERTA: Alguns usuários não foram neutralizados. Verifique a lógica de score.")

    # Limpeza opcional (comente se quiser ver no painel)
    # for uid in test_uids: db.reference(f'users/{uid}').delete()

if __name__ == "__main__":
    run_stress_test()
