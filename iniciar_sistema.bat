@echo off
echo ==========================================
echo    INICIANDO PAINEL DE GERENCIAMENTO
echo ==========================================
echo.
echo [1/2] Iniciando Backend FastAPI na porta 7861...
echo.

:: Terminal 1 - Backend FastAPI
start "Backend FastAPI - Porta 7861" cmd /k "cd /d C:\Users\Alegomes\Desktop\Painel gerenciamento\backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 7861 --reload"

:: Aguarda 4 segundos para o backend subir primeiro
timeout /t 4 /nobreak >nul

echo [2/2] Iniciando Servidor Admin na porta 8080...
echo.

:: Terminal 2 - Servidor Admin
start "Servidor Admin - Porta 8080" cmd /k "cd /d C:\Users\Alegomes\Desktop\Painel gerenciamento && python servidor_admin.py"

echo.
echo ==========================================
echo    AMBOS OS SERVIDORES INICIADOS!
echo.
echo    Backend API:  http://localhost:7861
echo    Painel Admin: http://localhost:8080
echo.
echo    Pressione qualquer tecla para fechar...
echo ==========================================
pause >nul
