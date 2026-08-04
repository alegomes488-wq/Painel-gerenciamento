---
title: Painel CyberCore IA
emoji: 🛡️
colorFrom: indigo
colorTo: purple
sdk: docker
pinned: false
---

# 🛡️ Painel CyberCore IA

Painel administrativo do CineCash — monitoramento em tempo real de sites, apps e APIs conectados por URL.

## 🔍 Monitoramento por URL
No painel, digite a URL do site e clique em **CONECTAR**. O backend do painel analisa a URL (status HTTP, latência, framework) e grava o projeto em `neural/nodes` no Firebase RTDB. O painel monitora em tempo real o status de cada projeto.

## 🚀 Deployment (Hugging Face Spaces)

### Required Secrets
Configure no Space settings:
- `FIREBASE_SERVICE_ACCOUNT`: Full Service Account JSON.
- `FIREBASE_DATABASE_URL`: URL do Realtime Database (ex.: `https://your-db.firebaseio.com`).
- `ASAAS_API_KEY`: Chave Asaas (produção/sandbox).
- `ADMIN_EMAIL`: E-mail com acesso administrativo (Default: `alegomes488@gmail.com`).
- `WEBHOOK_SECRET`: Token para webhooks.
- `N8N_SHARED_SECRET`: Token interno para auto-aprovação.

## 💻 Desenvolvimento Local
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7861
```

---
*Painel CyberCore IA — tecnologia a serviço da gestão.*
