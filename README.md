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

### Backend (FastAPI)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7861
```

### Frontend (Painel Admin)
```bash
# Opção 1: VS Code Live Server (recomendado)
# Clique com direito em www/admin/index.html → "Open with Live Server"
# Acessa em http://localhost:8080

# Opção 2: Python built-in server
cd www/admin
python -m http.server 8080
# Acessa em http://localhost:8080

# Opção 3: servidor_admin.py (incluído no projeto)
python servidor_admin.py
# Acessa em http://localhost:8080 (padrão, ou porta definida em ADMIN_PORT)
```

> ⚠️ **IMPORTANTE:** Nunca abra o painel via `file://`. Sempre use `http://localhost:8080`.

### App Check Debug (desenvolvimento local)
O painel ativa automaticamente o modo debug do App Check em `localhost`. Ao recarregar a página:
1. Abra o console (F12)
2. Copie o token de debug exibido
3. Registre em: Firebase Console → App Check → Apps → cashvideos → Manage debug tokens

## 🔒 Correções de Segurança Aplicadas (Agosto/2026)
- **C1**: Service accounts revogadas e histórico do git purgado
- **C2**: Webhook Asaas fail-closed (503 sem segredo, 403 token inválido)
- **M5**: Lock anti-concorrência no approve_payment (claim atômico)
- **A1**: `/api/monitor/*` protegido (agent-script exige Bearer admin)
- **A2**: Stored XSS neutralizado (escapeHtml em todos os pontos de render)
- **M1**: App Check com chave Enterprise correta (`6Leds3Ut...`)

## 📁 Estrutura do Projeto
```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI + middleware auth
│   │   └── routers/
│   │       ├── payments.py      # Webhooks + saques
│   │       └── projects.py      # Monitoramento
│   └── requirements.txt
├── www/
│   └── admin/
│       ├── js/
│       │   ├── config.js        # Firebase config + App Check
│       │   ├── auth.js          # Login + claim sync
│       │   ├── main.js          # Listeners RTDB
│       │   ├── ui.js            # Navegação
│       │   └── utils.js         # Helpers
│       └── sw.js                # Service Worker (messaging)
├── servidor_admin.py            # Servidor HTTP dev
└── README.md
```

---
*Painel CyberCore IA — tecnologia a serviço da gestão.*
