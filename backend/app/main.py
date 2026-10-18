import os
from fastapi import FastAPI, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from app.core.config import settings
from app.services.firebase_service import get_auth
from app.middleware.appcheck import AppCheckMiddleware
from app.dependencies import is_admin_user, get_current_user, log_admin_action
from app.routers import payments, secops, projects, admin, telemetry
from app.routers.projects import project_router
from app.core.security import rate_limiter
# TAREFA 6.1: guarda de entrega de arquivos estáticos (bloqueia dotfiles e
# a cópia do backend que estava dentro de www/admin/). Ver core/static_guard.py.
from app.core.static_guard import GuardedStaticFiles

app = FastAPI(title=settings.PROJECT_NAME)


@app.on_event("startup")
async def _start_telemetry_worker():
    from app.services.telemetry_worker import start_telemetry_worker
    await start_telemetry_worker()


@app.on_event("shutdown")
async def _stop_telemetry_worker():
    from app.services.telemetry_worker import stop_telemetry_worker
    await stop_telemetry_worker()

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
async def rate_limit_middleware(request: Request, call_next):
    # TAREFA 2.5: limita requisições por IP (exceto estáticos e docs)
    path = request.url.path
    if not (path.startswith("/api/") or path.startswith("/payments/") or path == "/health"):
        return await call_next(request)
    if not rate_limiter.check(request):
        return JSONResponse(status_code=429, content={"detail": "Muitas requisições. Tente novamente em 1 minuto."})
    return await call_next(request)


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
    if path in ("/payments/webhook", "/api/monitor/report", "/api/telemetry/stream") or path.startswith(("/api/auto-approve/", "/payments/auto-approve/")):
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

        # ✅ TAREFA 2.1: Admin por allowlist de UID (fonte principal) OU claim
        # OU e-mail (fallback temporário). A allowlist vive em /system/admin_uids.
        is_admin = is_admin_user(user_uid, decoded)

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
    # TAREFA 3.3: expõe o modo de simulação para o frontend exibir banner
    return {
        "status": "online",
        "server": "admin-panel",
        "simulation": settings.SIMULATION_MODE,
        "timestamp": datetime.now().isoformat(),
    }

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file_path = os.path.join(ADMIN_DIR, "favicon.svg")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

app.include_router(payments.router)
app.include_router(secops.router)
app.include_router(projects.router)
app.include_router(admin.router)
app.include_router(telemetry.router)
app.include_router(project_router)


# Alias de compatibilidade: o workflow N8N deployed chama /api/auto-approve/{wid}
# (rota canônica é /payments/auto-approve/{wid}).
@app.post("/api/auto-approve/{wid}")
async def api_auto_approve_alias(wid: str, request: Request):
    return await payments.auto_approve_withdrawal(wid, request)


@app.post("/api/auth/refresh-admin-claim")
async def refresh_admin_claim(request: Request):
    # Caminho /api/ já é protegido pelo middleware (is_admin_user: claim OU allowlist OU e-mail).
    # TAREFA 2.1: o claim admin SÓ é (re)confirmado se o UID estiver na allowlist de
    # /system/admin_uids OU (fallback) for o ADMIN_EMAIL. UIDs fora da allowlist
    # nunca recebem claim admin permanente — apenas tentativa de primeiro login natural.
    import datetime
    try:
        decoded = get_current_user(request)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"detail": str(e)})

    uid = decoded.get("uid", "")
    if not uid:
        return JSONResponse(status_code=401, content={"detail": "Não autenticado"})

    from app.dependencies import is_admin_user
    # Garante consistência: só seta claim se o usuário for admin pela fonte de verdade
    if not is_admin_user(uid, decoded):
        return JSONResponse(status_code=403, content={"detail": "UID fora da allowlist de admin"})

    # Claim temporária com expiração (padrão 24h) — admin_until como UNIX timestamp
    admin_exp = int((datetime.datetime.utcnow() + datetime.timedelta(hours=24)).timestamp())
    try:
        get_auth().set_custom_user_claims(uid, {"admin": True, "admin_until": admin_exp})
        # Log de auditoria da promoção
        log_admin_action(uid, "refresh_admin_claim", {
            "target_uid": uid,
            "admin_until": admin_exp
        })
        return {"status": "success", "message": "Claim admin atualizado", "admin_until": admin_exp}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Erro ao atualizar claim: {e}"})

# Mount frontend
# TAREFA 6.1: GuardedStaticFiles em vez de StaticFiles puro.
# `www/admin/` é a raiz estática do painel E contém uma cópia do backend
# (`www/admin/backend/`) com `.env` e `firebase-adminsdk.json`. Com StaticFiles
# puro, `GET /backend/.env` e `GET /backend/firebase-adminsdk.json` devolviam
# HTTP 200 com credenciais reais — medido em `_verify_static_exposure.py`.
# A guarda recusa dotfiles e a subárvore `backend`; ver core/static_guard.py.
if os.path.exists(ADMIN_DIR):
    app.mount("/", GuardedStaticFiles(directory=ADMIN_DIR, html=True), name="admin")

# TAREFA 2.8: Injeção de cabeçalhos de segurança.
# Registrado por ÚLTIMO -> em Starlette o último @app.middleware é o mais EXTERNO,
# então envolve inclusive respostas de erro dos middlewares internos (401/403/429).
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    
    csp = (
        "default-src 'self'; "
        "script-src 'self' https://*.gstatic.com https://*.google.com https://*.googleapis.com https://cdn.jsdelivr.net https://www.googletagmanager.com https://apis.google.com https://*.firebaseio.com 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' http://localhost:7861 https://localhost:7861 https://*.googleapis.com https://*.google.com https://www.gstatic.com https://cdn.jsdelivr.net https://*.firebaseio.com wss://*.firebaseio.com https://*.firebaseapp.com wss://*.firebaseapp.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com; "
        "img-src 'self' data: https: blob:; "
        "frame-src https://*.google.com https://*.firebaseapp.com; "
        "worker-src 'self' blob:;"
    )
    
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    return response
    # CSP permitindo apenas origens usadas pelo painel (Firebase/CDN/fontes Google)
    
   

# App Check enforcement (APP_CHECK_REQUIRED=false por padrão — não quebra o fluxo
# atual). Adicionado por último para rodar PRIMEIRO (Starlette: o último add_middleware
# é o mais externo). Ver app/middleware/appcheck.py.
app.add_middleware(AppCheckMiddleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.ADMIN_PORT)  # nosec B104
