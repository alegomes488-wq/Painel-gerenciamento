import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "CineCash Admin Panel"
    ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "alegomes488@gmail.com")
    FIREBASE_DATABASE_URL: str = os.environ.get("FIREBASE_DATABASE_URL", "https://playearn-b001b-default-rtdb.firebaseio.com")
    FIREBASE_SERVICE_ACCOUNT: str = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    ASAAS_API_KEY: str = os.environ.get("ASAAS_API_KEY")
    WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET")
    N8N_SHARED_SECRET: str = os.environ.get("N8N_SHARED_SECRET")
    MONITOR_SHARED_SECRET: str = os.environ.get("MONITOR_SHARED_SECRET")
    APP_ENV: str = os.environ.get("APP_ENV", "development").strip().lower()
    PAYMENTS_MODE: str = os.environ.get("PAYMENTS_MODE", "simulation").strip().lower()
    CORS_ALLOWED_ORIGINS: tuple = tuple(
        origin.strip()
        for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    )
    ADMIN_PORT: int = int(os.environ.get("ADMIN_PORT", 7861))

    @property
    def real_payments_enabled(self) -> bool:
        """Real transfers require two explicit production settings."""
        return self.APP_ENV == "production" and self.PAYMENTS_MODE == "production"

settings = Settings()
