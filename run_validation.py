"""Gera ADMIN_TOKEN + sobe backend para validação."""
import os, sys, json, time, subprocess, threading, signal

# ── 1. Carrega .env manualmente (evita problemas de encoding) ──
def load_env_file(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

load_env_file(".env")  # root .env (tem WEBHOOK_SECRET)

# ── 2. Sobe o backend em background ──
backend_proc = subprocess.Popen(
    [sys.executable, "backend/admin_panel.py"],
    cwd=os.getcwd(),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
print(f"Backend PID: {backend_proc.pid}")
time.sleep(4)

# Verifica se subiu
import urllib.request
try:
    r = urllib.request.urlopen("http://localhost:8080/health", timeout=3)
    print("Backend UP:", r.read().decode())
except Exception as e:
    print("Backend não subiu:", e)
    backend_proc.kill()
    sys.exit(1)

# ── 3. Gera ADMIN_TOKEN via Firebase SDK ──
from firebase_admin import credentials, auth, initialize_app
from firebase_admin import db as rtdb
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

cred = credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"]))
initialize_app(cred, {"databaseURL": os.environ["FIREBASE_DATABASE_URL"]})

ADMIN_UID = "admin-validation"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "alegomes488@gmail.com")

# Seta claim admin (temporário) +allowlist
auth.set_custom_user_claims(ADMIN_UID, {"admin": True})
rtdb.reference(f"system/admin_uids/{ADMIN_UID}").set(True)

# Gera custom token para obter ID token
custom_token = auth.create_custom_token(ADMIN_UID)
# Troca custom token por ID token via REST API
import requests as req
resp = req.post(
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={os.environ.get('FIREBASE_API_KEY', 'AIzaSyDBa-yJArg3bkz9ouwqlNmPXKj_pTsl_1E')}",
    json={"token": custom_token.decode(), "returnSecureToken": True},
    timeout=10,
)
if resp.status_code != 200:
    print("Erro ao gerar ID token:", resp.status_code, resp.text)
    backend_proc.kill()
    sys.exit(1)

id_token = resp.json()["idToken"]
print(f"\nADMIN_TOKEN gerado: {id_token[:40]}...")
print(f"WEBHOOK_SECRET: {os.environ.get('WEBHOOK_SECRET', '')}")
print(f"N8N_SECRET: {os.environ.get('N8N_SHARED_SECRET', '')}")

# ── 4. Roda o validador ──
import subprocess as sp
result = sp.run([
    sys.executable, "validate_cybercore.py",
    "--backend-url", "http://localhost:8080",
    "--admin-token", id_token,
    "--webhook-secret", os.environ.get("WEBHOOK_SECRET", ""),
    "--n8n-secret", os.environ.get("N8N_SHARED_SECRET", ""),
], capture_output=False, text=True, cwd=os.getcwd())

# ── 5. Limpa ──
try:
    auth.revoke_refresh_tokens(ADMIN_UID)
except:
    pass
rtdb.reference(f"system/admin_uids/{ADMIN_UID}").delete()
backend_proc.terminate()
backend_proc.wait(timeout=5)
print("\nBackend encerrado. Limpeza concluída.")
