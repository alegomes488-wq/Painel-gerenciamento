FROM python:3.10-slim

WORKDIR /app

# Instalar dependências primeiro (cache)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o projeto
COPY . .

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Backend modular em backend/app; www/admin servido a partir de /app/www/admin
WORKDIR /app/backend

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '7860') + '/health', timeout=3).read()" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
