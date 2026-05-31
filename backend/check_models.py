import firebase_admin
from firebase_admin import credentials, db
import os
import requests

backend_dir = os.path.dirname(__file__)
cred_path = os.path.join(backend_dir, 'serviceAccountKey.json')

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})

config = db.reference('config').get() or {}
api_key = str(config.get('geminiKey', '')).strip()

if not api_key:
    print("❌ API Key não encontrada no Firebase.")
else:
    print(f"Chave encontrada (começa com {api_key[:5]}...)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    resp = requests.get(url)
    if resp.status_code == 200:
        models = resp.json().get('models', [])
        print("Modelos disponíveis:")
        for m in models:
            if 'gemini' in m['name']:
                print(f" - {m['name']}")
    else:
        print(f"❌ Erro ao listar modelos: {resp.status_code} - {resp.text}")
