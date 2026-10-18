"""
DependÃªncias de autenticaÃ§Ã£o/autorizaÃ§Ã£o reutilizÃ¡veis â€” CyberCore IA

Centraliza:
  - validaÃ§Ã£o de Firebase ID token (get_current_user)
  - verificaÃ§Ã£o de admin por claim OU allowlist de UID (require_admin / is_admin_user)
  - gate N8N via secret timing-safe (n8n header)
  - log de aÃ§Ãµes administrativas em /logs/admin_actions

TAREFA 2.3: extraÃ§Ã£o dos blocos duplicados de main.py, payments.py, projects.py, secops.py.
"""
import hmac
import hashlib
import os
from firebase_admin import auth as firebase_auth
from app.services.firebase_service import get_db, get_auth

# Allowlist de UIDs admin no RTDB: /system/admin_uids/{uid} = true
ADMIN_ALLOWLIST_PATH = "system/admin_uids"


def _timing_safe_equal(a: str, b: str) -> bool:
    """ComparaÃ§Ã£o de strings em tempo constante."""
    a = (a or "").encode()
    b = (b or "").encode()
    return hmac.compare_digest(a, b)


def _is_uid_in_allowlist(uid: str) -> bool:
    """Checa se o UID estÃ¡ na allowlist de administradores no RTDB."""
    if not uid:
        return False
    try:
        db = get_db()
        return bool(db.reference(f"{ADMIN_ALLOWLIST_PATH}/{uid}").get())
    except Exception:
        return False


def is_admin_user(uid: str, decoded: dict = None) -> bool:
    """
    Decide se um UID Ã© administrador.

    Ordem de verdade (decoded = payload do Firebase ID token jÃ¡ verificado):
      1. claim `admin` presente E vÃ¡lido no token decodificado (expiraÃ§Ã£o via admin_until)
         â€” fonte primÃ¡ria, pois o token jÃ¡ foi validado/revogado no middleware.
      2. UID na allowlist do RTDB (/system/admin_uids/{uid})
      3. (fallback temporÃ¡rio) e-mail == settings.ADMIN_EMAIL â€” removÃ­vel apÃ³s a
         allowlist estar populada.
    """
    if not uid:
        return False

    # 1. Claim admin no prÃ³prio token decodificado (expiraÃ§Ã£o por admin_until)
    if decoded:
        if decoded.get("admin"):
            exp = decoded.get("admin_until")
            if exp is None:
                return True  # claim permanente
            import datetime
            try:
                exp_val = float(exp)
            except (TypeError, ValueError):
                return True  # expiraÃ§Ã£o malformada â€” tratar como vÃ¡lido (melhor conceder)
            if datetime.datetime.utcfromtimestamp(exp_val) > datetime.datetime.utcnow():
                return True
            # Claim `admin` EXPIRADA (admin_until no passado): NAO negar aqui.
            # Negar aqui criava deadlock: /api/auth/refresh-admin-claim tambem
            # passa por is_admin_user, entao o operador nunca conseguia renovar
            # a claim e era barrado mesmo sendo o ADMIN_EMAIL. Seguimos para a
            # allowlist (2) e o fallback de e-mail (3).

    # 2. Allowlist explÃ­cita de UIDs
    if _is_uid_in_allowlist(uid):
        return True

    # 3. Fallback temporÃ¡rio: e-mail do token (para nÃ£o quebrar o admin existente)
    #    TODO: remover apÃ³s popular a allowlist via /api/admin/ban|grant
    email = (decoded or {}).get("email", "")
    if email and email == _admin_email_fallback():
        return True

    return False


def _admin_email_fallback() -> str:
    from app.core.config import settings
    return settings.ADMIN_EMAIL


def get_current_user(request) -> dict:
    """
    Valida o Firebase ID token (check_revoked=True) e retorna o payload decodificado.
    LanÃ§a ValueError se invÃ¡lido/expirado.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise ValueError("Token nÃ£o fornecido")
    token = auth_header.split(" ", 1)[1]
    try:
        return get_auth().verify_id_token(token, check_revoked=True)
    except Exception as e:
        raise ValueError(f"Token invÃ¡lido: {e}")


def require_admin(request) -> dict:
    """
    Valida token e exige privilÃ©gio de admin (claim OU allowlist OU e-mail fallback).
    Retorna o payload decodificado se admin; sobe PermissionError caso contrÃ¡rio.
    """
    decoded = get_current_user(request)
    uid = decoded.get("uid", "")
    if not is_admin_user(uid, decoded):
        raise PermissionError("Acesso administrativo exigido")
    return decoded


def is_n8n_request(request) -> bool:
    """True se header X-N8N-Secret bate com N8N_SHARED_SECRET (timing-safe)."""
    secret = os.environ.get("N8N_SHARED_SECRET", "").strip()
    if not secret:
        return False
    provided = request.headers.get("X-N8N-Secret", "")
    return _timing_safe_equal(secret, provided)


def log_admin_action(actor_uid: str, action: str, details: dict = None) -> None:
    """
    Registra aÃ§Ã£o administrativa em /logs/admin_actions com actor, timestamp e detalhes.
    """
    try:
        db = get_db()
        db.reference("logs/admin_actions").push({
            "actor_uid": actor_uid,
            "action": action,
            **(details or {}),
            "timestamp": {".sv": "timestamp"},
        })
    except Exception:
        # Falha de log nÃ£o deve quebrar a operaÃ§Ã£o principal
        pass  # nosec
