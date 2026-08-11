# PYTHON-SECURITY-TEST-MATRIX.md — AUDIT 00 (Descoberta)

> Matriz de testes de segurança planejados. Execução local com mocks (RTDB/Asaas/N8N) — **sem tocar produção**. Colunas de resultado preenchidas após execução.

## Como executar
```
cd <projeto>
python -m pytest tests/ -v --tb=short
```
Os testes mockam `firebase_admin`, `httpx`, `subprocess` e env vars; nada acessa rede.

## Matriz

| ID | Categoria | Teste | Alvo (arquivo:linha) | Input adversarial | Esperado | Resultado |
|----|-----------|-------|----------------------|-------------------|----------|-----------|
| T-01 | AuthN | Token ausente nas rotas protegidas | `main.py:247-331` (site) | sem `Authorization` | 401 | PASS (site) |
| T-02 | AuthN | Token inválido | idem | `Bearer garbage` | 401 | PASS (site) |
| T-03 | AuthN | Conta banida (RTDB `banned`) | `main.py:309-313` | claim de usuário com `banned=true` | 403 | PASS (site) |
| T-04 | AuthN | App Check enforcement no backend | `app/middleware/appcheck.py`; `main.py:117-120` | sem `X-Firebase-AppCheck` | **401 com `APP_CHECK_REQUIRED=true`**; desativado por padrão (`false`) | **PASS (T-04 baseline + middleware 8 testes)** |
| T-05 | Authorization | IDOR: `uid` != dono | `video/start`, `video/complete`, `game/*`, `daily-bonus`, `referral/create`, `referrals`, `payments/request` | `request.state.user_uid="A"`, rota com `{uid}="B"` | 403 | PASS (lógica de guard presente em todas) |
| T-06 | Authorization | `/api/monitor/report` sem auth | `projects.py:219-241` | POST sem Bearer | 200 (bypass) — documentar | PASS (bypass confirmado: 200) |
| T-07 | Authorization | `monitor_report` com projectId inexistente | idem | projectId aleatório | "Projeto não encontrado" | PASS (painel) |
| T-08 | AuthN | Auto-approve token vazio | `payments.py:132-136` | `N8N_SHARED_SECRET=""` + header vazio/ausente | **403 (guard `not expected_token`)** — N8N-04 descartado | PASS (contra-evidência) |
| T-09 | AuthN | Auto-approve token errado | idem | header ≠ secret | 403 | PASS (painel) |
| T-10 | AuthN | Webhook token errado/ausente | `main.py:1303-1314`; `payments.py:234-241` | sem `X-Webhook-Token` | 403 | PASS (site + painel) |
| T-11 | Webhook | Replay TRANSFER_PAID duplicado | `main.py:1348-1361`; `payments.py:270-285` | 2× mesmo evento | idempotente (2º ignorado) | PASS (painel: paid_at inalterado) |
| T-12 | Webhook | Replay TRANSFER_FAILED duplicado | `main.py:1374-1397`; `payments.py:298-324` | 2× mesmo evento | estorno único (2º `None`→ignored) | PASS (site + painel: balance estável) |
| T-13 | Webhook | Webhook com asaas_id sem mapping | ambos | id desconhecido | `not_found` | PASS (site + painel) |
| T-14 | Finance | Saque com saldo insuficiente | `main.py:1073-1075` | balance < amount | erro em transaction | PASS (site: `_error`) |
| T-15 | Finance | Saque 2× na mesma hora | `main.py:1076-1080` | `last_withdraw_at` recente | erro | NOT CREATED (lógica idêntica à T-14, transaction) |
| T-16 | Finance | Saque amount fora da allowlist | `main.py:1057` | amount=0.99 | erro | NOT CREATED |
| T-17 | Finance | Pix key inválida | `main.py:1063-1065` | CPF inválido | erro | NOT CREATED |
| T-18 | Concorrência | 2 approvals simultâneos (mesmo wid) | `main.py:1202-1225` | 2 admins | 1 vence, outro "processando" | PASS (painel: 2º claim None) |
| T-19 | Concorrência | 10 rewards simultâneos mesmo nonce | `main.py:1422-1453` | 10 reqs | só 1 sucesso | PASS (site: nonce usado → `_error`) |
| T-20 | Concorrência | video_complete replay (mesma sessão 2×) | `main.py:647-700+` | sessão usada | 1 crédito | PASS (site: sessão inválida sem crédito) |
| T-21 | Concorrência | daily_bonus 2× | `main.py:1622-1637` | 2 reqs | 1 crédito | PASS (site: `_error`) |
| T-22 | RACE | auto-approve vs approve (mesmo wid) | `payments.py:46-74` + `155-177` | N8N + admin | 1 vence | PASS (mesmo lock claim de T-18) |
| T-23 | SSRF | `_probe` URL interna | `projects.py:52-99` | `http://127.0.0.1:22/`, `http://169.254.169.254/` | **realiza GET** — documentar | PASS (mock: GET em `169.254.169.254`; `_normalize_url` aceita `http://`) |
| T-24 | SSRF | `_probe` redirect loop | idem | URL com redirect p/ si | timeout/límite | NOT CREATED |
| T-25 | Injection | `monitor_report` HTML/script | `projects.py:202-216` | `<script>` em hostname | escapado (`&lt;script&gt;`) | PASS (painel: `_sanitize_text` + endpoint) |
| T-26 | Injection | prompt injection nexus | `main.py:1791`, `n8n_integration.py:107` | question contendo instruções | passa como texto ao LLM (documentar) | NOT CREATED |
| T-27 | Mass assign | `project/save` data arbitrária | `projects.py:116-129` | data com chaves extras | grava tudo (admin) | NOT CREATED |
| T-28 | Rate-limit | register >3/h | `main.py:481-483` | 4 reqs | 4º bloqueado (slowapi) | NOT CREATED |
| T-29 | Secrets | `asaasKey` presente no `config` RTDB? | `main.py:1186-1189` | — | verificação de regra (runtime bloqueado) | BLOCKED |
| T-30 | Conformidade | `/docs` e `/openapi.json` | ambos | GET | painel: 200 (expor); site: 404 (default) | PASS (painel 200 / site 404) |
| T-31 | Injection | register email/password inválidos | `main.py:495-544` | `senha fraca`, `email` mal | 400 | PASS (site) |
| T-32 | Replay | CineBot `_activate_bot` por webhook duplicado | `main.py:1332-1345` | 2× PAYMENT_CONFIRMED | re-grava `active`/earnings (documentar impacto) | NOT CREATED |

