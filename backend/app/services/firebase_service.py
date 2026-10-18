import json
import os
import firebase_admin
from firebase_admin import credentials, db, auth
from app.core.config import settings


def _load_service_account_dict() -> dict:
    """Tenta obter o dict da Service Account com tolerância a JSON vazio/corrompido.

    Ordem:
      1) FIREBASE_SERVICE_ACCOUNT (env var) — se for JSON válido, usa;
      2) GOOGLE_APPLICATION_CREDENTIALS (path p/ arquivo) — se existir;
      3) firebase-adminsdk.json local (dev).
    """
    raw = settings.FIREBASE_SERVICE_ACCOUNT
    if raw:
        # Só usamos env var se for um JSON parseável; senão cai no próximo fallback
        # (evita JSONDecodeError no boot com valor vazio/corrompido no .env).
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("private_key"):
                return parsed
        except (ValueError, TypeError):
            pass

    for path in (os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""), "firebase-adminsdk.json"):
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                if isinstance(parsed, dict) and parsed.get("private_key"):
                    return parsed
            except (ValueError, TypeError, OSError):
                pass
    return {}


def init_firebase():
    if not firebase_admin._apps:
        cred_dict = _load_service_account_dict()
        try:
            if cred_dict:
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'databaseURL': settings.FIREBASE_DATABASE_URL})
                print("[FIREBASE] Inicializado via Service Account")
            else:
                # Dev/rodapé: permite inicializar sem credenciais para testes locais
                firebase_admin.initialize_app(options={'databaseURL': settings.FIREBASE_DATABASE_URL})
                print("[FIREBASE] Inicializado SEM credenciais (modo dev — RTDB restrito)")
        except Exception as e:
            print(f"[FIREBASE] Erro ao inicializar: {e}")

def get_db():
    return db

def get_auth():
    return auth

init_firebase()
