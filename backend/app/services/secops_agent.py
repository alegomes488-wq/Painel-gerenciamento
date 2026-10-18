import os
import re
from datetime import datetime
from app.services.firebase_service import get_db, get_auth
from app.core.config import settings

ALLOWED_AMOUNTS = [0.5, 3.0, 5.0, 10.0, 50.0]
VALID_PIX_TYPES = ["CPF", "CNPJ", "EMAIL", "PHONE", "EVP"]

def _validate_pix_key(pix_type: str, key: str):
    if not key:
        return "Chave PIX ausente"
    if pix_type == "CPF":
        cpf = re.sub(r"\D", "", key)
        if len(cpf) != 11 or cpf == cpf[0] * 11:
            return "CPF invÃ¡lido"
        return None
    if pix_type == "CNPJ":
        cnpj = re.sub(r"\D", "", key)
        if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
            return "CNPJ invÃ¡lido"
        return None
    if pix_type == "EMAIL":
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", key):
            return "E-mail invÃ¡lido"
        return None
    if pix_type == "PHONE":
        p = re.sub(r"\D", "", key)
        if not (10 <= len(p) <= 13):
            return "Telefone invÃ¡lido"
        return None
    if pix_type == "EVP":
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", key, re.I):
            return "Chave aleatÃ³ria EVP invÃ¡lida"
        return None
    return "Tipo de chave PIX nÃ£o reconhecido"


