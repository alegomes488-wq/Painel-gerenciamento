@echo off
echo === Iniciando Painel Admin (porta 7861) ===
uvicorn backend.admin_panel:app --host 0.0.0.0 --port 7861 --reload
pause