## Resumo de execução

- **Harness criado**: `tests/` no painel (8 arquivos) e no site (4 arquivos) com RTDB in-memory, auth mock e httpx mock — **sem rede, sem tocar produção**.
- **Executado**: painel **34/34 PASS**; site **19/19 PASS**.
- **T-04 (App Check)**: baseline provou a brecha (rota protegida respondia 200 sem `X-Firebase-AppCheck`). Correção implementada: `backend/app/middleware/appcheck.py` com validação real via REST `verifyToken` do Google (service account do painel), desativado por padrão (`APP_CHECK_REQUIRED=false`). Exceções: OPTIONS, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/favicon.*`, webhook Asaas, `/api/monitor/report`, `/payments/auto-approve/`, `/api/auto-approve/`. Testes: 8 (desativado/401/503/exceções/OPTIONS/frontend estático).
- **Achados corrigidos durante o harness** (documentação, não código):
  - N8N-04 (auto-approve token vazio) → **DESCARTADO**: guard `if not expected_token` → 403 (testado).
  - T-30 docs → site desabilita por default (`ENABLE_DOCS`); painel expõe.
- **Não testados (NOT CREATED)**: T-15..T-17, T-24, T-26..T-28, T-32 (sem mock adequado nesta fase) e **BLOCKED**: T-29 (requer runtime/credenciais).
- **AVISO DE DEPLOY (App Check)**: `APP_CHECK_REQUIRED` está `false` por padrão. **Só ative `true` após o frontend passar a enviar `X-Firebase-AppCheck`** (hoje `www/admin/js/auth.js` e módulos usam `fetch` direto, sem wrapper — ativar agora quebraria todo o painel com 401).

## Env necessárias (mock)
- `FIREBASE_SERVICE_ACCOUNT` ausente → site usa `dev_local` (não testar com esse estado; mockar `verify_id_token`).
- `N8N_SHARED_SECRET`, `WEBHOOK_SECRET` setadas nos testes via monkeypatch.
