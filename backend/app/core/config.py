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
    ADMIN_PORT: int = int(os.environ.get("ADMIN_PORT", 7861))

settings = Settings()
