import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# TAREFA 4.2: Validação de schema de env vars no startup.
# Levanta RuntimeError com mensagem clara se essencial faltar.
# ─────────────────────────────────────────────────────────────

def _validate_env():
    missing = []
    simulation = os.environ.get("SIMULATION_MODE", "true").lower() in ("1", "true", "yes")
    appcheck_on = os.environ.get("APP_CHECK_REQUIRED", "true").lower() in ("1", "true", "yes")

    # Service Account do Firebase é obrigatória quando o App Check está ativo,
    # pois sem ela não há credencial para validar tokens no backend.
    if appcheck_on:
        has_sa = bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT")) or \
                 bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")) or \
                 os.path.exists("firebase-adminsdk.json")
        if not has_sa:
            missing.append("FIREBASE_SERVICE_ACCOUNT (necessária com APP_CHECK_REQUIRED=true)")

    # Webhook secret essencial (fail-closed no webhook Asaas)
    if not os.environ.get("WEBHOOK_SECRET"):
        missing.append("WEBHOOK_SECRET")

    # Modo produção: Asaas key obrigatória a menos que SIMULATION_MODE=true
    if not simulation and not os.environ.get("ASAAS_API_KEY"):
        missing.append("ASAAS_API_KEY (necessária fora do modo simulação)")

    # ALLOWED_ORIGINS não pode ser * em produção
    allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if allowed_origins == ["*"] and not simulation:
        missing.append("ALLOWED_ORIGINS não pode ser ['*'] em produção")

    if missing:
        raise RuntimeError(
            "Configuração incompleta. Corrija antes de subir:\n  - " + "\n  - ".join(missing)
        )

_validate_env()

class Settings:
    PROJECT_NAME: str = "CineCash Admin Panel"
    ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "alegomes488@gmail.com")
    FIREBASE_DATABASE_URL: str = os.environ.get("FIREBASE_DATABASE_URL", "https://playearn-b001b-default-rtdb.firebaseio.com")
    FIREBASE_SERVICE_ACCOUNT: str = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    # TODO 1.9: Após rotacionar a credencial de Service Account no Console Firebase
    # (Configurações do Projeto -> Contas de Serviço -> gerar nova chave), configure a
    # NOVA chave aqui via env var FIREBASE_SERVICE_ACCOUNT. NUNCA versione o .json.
    # Para iniciar o backend usando o arquivo local, defina:
    #   $env:FIREBASE_SERVICE_ACCOUNT = "{\"...conteúdo do json...\"}"
    # ou use GOOGLE_APPLICATION_CREDENTIALS apontando para o novo arquivo.
    ASAAS_API_KEY: str = os.environ.get("ASAAS_API_KEY")
    # TAREFA 3.3: Modo de simulação explícito. Quando SIMULATION_MODE=true, o backend
    # NUNCA chama a API real do Asaas — gera transfer_id simulado prefixado com SIM_.
    # Em produção, defina SIMULATION_MODE=false + ASAAS_API_KEY real.
    SIMULATION_MODE: bool = os.environ.get("SIMULATION_MODE", "true").lower() in ("1", "true", "yes")
    WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET")
    N8N_SHARED_SECRET: str = os.environ.get("N8N_SHARED_SECRET")
    ADMIN_PORT: int = int(os.environ.get("BACKEND_PORT", os.environ.get("ADMIN_PORT", 7861)))
    ALLOWED_ORIGINS: list = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

settings = Settings()
