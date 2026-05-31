FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY core/ ./core/
COPY tasks/ ./tasks/
COPY www/ ./www/

ENV PORT=7860
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Secrets necessários no HF Spaces:
# GROQ_API_KEY → Obrigatório para IA
# FIREBASE_SERVICE_ACCOUNT → Obrigatório para persistência

EXPOSE 7860

CMD ["python3", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
