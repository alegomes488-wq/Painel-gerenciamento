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

# O backend espera encontrar a pasta 'www' no nível acima ou configurada via caminhos.
# No main.py, definimos PROJECT_ROOT como o pai de backend/.
# Com esta estrutura, o main.py em /app/backend encontrará /app/www.

WORKDIR /app/backend

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
