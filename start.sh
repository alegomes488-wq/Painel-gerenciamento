#!/bin/bash
set -e

echo "=== Iniciando CyberCore IA + N8N ==="

# Inicia N8N em background na porta 5678
n8n start --port=5678 &
N8N_PID=$!
echo "[N8N] Iniciado (PID: $N8N_PID, porta 5678)"

# Aguarda N8N ficar pronto
echo "[N8N] Aguardando N8N ficar online..."
for i in $(seq 1 30); do
    if curl -s http://localhost:5678/healthz > /dev/null 2>&1; then
        echo "[N8N] Online!"
        break
    fi
    sleep 1
done

echo "[FASTAPI] Iniciando backend..."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 7860 &
UVICORN_PID=$!

# Graceful shutdown
trap "echo '[SHUTDOWN] Encerrando...'; kill $N8N_PID $UVICORN_PID 2>/dev/null" SIGINT SIGTERM

wait $UVICORN_PID
