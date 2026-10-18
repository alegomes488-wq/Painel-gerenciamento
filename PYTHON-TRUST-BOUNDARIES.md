# PYTHON-TRUST-BOUNDARIES.md — AUDIT 00 (Descoberta)

> Delimitações de confiança nos dois backends Python: quem autentica o quê, onde o dado é confiável e onde não é.

## 1. Identidades e confiança

| Identidade | Fonte | Confiável para | Fraco quando |
|------------|-------|----------------|--------------|
| Usuário final | Firebase ID token verificado (`verify_id_token`) + ownership `request.state.user_uid == uid` | acesso aos próprios recursos | dados do corpo da request (amount, score, pixKey) — sempre sanitizados/validados |
| Admin (site) | `decoded.get("admin")` claim OU `ADMIN_EMAIL` fallback (`_is_admin`, `main.py:207`) | aprovar/processar saques | claim pode não existir (refreshed no painel) |
| Admin (painel) | claim `admin` OU email == `ADMIN_EMAIL` (`main.py:48`) | rotas `/api/*`, `/payments/*` | allowlist de bypass |
| N8N | `X-Internal-Token` == `N8N_SHARED_SECRET` | auto-aprovar saques | token compartilhado com HMAC de webhooks (N8N-02) |
| Asaas | `X-Webhook-Token` == `WEBHOOK_SECRET` | confirmar/estornar transferências | secret único, sem assinatura de payload (ASA-07) |
| Agente monitor (script gerado) | **nenhuma** | escrever `neural/nodes/{id}/health` | qualquer pessoa com projectId conhecido (bypass allowlist) |
| Frontend SDK (Firebase) | ID token + claims | leitura RTDB direta | depende 100% das Security Rules |

## 2. Boundaries por backend

### Site (7860)
```
Internet
  │
  ▼
[CORSMiddleware + auth_middleware (Bearer) + hardening (headers/body 16KB) + App Check?]
  │  user_uid / user_admin / user_email_verified (do token verificado)
  ▼
[Rotas] ──▶ RTDB (Admin SDK — sem rules no servidor, privilégio total)
   │
   └──▶ Asaas (access_token) / N8N (X-N8N-Key+HMAC) / memory (filesystem)
```
- **`dev_local` fallback** (`main.py:280-286`): se `FIREBASE_SERVICE_ACCOUNT` não setada, qualquer request sem token vira `user_uid="dev_local"`. Em produção env setada → não ocorre; em dev é hole deliberado.

### Painel (7861)
```
Internet
  │
  ▼
[CORSMiddleware (ALLOWED_ORIGINS) + admin_auth_middleware]
  ├─ público: /health, /, /docs, /openapi.json, /favicon.ico, static
  ├─ bypass intencional: /payments/webhook, /api/monitor/report, /api/auto-approve/*, /payments/auto-approve/*
  └─ admin (claim ou ADMIN_EMAIL): /api/secops/*, /api/project/*, /api/auth/refresh-admin-claim, /payments/*
        └──▶ RTDB (Admin SDK) + Asaas + SSRF probe
```

## 3. Achados de confiança

| ID | Achado | Evidência | Severidade |
|----|--------|-----------|-----------|
| TB-01 | **`/api/monitor/report` sem auth** permite escrita em `neural/nodes/{projectId}/health` (requer projectId existente) | `main.py:33` (painel), `projects.py:219-241` | P2 |
| TB-02 | `_is_admin` aceita `ADMIN_EMAIL` fallback por e-mail do token — quem controlar uma conta com esse e-mail vira admin (Google) | `main.py:207-211` (site), `main.py:48` (painel) | P1 (depende da conta) |
| TB-03 | `/docs` + `/openapi.json` públicos **no painel** (default); site desabilita via `ENABLE_DOCS` | `app/main.py:25` (painel), `main.py:161-166` (site) | P3 |
| TB-04 | Painel admin promove claim `admin:True` via `/api/auth/refresh-admin-claim` — sem MFA, sem origem extra | `main.py:82-94` | P2 |
| TB-05 | Token cache `_token_cache` TTL 5s (`main.py:64-66`) — janela pós-revogação pequena, aceitável | `main.py:294-318` | OK |
| TB-06 | Webhook do site ativa CineBot por `external_ref` truncado (`uid[:12]`) e itera tudo — identidade frágil | `main.py:1332-1345` | P3 |
| TB-07 | Frontend admin lê RTDB direto (SDK) — a real proteção dos dados é **só** as Security Rules | `admin/js/config.js:49-60` | P1 (rules, fora do Python) |
| TB-08 | Serviço de serviço de conta (Service Account) com privilégio total — vazamento = P0 total | env vars | P0 (chave) |

## 4. Matriz identidade → ação
| Ação | Usuário | Admin | N8N | Webhook | Anônimo |
|------|:-------:|:-----:|:---:|:-------:|:-------:|
| Registrar | — | — | — | — | sim (rate 3/h) |
| Ver vídeo / jogar / bônus | sim (dono) | — | — | — | não |
| Pedir saque | sim (dono, email verificado) | — | — | — | não |
| Aprovar saque | — | sim | sim (token) | — | não |
| Confirmar/estornar | — | — | — | sim (secret) | não |
| Criar projeto / probe SSRF | — | sim | — | — | não |
| Report monitor | — | — | — | — | **sim (bypass)** |
| Ler RTDB | via SDK+rules | via SDK+rules | — | — | rules |
