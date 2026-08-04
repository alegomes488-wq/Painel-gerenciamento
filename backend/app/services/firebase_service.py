import json
import firebase_admin
from firebase_admin import credentials, db, auth
from app.core.config import settings

def init_firebase():
    if not firebase_admin._apps:
        if settings.FIREBASE_SERVICE_ACCOUNT:
            cred_dict = json.loads(settings.FIREBASE_SERVICE_ACCOUNT)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'databaseURL': settings.FIREBASE_DATABASE_URL})
            print("[FIREBASE] Inicializado via Service Account")
        else:
            try:
                cred = credentials.Certificate("firebase-adminsdk.json")
                firebase_admin.initialize_app(cred, {'databaseURL': settings.FIREBASE_DATABASE_URL})
                print("[FIREBASE] Inicializado via arquivo local")
            except Exception as e:
                print(f"[FIREBASE] Erro ao inicializar: {e}")

def get_db():
    return db

def get_auth():
    return auth

init_firebase()
