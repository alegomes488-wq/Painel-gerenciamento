FROM python:3.11-slim

# Instala dependências de sistema para Playwright, IA e processamento gráfico
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    librandr2 \
    libgbm1 \
    libpango-1-0-0 \
    libcairo2 \
    libasound2 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip e instala requisitos
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Instala Playwright e o navegador Chromium com dependências
RUN playwright install chromium && \
    playwright install-deps chromium

# Copia o restante do código
COPY . .

# Garante permissões para execução e logs
RUN chmod -R 777 /app

# Define variáveis de ambiente
ENV PYTHONUNBUFFERED=1

# Expondo a porta configurada no backend (7860 é o padrão para Hugging Face Spaces)
EXPOSE 7860

# Comando para iniciar o backend com Uvicorn usando a porta 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
