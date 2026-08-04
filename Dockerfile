FROM python:3.10-slim

WORKDIR /app

# Instalar dependências primeiro (cache)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o projeto
COPY . .

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Backend modular em backend/app; www/admin servido a partir de /app/www/admin
WORKDIR /app/backend

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
