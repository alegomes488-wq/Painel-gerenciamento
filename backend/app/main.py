import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings
from app.services.firebase_service import get_auth
from app.routers import payments, secops, projects

app = FastAPI(title=settings.PROJECT_NAME)

print(
    f"[CONFIG] APP_ENV={settings.APP_ENV!r} PAYMENTS_MODE={settings.PAYMENTS_MODE!r} "
    f"real_payments_enabled={settings.real_payments_enabled} "
    f"asaas_key_present={bool(settings.ASAAS_API_KEY)} "
    f"webhook_secret_present={bool(settings.WEBHOOK_SECRET)}"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ALLOWED_ORIGINS),
    allow_origin_regex=(
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
        if settings.APP_ENV != "production" else None
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADMIN_DIR = os.path.join(PROJECT_ROOT, "www", "admin")

PUBLIC_ROUTES = {"/health", "/", "/docs", "/openapi.json", "/favicon.ico", "/favicon.svg"}

@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    # CORS preflights never carry Firebase credentials. Let CORSMiddleware
    # validate and answer them before applying route authentication.
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not path.startswith(("/api/", "/payments/")) or path in PUBLIC_ROUTES:
        return await call_next(request)

    if path in ("/payments/webhook", "/api/monitor/report") or path.startswith(("/api/auto-approve/", "/payments/auto-approve/")):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Token não fornecido"})

    token = auth_header.split(" ", 1)[1]
    try:
        firebase_auth = get_auth()
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        user_uid = decoded.get("uid", "")
        user_data = firebase_auth.get_user(user_uid)
        if user_data.email != settings.ADMIN_EMAIL:
            return JSONResponse(status_code=403, content={"detail": "Acesso administrativo exigido"})
        request.state.user_uid = user_uid
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Token inválido"})

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

# Mount frontend
if os.path.exists(ADMIN_DIR):
    app.mount("/", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.ADMIN_PORT)
