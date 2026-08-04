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
            return "CPF inválido"
        return None
    if pix_type == "CNPJ":
        cnpj = re.sub(r"\D", "", key)
        if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
            return "CNPJ inválido"
        return None
    if pix_type == "EMAIL":
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", key):
            return "E-mail inválido"
        return None
    if pix_type == "PHONE":
        p = re.sub(r"\D", "", key)
        if not (10 <= len(p) <= 13):
            return "Telefone inválido"
        return None
    if pix_type == "EVP":
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", key, re.I):
            return "Chave aleatória EVP inválida"
        return None
    return "Tipo de chave PIX não reconhecido"


class SecOpsSentinelAgent:
    """
    Agente Cyber Security SecOps Sentinel
    Responsável por auditar a infraestrutura, monitorar chaves e calcular Scores de Risco para saques.
    """

    @staticmethod
    def evaluate_withdrawal_risk(wid: str, wd_data: dict) -> dict:
        if not wd_data:
            return {
                "wid": wid,
                "trust_score": 0,
                "risk_level": "CRITICAL",
                "recommendation": "HIGH_RISK_BLOCK",
                "reasons": ["Saque não encontrado no banco de dados"]
            }

        uid = wd_data.get("uid", "")
        amount = float(wd_data.get("amount", 0))
        pix_type = wd_data.get("pixType", "").upper()
        pix_key = wd_data.get("pixKey", "")
        fingerprint = wd_data.get("fingerprint", "unknown")

        reasons = []
        score = 100  # Começa em 100% de confiança

        # 1. Validação de Valor
        if amount not in ALLOWED_AMOUNTS:
            score -= 40
            reasons.append(f"Valor R$ {amount:.2f} fora da tabela oficial permitida.")

        # 2. Validação da Chave PIX
        if pix_type not in VALID_PIX_TYPES:
            score -= 30
            reasons.append(f"Tipo de chave PIX desconhecido: {pix_type}")
        else:
            pix_err = _validate_pix_key(pix_type, pix_key)
            if pix_err:
                score -= 35
                reasons.append(f"Chave PIX com inconsistência: {pix_err}")

        # 3. Consulta de Dados do Usuário no Firebase
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
                    pass

            if not email_verified:
                score -= 20
                reasons.append("Conta com e-mail não verificado.")

            # Checagem de Saldo em relação ao saque
            current_balance = float(user_ref.get("balance", 0))
            if current_balance < 0:
                score -= 50
                reasons.append("Alerta crítico: Saldo atual do usuário está negativo!")

            # Checagem de Fingerprint Duplicado (Dispositivo compartilhado por várias contas)
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

        # 4. Ajuste final de Score e Classificação
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
            reasons.append("Nenhuma inconsistência detectada. Transação limpa.")

        return {
            "wid": wid,
            "uid": uid,
            "fullname": wd_data.get("fullname", "Desconhecido"),
            "amount": amount,
            "pixType": pix_type,
            "pixKey": pix_key,
            "trust_score": score,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "reasons": reasons,
            "evaluated_at": datetime.now().isoformat()
        }

    @staticmethod
    def audit_system_security() -> dict:
        """
        Checkup completo de integridade das chaves API, conexões e configurações
        """
        checks = []
        is_secure = True

        # Check 1: Service Account Firebase
        service_account = settings.FIREBASE_SERVICE_ACCOUNT or os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if service_account:
            checks.append({"item": "Firebase Service Account", "status": "OK", "detail": "Configurado via variável de ambiente"})
        else:
            from app.core.config import PROJECT_ROOT
            fp = os.path.join(PROJECT_ROOT, "backend", "firebase-adminsdk.json")
            if os.path.exists(fp):
                checks.append({"item": "Firebase Service Account", "status": "WARN", "detail": "Usando arquivo local. Recomendado mover para env var."})
            else:
                is_secure = False
                checks.append({"item": "Firebase Service Account", "status": "FAIL", "detail": "Não encontrada credencial de Service Account."})

        # Check 2: Chave Asaas API
        asaas_key = settings.ASAAS_API_KEY
        if asaas_key:
            checks.append({"item": "Asaas API Key", "status": "OK", "detail": "Chave de integração configurada"})
        else:
            checks.append({"item": "Asaas API Key", "status": "WARN", "detail": "Variável ASAAS_API_KEY ausente no env."})

        # Check 3: Webhook Secret
        webhook_sec = settings.WEBHOOK_SECRET
        if webhook_sec:
            checks.append({"item": "Asaas Webhook Secret", "status": "OK", "detail": "Segredo de assinatura HMAC ativo"})
        else:
            checks.append({"item": "Asaas Webhook Secret", "status": "WARN", "detail": "WEBHOOK_SECRET ausente. Webhooks sem validação estrita."})

        # Check 4: N8N Shared Secret
        n8n_secret = settings.N8N_SHARED_SECRET
        if n8n_secret:
            checks.append({"item": "N8N Shared Secret", "status": "OK", "detail": "Segredo de comunicação n8n ativo"})
        else:
            checks.append({"item": "N8N Shared Secret", "status": "INFO", "detail": "Sem integração n8n para auto-aprovação externa."})

        return {
            "agent": "SecOps Sentinel AI v1.0",
            "system_secure": is_secure,
            "total_checks": len(checks),
            "timestamp": datetime.now().isoformat(),
            "audit_results": checks
        }
