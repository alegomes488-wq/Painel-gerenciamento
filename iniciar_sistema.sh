#!/usr/bin/env bash
# Inicia o Painel CyberCore IA em dois servidores (Linux / Git Bash):
#   Backend FastAPI  -> http://localhost:7861
#   Painel Admin     -> http://localhost:8080
set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-7861}"
ADMIN_PORT="${ADMIN_PORT:-8080}"
# PYTHON pode ser sobrescrito no chamado (ex.: PYTHON=/tmp/venv/bin/python).
# O .venv local so e usado se for um venv do Linux (bin/python existe).
if [ -z "${PYTHON:-}" ] && [ -x "$BASE_DIR/.venv/bin/python" ]; then
    PYTHON="$BASE_DIR/.venv/bin/python"
fi
PYTHON="${PYTHON:-python3}"

echo "=========================================="
echo "   INICIANDO PAINEL DE GERENCIAMENTO"
echo "=========================================="
echo "[env] Python: $PYTHON"

if ! command -v "$PYTHON" >/dev/null 2>&1 && [ ! -x "$PYTHON" ]; then
    echo "[ERRO] Python nao encontrado ($PYTHON). Crie o ambiente virtual:"
    echo "       python3 -m venv .venv && source .venv/bin/activate"
    echo "       pip install -r backend/requirements.txt"
    exit 1
fi

echo
echo "[1/2] Iniciando Backend FastAPI na porta $BACKEND_PORT..."
(
    cd "$BASE_DIR/backend" || exit 1
    exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
) &
BACKEND_PID=$!

sleep 3
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[ERRO] Backend falhou ao iniciar. Verifique as dependencias:"
    echo "       pip install -r backend/requirements.txt"
    exit 1
fi

echo "[2/2] Iniciando Servidor Admin na porta $ADMIN_PORT..."
echo
echo "=========================================="
echo "  Backend API:  http://localhost:$BACKEND_PORT"
echo "  Painel Admin: http://localhost:$ADMIN_PORT"
echo "  Para encerrar: Ctrl+C nesta janela"
echo "=========================================="
echo

(
    cd "$BASE_DIR" || exit 1
    exec env ADMIN_PORT="$ADMIN_PORT" "$PYTHON" servidor_admin.py
) &
FRONTEND_PID=$!

cleanup() {
    echo
    echo "[+] Encerrando servidores..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
}
trap cleanup INT TERM

wait
