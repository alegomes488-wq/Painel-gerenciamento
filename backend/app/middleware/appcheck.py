"""Middleware de App Check enforcement (backend FastAPI).

O SDK Python do firebase-admin (7.4.0) NÃO possui app_check.verify_token()
(só o Node.js tem). A validação real é feita via REST:
    POST https://appcheck.googleapis.com/v1/projects/{project}/apps/{app}:verifyToken

Desativado por padrão (APP_CHECK_REQUIRED=false) para não quebrar o fluxo atual —
o frontend ainda não envia X-Firebase-AppCheck. Só ative após o frontend passar a
enviar o token (wrapper central de fetch).
"""
import os
import json
import logging

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

APP_CHECK_SCOPES = ["https://www.googleapis.com/auth/firebase"]
VERIFY_URL = (
    "https://appcheck.googleapis.com/v1/projects/{project_id}/apps/{app_id}:verifyToken"
)

# Rotas que nunca exigem App Check (públicas por design ou já excluídas da auth)
EXCLUDED_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    "/favicon.svg",
}
EXCLUDED_PREFIXES = (
    "/payments/webhook",
    "/api/monitor/report",
    "/payments/auto-approve/",
    "/api/auto-approve/",
)


class AppCheckMiddleware(BaseHTTPMiddleware):
    """Valida X-Firebase-AppCheck nas rotas de API quando APP_CHECK_REQUIRED=true."""

    def __init__(self, app):
        super().__init__(app)
        self.required = os.getenv("APP_CHECK_REQUIRED", "false").lower() == "true"
        self.project_id = os.getenv("FIREBASE_PROJECT_ID") or self._project_id_from_sa()
        self.app_id = os.getenv("FIREBASE_APP_ID")
        self.credentials = None
        self._init_credentials()

        if not self.required:
            logger.warning(
                "[AppCheck] Enforcement DESATIVADO (APP_CHECK_REQUIRED=false). "
                "O backend aceita requisições sem validação de App Check."
            )
        else:
            logger.info(
                "[AppCheck] Enforcement ATIVADO — "
                f"project_id={self.project_id} app_id={self.app_id}"
            )

    def _sa_dict(self):
        raw = os.getenv("FIREBASE_SERVICE_ACCOUNT") or os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_JSON", ""
        )
        if raw:
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                pass
        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _project_id_from_sa(self):
        return self._sa_dict().get("project_id")

    def _init_credentials(self):
        try:
            sa = self._sa_dict()
            if sa:
                self.credentials = service_account.Credentials.from_service_account_info(
                    sa, scopes=APP_CHECK_SCOPES
                )
            else:
                self.credentials = None
                logger.error(
                    "[AppCheck] Falha ao carregar service account: "
                    "nenhum JSON encontrado (FIREBASE_SERVICE_ACCOUNT / "
                    "GOOGLE_APPLICATION_CREDENTIALS)"
                )
        except Exception as e:
            logger.error(f"[AppCheck] Falha ao carregar service account: {e}")
            self.credentials = None

    def _refresh_token(self):
        if not self.credentials:
            return None
        try:
            if not self.credentials.valid:
                self.credentials.refresh(GoogleAuthRequest())
            return self.credentials.token
        except Exception as e:
            logger.error(f"[AppCheck] Falha ao obter access token: {e}")
            return None

    def _verify_appcheck_token(self, token: str) -> bool | None:
        """Valida o token. True=ok, False=token inválido, None=serviço indisponível."""
        if not self.project_id or not self.app_id:
            logger.error("[AppCheck] FIREBASE_PROJECT_ID ou FIREBASE_APP_ID não configurados")
            return False

        access_token = self._refresh_token()
        if not access_token:
            logger.error("[AppCheck] Não foi possível obter access token da service account")
            return False

        url = VERIFY_URL.format(project_id=self.project_id, app_id=self.app_id)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        try:
            resp = httpx.post(url, headers=headers, json={"token": token}, timeout=5)
        except httpx.HTTPError as e:
            logger.error(f"[AppCheck] Erro de rede na validação: {e}")
            return None

        if resp.status_code == 200:
            logger.info("[AppCheck] Token validado com sucesso")
            return True
        if resp.status_code in (400, 401, 403):
            logger.warning(f"[AppCheck] Token inválido: {resp.status_code} - {resp.text[:200]}")
            return False
        logger.error(f"[AppCheck] Erro inesperado da API: {resp.status_code} - {resp.text[:200]}")
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Preflight CORS e rotas excluídas nunca exigem App Check
        if method == "OPTIONS":
            return await call_next(request)
        if path in EXCLUDED_PATHS or path.startswith(EXCLUDED_PREFIXES):
            return await call_next(request)

        # Só protege rotas de API/pagamentos (o frontend estático em / não é bloqueado)
        if not (path.startswith("/api/") or path.startswith("/payments/")):
            return await call_next(request)

        if not self.required:
            logger.debug("[AppCheck] Enforcement desativado — requisição sem validação")
            return await call_next(request)

        appcheck_token = request.headers.get("X-Firebase-AppCheck")
        if not appcheck_token:
            logger.warning(f"[AppCheck] Requisição {method} {path} rejeitada: header ausente")
            return JSONResponse(status_code=401, content={"detail": "X-Firebase-AppCheck header required"})

        result = self._verify_appcheck_token(appcheck_token)
        if result is None:
            return JSONResponse(status_code=503, content={"detail": "Serviço de validação indisponível"})
        if not result:
            return JSONResponse(status_code=401, content={"detail": "App Check token invalid"})

        return await call_next(request)
