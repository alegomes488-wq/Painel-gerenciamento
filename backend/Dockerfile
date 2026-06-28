FROM python:3.10-slim

WORKDIR /app

# Instalar dependências
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o projeto para manter a estrutura (backend e www)
COPY . .

# Mudar para a pasta do backend para rodar o app
WORKDIR /app/backend

ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Comando para rodar com Uvicorn usando a porta da variável de ambiente (comum em deploy)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
