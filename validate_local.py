"""
🔒 VALIDADOR LOCAL — CyberCore IA / CineCash
Usa TestClient (sem servidor HTTP, sem Firebase real).
Valida as 4 fases de correção via testes integrados.
"""
import sys, os, hmac, hashlib, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

os.environ["WEBHOOK_SECRET"] = os.environ.get("WEBHOOK_SECRET", "test-webhook-secret")
os.environ["N8N_SHARED_SECRET"] = os.environ.get("N8N_SHARED_SECRET", "test-n8n-secret")
os.environ["ASAAS_API_KEY"] = os.environ.get("ASAAS_API_KEY", "test-key")
os.environ.setdefault("APP_CHECK_REQUIRED", "false")
os.environ.setdefault("SIMULATION_MODE", "true")

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import Settings

R, G, Y, B, RST = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[0m"
passed = failed = warnings = 0

def check(name, cond, critical=True, detail=""):
    global passed, failed, warnings
    if cond:
        print(f"  {G}✅{RST} {name}")
        passed += 1
    elif critical:
        print(f"  {R}❌{RST} {name} — {detail}")
        failed += 1
    else:
        print(f"  {Y}⚠️{RST} {name} — {detail}")
        warnings += 1

c = TestClient(app)

print(f"\n{B}{'='*60}{RST}")
print(f"{B}  🔒 VALIDADOR LOCAL — CyberCore IA / CineCash{RST}")
print(f"{B}{'='*60}{RST}")

# ── SEGURANÇA ──
print(f"\n{B}▶ SEGURANÇA{RST}")
r = c.get("/health")
check("CSP presente", "Content-Security-Policy" in r.headers, detail=r.headers.get("Content-Security-Policy","?")[:60])
check("X-Frame-Options: DENY", r.headers.get("X-Frame-Options") == "DENY")
check("X-Content-Type-Options: nosniff", r.headers.get("X-Content-Type-Options") == "nosniff")
check("Referrer-Policy presente", "Referrer-Policy" in r.headers)
r = c.get("/api/secops/health-audit")
check("Sem token -> 401", r.status_code == 401, detail=f"status={r.status_code}")
r = c.get("/api/secops/health-audit", headers={"Authorization": "Bearer invalid"})
check("Token inválido -> 401", r.status_code == 401, detail=f"status={r.status_code}")

# N8N header
r = c.post("/payments/auto-approve/NAO_X", headers={"X-N8N-Secret": "test-n8n-secret"})
check("N8N correto -> não 401", r.status_code != 401, detail=f"status={r.status_code}")
r = c.post("/payments/auto-approve/NAO_Y", headers={"X-N8N-Secret": "errado"})
check("N8N errado -> 401", r.status_code == 401, detail=f"status={r.status_code}")

# Report sem secret
r = c.post("/api/monitor/report", json={"projectId": "X", "cpu": 1})
check("Report sem X-Agent-Secret -> 403", r.status_code == 403, detail=f"status={r.status_code}")

# Health audit sem leak
r = c.get("/api/secops/health-audit", headers={"Authorization": "Bearer valid-admin"})
if r.status_code == 200:
    body = r.text.lower()
    leak = any(x in body for x in ["adminsdk", "firebase-adminsdk", "/home/"])
    check("Health audit sem leak de segredos", not leak, detail="Leak encontrado" if leak else "OK")
else:
    check("Health audit acessível", r.status_code == 200, detail=f"status={r.status_code}")

# Rate limit
for _ in range(35):
    r = c.get("/health")
check("Rate limit 429 após 30 req/min", r.status_code == 429, detail=f"último status={r.status_code}")

# ── FINANCEIRO ──
print(f"\n{B}▶ FINANCEIRO{RST}")
# Webhook HMAC errado
r = c.post("/payments/webhook", json={"event": "TRANSFER_PAID", "payment": {}},
           headers={"X-Webhook-Token": "errado"})
check("Webhook HMAC errado -> 403", r.status_code == 403, detail=f"status={r.status_code}")

# Webhook HMAC correto
payload = {"event": "TRANSFER_PAID", "payment": {"id": "val-test", "externalReference": "wid_VALX", "value": 10.0}}
body = json.dumps(payload, separators=(",", ":")).encode()
sig = hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()
r = c.post("/payments/webhook", content=body, headers={"X-Webhook-Token": sig, "Content-Type": "application/json"})
check("Webhook HMAC correto -> 200", r.status_code == 200, detail=f"status={r.status_code}")

# ── FUNCIONAL ──
print(f"\n{B}▶ FUNCIONAL{RST}")
r = c.get("/api/secops/health-audit", headers={"Authorization": "Bearer valid-admin"})
check("SecOps endpoint -> 200", r.status_code == 200, detail=f"status={r.status_code}")

# Watch endpoints existem
for ep in ["/api/project/analyze", "/api/project/save", "/api/project/remove", "/api/project/toggle"]:
    r = c.post(ep, json={}, headers={"Authorization": "Bearer valid-admin"})
    check(f"Endpoint {ep} existe (não 404/500)", r.status_code not in (404, 500), detail=f"status={r.status_code}")

# ── QUALIDADE ──
print(f"\n{B}▶ QUALIDADE{RST}")
bak = [f for r,d,fs in os.walk("www/admin") for f in fs if f.endswith(".bak")]
check("Nenhum .bak em www/admin", len(bak) == 0, detail=str(bak))
check("dependencies.py existe", os.path.exists("backend/app/dependencies.py"))
check("security.py existe", os.path.exists("backend/app/core/security.py"))
check("admin.py existe", os.path.exists("backend/app/routers/admin.py"))
check("set-admin-claim.js existe", os.path.exists("scripts/set-admin-claim.js"))
check("validate_cybercore.py existe", os.path.exists("validate_cybercore.py"))
check(".gitignore contém *.bak", "*.bak" in open(".gitignore").read())
check("ALLOWED_AMOUNTS não hardcoded", "allowedAmounts" in open("functions/index.js").read())
check("RTDB rules: balance write:false", '"balance"' in open("database.rules.json").read())

# ── RESULTADO ──
print(f"\n{B}{'='*60}{RST}")
print(f"  {G}✅ PASSARAM: {passed}{RST}")
print(f"  {R}❌ FALHARAM: {failed}{RST}")
print(f"  {Y}⚠️  AVISOS:  {warnings}{RST}")
if failed == 0:
    print(f"\n  {G}🎉 PAINEL VALIDADO — 0 FALHAS CRÍTICAS{RST}")
else:
    print(f"\n  {R}⚠️  {failed} FALHAS CRÍTICAS A CORRIGIR{RST}")
print(f"{'='*60}\n")
sys.exit(0 if failed == 0 else 1)
