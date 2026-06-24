FROM python:3.11-slim

# Instala Node.js 20.x para rodar N8N
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g n8n \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY core/ ./core/
COPY tasks/ ./tasks/
COPY www/ ./www/
COPY n8n-workflows/ ./n8n-workflows/
COPY start.sh .

RUN chmod +x start.sh

ENV PORT=7860
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Secrets necessários no HF Spaces:
# GROQ_API_KEY → Obrigatório para IA
# FIREBASE_SERVICE_ACCOUNT → Obrigatório para persistência

EXPOSE 7860

CMD ["bash", "start.sh"]
