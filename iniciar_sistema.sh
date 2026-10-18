#!/usr/bin/env bash
# Inicia o Painel CyberCore IA em dois servidores (Linux / Git Bash):
#   Backend FastAPI  -> http://localhost:7861
#   Painel Admin     -> http://localhost:8080
# Na primeira execucao no Ubuntu, cria sozinho o ambiente virtual
# em ~/.venvs/painel-gerenciamento e instala as dependencias.
set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-7861}"
ADMIN_PORT="${ADMIN_PORT:-8080}"
VENV_DIR="${PAINEL_VENV:-$HOME/.venvs/painel-gerenciamento}"

# PYTHON pode ser sobrescrito no chamado (ex.: PYTHON=/tmp/venv/bin/python).
# Ordem: 1) PYTHON externo  2) venv do projeto (Linux)  3) venv da casa  4) python3 do sistema
if [ -z "${PYTHON:-}" ] && [ -x "$BASE_DIR/.venv/bin/python" ]; then
    PYTHON="$BASE_DIR/.venv/bin/python"
fi
if [ -z "${PYTHON:-}" ] && [ -x "$VENV_DIR/bin/python" ]; then
    PYTHON="$VENV_DIR/bin/python"
fi
PYTHON="${PYTHON:-python3}"

echo "=========================================="
echo "   INICIANDO PAINEL DE GERENCIAMENTO"
echo "=========================================="
echo "[env] Python: $PYTHON"

if ! command -v "$PYTHON" >/dev/null 2>&1 && [ ! -x "$PYTHON" ]; then
    echo "[ERRO] Python nao encontrado ($PYTHON)."
    echo "       No Ubuntu: sudo apt install python3 python3-venv"
    exit 1
fi

# Primeira execucao sem dependencias: cria venv em $VENV_DIR e instala tudo.
if ! "$PYTHON" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo
    echo "[setup] Dependencias ausentes. Preparando ambiente (so na 1a vez)..."
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        if ! "$PYTHON" -m venv "$VENV_DIR"; then
            echo "[ERRO] Nao foi possivel criar o ambiente virtual."
            echo "       No Ubuntu rode e tente de novo:"
            echo "           sudo apt install python3-venv"
            exit 1
        fi
        echo "[setup] Ambiente criado em: $VENV_DIR"
    fi
    PYTHON="$VENV_DIR/bin/python"
    if ! "$PYTHON" -m pip install --quiet -r "$BASE_DIR/backend/requirements.txt"; then
        echo "[ERRO] Falha ao instalar as dependencias (sem internet?)."
        exit 1
    fi
    echo "[setup] Dependencias instaladas."
fi

echo
echo "[1/2] Iniciando Backend FastAPI na porta $BACKEND_PORT..."
(
    cd "$BASE_DIR/backend" || exit 1
    exec "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload
) &
BACKEND_PID=$!

# Espera o backend responder de verdade (ate 30s) antes de seguir.
backend_ok=no
for _ in $(seq 1 30); do
    sleep 1
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        break
    fi
    if command -v curl >/dev/null 2>&1; then
        code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$BACKEND_PORT/docs" 2>/dev/null)
        [ "$code" = "200" ] && backend_ok=yes && break
    else
        backend_ok=yes && break
    fi
done

if [ "$backend_ok" != yes ]; then
    echo "[ERRO] Backend nao subiu na porta $BACKEND_PORT."
    echo "       Rode manualmente para ver o erro:"
    echo "           cd backend && $PYTHON -m uvicorn app.main:app --reload"
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
