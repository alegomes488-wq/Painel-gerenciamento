import os
from fastapi import FastAPI, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings
from app.services.firebase_service import get_auth
from app.middleware.appcheck import AppCheckMiddleware
from app.routers import payments, secops, projects

app = FastAPI(title=settings.PROJECT_NAME)

_cors_origins = settings.ALLOWED_ORIGINS or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=(_cors_origins != ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADMIN_DIR = os.path.join(PROJECT_ROOT, "www", "admin")

PUBLIC_ROUTES = {"/health", "/", "/docs", "/openapi.json", "/favicon.ico", "/favicon.svg"}

@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    path = request.url.path

    # ✅ CORREÇÃO 1: Ignorar Preflight CORS (OPTIONS)
    # O navegador envia OPTIONS antes do POST real. Sem essa linha,
    # o middleware rejeita com 401 (OPTIONS não tem header Authorization).
    if request.method == "OPTIONS":
        return await call_next(request)

    # Ignorar rotas públicas e webhooks
    if not path.startswith(("/api/", "/payments/")) or path in PUBLIC_ROUTES:
        return await call_next(request)

    # Excluir rotas específicas que não exigem o header de admin
    if path in ("/payments/webhook", "/api/monitor/report") or path.startswith(("/api/auto-approve/", "/payments/auto-approve/")):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Token não fornecido"})

    token = auth_header.split(" ", 1)[1]
    try:
        firebase_auth = get_auth()
        # Validação do ID Token
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        user_uid = decoded.get("uid", "")
        user_email = decoded.get("email", "")

        # ✅ CORREÇÃO 2: Admin por claim OU e-mail (fallback para primeiro login)
        # A rota /api/auth/refresh-admin-claim precisa ser acessível para o admin
        # se auto-promover, mesmo antes do claim estar no token.
        is_admin = bool(decoded.get("admin", False)) or (user_email == settings.ADMIN_EMAIL)

        if is_admin:
            request.state.user_uid = user_uid
            request.state.user_admin = True
        else:
            return JSONResponse(status_code=403, content={"detail": "Acesso administrativo exigido"})

    except Exception as e:
        print(f"[AUTH ERROR] {str(e)}")  # Log para debug no terminal
        return JSONResponse(status_code=401, content={"detail": f"Token inválido: {str(e)}"})

    return await call_next(request)

@app.get("/health")
async def health():
    from datetime import datetime
    return {"status": "online", "server": "admin-panel", "timestamp": datetime.now().isoformat()}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file_path = os.path.join(ADMIN_DIR, "favicon.svg")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

app.include_router(payments.router)
app.include_router(secops.router)
app.include_router(projects.router)


# Alias de compatibilidade: o workflow N8N deployed chama /api/auto-approve/{wid}
# (rota canônica é /payments/auto-approve/{wid}).
@app.post("/api/auto-approve/{wid}")
async def api_auto_approve_alias(wid: str, request: Request):
    return await payments.auto_approve_withdrawal(wid, request)


@app.post("/api/auth/refresh-admin-claim")
async def refresh_admin_claim(request: Request):
    # Path /api/ já é protegido pelo middleware (claim admin ou e-mail ADMIN_EMAIL).
    # Re-set do custom claim admin para as Security Rules (auth.token.admin), que não
    # são propagadas automaticamente se o claim nunca foi gravado.
    uid = getattr(request.state, "user_uid", "")
    if not uid:
        return JSONResponse(status_code=401, content={"detail": "Não autenticado"})
    try:
        get_auth().set_custom_user_claims(uid, {"admin": True})
        return {"status": "success", "message": "Claim admin atualizado"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro ao atualizar claim: {e}"})

# Mount frontend
if os.path.exists(ADMIN_DIR):
    app.mount("/", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")

# App Check enforcement (APP_CHECK_REQUIRED=false por padrão — não quebra o fluxo
# atual). Adicionado por último para rodar PRIMEIRO (Starlette: o último add_middleware
# é o mais externo). Ver app/middleware/appcheck.py.
app.add_middleware(AppCheckMiddleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.ADMIN_PORT)
