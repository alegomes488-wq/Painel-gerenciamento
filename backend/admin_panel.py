import uvicorn
import os
import sys

# Adiciona o diretório atual ao path para permitir importações do app/
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.core.config import settings

if __name__ == "__main__":
    print(f"[SYSTEM] Iniciando Painel Admin na porta {settings.ADMIN_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=settings.ADMIN_PORT)