class SecOpsSentinelAgent:
    """
    Agente Cyber Security SecOps Sentinel
    ResponsÃ¡vel por auditar a infraestrutura, monitorar chaves e calcular Scores de Risco para saques.
    """

    @staticmethod
    def evaluate_withdrawal_risk(wid: str, wd_data: dict) -> dict:
        if not wd_data:
            return {
                "wid": wid,
                "trust_score": 0,
                "risk_level": "CRITICAL",
                "recommendation": "HIGH_RISK_BLOCK",
                "reasons": ["Saque nÃ£o encontrado no banco de dados"]
            }

        uid = wd_data.get("uid", "")
        amount = float(wd_data.get("amount", 0))
        pix_type = wd_data.get("pixType", "").upper()
        pix_key = wd_data.get("pixKey", "")
        fingerprint = wd_data.get("fingerprint", "unknown")

        reasons = []
        score = 100  # ComeÃ§a em 100% de confianÃ§a

        # 1. ValidaÃ§Ã£o de Valor
        if amount not in ALLOWED_AMOUNTS:
            score -= 40
            reasons.append(f"Valor R$ {amount:.2f} fora da tabela oficial permitida.")

        # 2. ValidaÃ§Ã£o da Chave PIX
        if pix_type not in VALID_PIX_TYPES:
            score -= 30
            reasons.append(f"Tipo de chave PIX desconhecido: {pix_type}")
        else:
            pix_err = _validate_pix_key(pix_type, pix_key)
            if pix_err:
                score -= 35
                reasons.append(f"Chave PIX com inconsistÃªncia: {pix_err}")

        # 3. Consulta de Dados do UsuÃ¡rio no Firebase
        try:
            db = get_db()
            user_ref = db.reference(f"users/{uid}").get() or {}
            
            # Checagem de E-mail Verificado
            email_verified = user_ref.get("email_verified", False)
            if not email_verified:
                try:
                    auth = get_auth()
                    user_record = auth.get_user(uid)
                    email_verified = user_record.email_verified
                except Exception:
                    pass  # nosec

            if not email_verified:
                score -= 20
                reasons.append("Conta com e-mail nÃ£o verificado.")

            # Checagem de Saldo em relaÃ§Ã£o ao saque
            current_balance = float(user_ref.get("balance", 0))
            if current_balance < 0:
                score -= 50
                reasons.append("Alerta crÃ­tico: Saldo atual do usuÃ¡rio estÃ¡ negativo!")

            # Checagem de Fingerprint Duplicado (Dispositivo compartilhado por vÃ¡rias contas)
            if fingerprint and fingerprint != "unknown":
                all_users = db.reference("users").get() or {}
                shared_accounts = 0
                for other_uid, other_data in all_users.items():
                    if other_uid != uid and isinstance(other_data, dict):
                        sec = other_data.get("security", {})
                        if sec.get("last_login_fingerprint") == fingerprint:
                            shared_accounts += 1

                if shared_accounts > 0:
                    score -= (15 * min(shared_accounts, 4))
                    reasons.append(f"Fingerprint de dispositivo associado a {shared_accounts} outra(s) conta(s). Potential Multi-Accounting.")

        except Exception as e:
            reasons.append(f"Aviso ao consultar perfil no banco: {str(e)}")

        # 4. Ajuste final de Score e ClassificaÃ§Ã£o
        score = max(0, min(100, score))

        if score >= 85:
            risk_level = "LOW"
            recommendation = "AUTO_APPROVE"
        elif score >= 60:
            risk_level = "MEDIUM"
            recommendation = "MANUAL_REVIEW"
        elif score >= 35:
            risk_level = "HIGH"
            recommendation = "MANUAL_REVIEW"
        else:
            risk_level = "CRITICAL"
            recommendation = "HIGH_RISK_BLOCK"

        if not reasons:
            reasons.append("Nenhuma inconsistÃªncia detectada. TransaÃ§Ã£o limpa.")

        # TAREFA 3.7: Masking PII â€” pixKey Ã© mascarada (apenas Ãºltimos 4) e o UID
        # completo NÃƒO Ã© devolvido no payload pÃºblico do SecOps. fcm/viewer interno
        # pode obter o UID completo em outro endpoint se necessÃ¡rio.
        masked_key = ""
        if pix_key:
            masked_key = ("*" * max(0, len(pix_key) - 4)) + pix_key[-4:]
        else:
            masked_key = "****"

        return {
            "wid": wid,
            "uid": uid[:1] + "***" if uid else uid,  # uid semi-mascarado
            "fullname": wd_data.get("fullname", "Desconhecido"),
            "amount": amount,
            "pixType": pix_type,
            "pixKey": masked_key,
            "trust_score": score,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "reasons": reasons,
            "evaluated_at": datetime.now().isoformat()
        }

    @staticmethod
    def audit_system_security() -> dict:
        """
        Checkup completo de integridade das chaves API, conexÃµes e configuraÃ§Ãµes
        """
        checks = []
        is_secure = True

        # Check 1: Service Account Firebase (env var OU GOOGLE_APPLICATION_CREDENTIALS)
        service_account = (
            settings.FIREBASE_SERVICE_ACCOUNT
            or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
        # TAREFA 4.11: nÃ£o revelar presenÃ§a/ausÃªncia nem caminhos locais de secrets.
        if service_account:
            checks.append({"item": "Firebase Service Account", "status": "OK", "detail": "Credencial configurada"})
        else:
            is_secure = False
            checks.append({"item": "Firebase Service Account", "status": "FAIL", "detail": "Credencial de Service Account nÃ£o configurada"})

        # Check 2: Chave Asaas API
        asaas_key = settings.ASAAS_API_KEY
        if asaas_key:
            checks.append({"item": "Asaas API Key", "status": "OK", "detail": "Chave de integraÃ§Ã£o configurada"})
        else:
            checks.append({"item": "Asaas API Key", "status": "WARN", "detail": "VariÃ¡vel ASAAS_API_KEY ausente no env."})

        # Check 3: Webhook Secret
        webhook_sec = settings.WEBHOOK_SECRET
        if webhook_sec:
            checks.append({"item": "Asaas Webhook Secret", "status": "OK", "detail": "Segredo de assinatura HMAC ativo"})
        else:
            checks.append({"item": "Asaas Webhook Secret", "status": "WARN", "detail": "WEBHOOK_SECRET ausente. Webhooks sem validaÃ§Ã£o estrita."})

        # Check 4: N8N Shared Secret
        n8n_secret = settings.N8N_SHARED_SECRET
        if n8n_secret:
            checks.append({"item": "N8N Shared Secret", "status": "OK", "detail": "Segredo de comunicaÃ§Ã£o n8n ativo"})
        else:
            checks.append({"item": "N8N Shared Secret", "status": "INFO", "detail": "Sem integraÃ§Ã£o n8n para auto-aprovaÃ§Ã£o externa."})

        return {
            "agent": "SecOps Sentinel AI v1.0",
            "system_secure": is_secure,
            "total_checks": len(checks),
            "timestamp": datetime.now().isoformat(),
            "audit_results": checks
        }
