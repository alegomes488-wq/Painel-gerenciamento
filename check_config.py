import firebase_admin
from firebase_admin import credentials, db
import os
import json

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

config = db.reference('config').get()
print(json.dumps(config, indent=2))
