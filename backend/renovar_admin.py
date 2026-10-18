#!/usr/bin/env python3
import sys, os, json, time
from pathlib import Path

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import firebase_admin
from firebase_admin import credentials, auth

if not firebase_admin._apps:
    cred = None
    # 1) Prefere o arquivo local: versao do .env pode estar desatualizada (key rotacionada).
    for p in [
        Path(__file__).parent / "firebase-adminsdk.json",
        Path(__file__).parent / "serviceAccountKey.json",
    ]:
        if p.exists():
            try:
                cred = credentials.Certificate(str(p))
                break
            except Exception:
                cred = None
    # 2) Fallback: GOOGLE_APPLICATION_CREDENTIALS
    if cred is None:
        gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        for p in ([gac] if gac else []):
            if p and Path(p).exists():
                cred = credentials.Certificate(str(p))
                break
    # 3) Fallback: env var FIREBASE_SERVICE_ACCOUNT
    if cred is None:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
        if raw:
            try:
                info = json.loads(raw)
                if info.get("private_key"):
                    cred = credentials.Certificate(info)
            except ValueError:
                pass
    if cred is None:
        sys.exit("Credencial nao encontrada. Verifique o .env ou firebase-adminsdk.json")
    firebase_admin.initialize_app(cred)

UID = "yVjmEMnlHcPgEb5kozRnJNLmHY63"
admin_until = int(time.time()) + 365 * 24 * 3600

auth.set_custom_user_claims(UID, {"admin": True, "admin_until": admin_until})
print("SUCESSO! Admin renovado ate:",
      time.strftime("%d/%m/%Y %H:%M", time.localtime(admin_until)))