#!/usr/bin/env python3
"""
Script standalone para definir admin claim no Firebase Auth.
Não depende da estrutura interna do projeto.
Uso: python scripts\set_admin_claim.py <UID>
"""
import sys
import os
import json
from pathlib import Path

# Carrega o .env manualmente
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))

# Agora importa o firebase_admin
import firebase_admin
from firebase_admin import credentials, auth


def initialize_firebase():
    """Inicializa o Firebase Admin SDK de forma robusta."""
    if firebase_admin._apps:
        return firebase_admin.get_app()

    # 1. Tenta FIREBASE_SERVICE_ACCOUNT do .env
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if service_account_json:
        try:
            cred_info = json.loads(service_account_json)
            if "private_key" in cred_info:
                cred = credentials.Certificate(cred_info)
                app = firebase_admin.initialize_app(cred)
                print("[FIREBASE] Inicializado via FIREBASE_SERVICE_ACCOUNT (.env)")
                return app
        except (json.JSONDecodeError, ValueError):
            print("[FIREBASE] FIREBASE_SERVICE_ACCOUNT inválido, tentando fallback...")

    # 2. Tenta GOOGLE_APPLICATION_CREDENTIALS
    gac_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if gac_path and Path(gac_path).exists():
        cred = credentials.Certificate(gac_path)
        app = firebase_admin.initialize_app(cred)
        print(f"[FIREBASE] Inicializado via GOOGLE_APPLICATION_CREDENTIALS ({gac_path})")
        return app

    # 3. Tenta arquivo serviceAccountKey.json no root
    local_key = Path(__file__).parent.parent / "serviceAccountKey.json"
    if local_key.exists():
        cred = credentials.Certificate(str(local_key))
        app = firebase_admin.initialize_app(cred)
        print("[FIREBASE] Inicializado via serviceAccountKey.json")
        return app

    raise RuntimeError(
        "Nenhuma credencial Firebase encontrada.\n"
        "Configure FIREBASE_SERVICE_ACCOUNT no .env, GOOGLE_APPLICATION_CREDENTIALS, "
        "ou coloque um serviceAccountKey.json na raiz do backend."
    )


def set_admin_claim(uid: str):
    print(f"[ADMIN CLAIM] Definindo admin=true para UID: {uid}")
    
    initialize_firebase()
    
    # Define o custom claim
    auth.set_custom_user_claims(uid, {
    "admin": True,
     "admin_until": int(time.time() * 1000)
     })
    
    # Verifica
    user = auth.get_user(uid)
    claims = user.custom_claims or {}
    
    if claims.get("admin") is True:
        print(f"✅ SUCESSO! Claim 'admin: true' definido para {uid}")
        print(f"   Email: {user.email or 'sem email'}")
        print(f"   Claims: {claims}")
        print("\n⚠️  AGORA NO FRONTEND (console do navegador):")
        print("   firebase.auth().currentUser.getIdToken(true)")
        print("   Depois recarregue a página (F5).")
    else:
        print(f"❌ FALHA! Claims atuais: {claims}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts\\set_admin_claim.py <UID>")
        sys.exit(1)
    
    uid = sys.argv[1].strip()
    set_admin_claim(uid)