# PYTHON-DEBUG-BACKLOG.md — AUDIT 00 (Descoberta)

> Backlog de débitos de descoberta (leitura pendente, verificação de runtime, achados não testáveis localmente). Próximas fases: DEBUG BLOCKS.

## 1. Leitura pendente (Fase 3)

| Item | Local | Por que importa |
|------|-------|-----------------|
| `video_complete` completo (700-900) | `main.py` | valor do crédito por vídeo + integração N8N/ASAAS pós-completar |
| `nexus_ask`/`_call_llm_with_context` (1789-2100) | `main.py` | onde chama `call_n8n_llm` (dead code F-12) |
| `memory_search`/`memory_store` (1712-1788) | `main.py` | escrita em filesystem `memory/` |
| Uso de `send_encrypted_webhook`/`trigger_n8n_webhook` no site | `main.py` | eventos N8N reais |
| `resolve_referral` (931-960) | `main.py` | fluxo público de referral |
| `secops_agent.py` (10-200) | painel | lógica de risco de saque (F-09) |
| `firebase_service.py` | painel | singletons `get_db`/`get_auth` |
| `www/admin/js/*` completo (main, utils, ui, modules) | painel | confirma FE-02/FE-05 e chamadas diretas ao RTDB |
| `www/*.js` do site restante (app.js além das linhas greps) | site | FE-03 (jogos), outras rotas |
| `n8n-workflows/*.json` (7) | site (gitignored) | N8N-03 e demais endpoints |
| `functions/index.js` + `firebase.json` | ambos | F-01/F-02 (deploy bloqueado) |

## 2. Verificações de runtime (BLOCKED — produção)

| Item | Pergunta | Bloqueio |
|------|----------|----------|
| `N8N_SHARED_SECRET` setada no painel? | A-02: auto-approve com token vazio? | acesso a env de produção |
| `WEBHOOK_SECRET` setada? | webhooks aceitos? | idem |
| `ASAAS_API_KEY` em `config` RTDB? | asaasKey exposta às rules? | regras + runtime |
| `FIREBASE_APP_CHECK_REQUIRED` | App Check enforcement ativo? | env |
| claims `admin` existem nos admins? | F-09 admin OU e-mail | Auth SDK |
| worker `cybercore-api...workers.dev` | EXT-01: quem consome? | código frontend/back |

## 3. Achados a reproduzir em DEBUG (não corrigir no AUDIT 00)

| ID | Descrição | Plano de reprodução |
|----|-----------|---------------------|
| N8N-04/A-02 | auto-approve token vazio → **descartado: guard `not expected_token` → 403** | teste T-08 (PASS) |
| R-07 | webhook CineBot duplicado reativa bot | teste com evento duplicado (T-32) |
| INJ-01 | SSRF `_probe` | teste p/ `127.0.0.1` (T-23) |
| I-04 | `get_referrals` vaza dados | teste de payload (T-05 ext) |
| A-01 | monitor/report bypass | teste (T-06/T-07) |
| O-06 | DOS redirect loop no probe | teste (T-24) |

## 4. Decisões de não-correção (regras do AUDIT 00)
- Não corrigir: INV-01 (run_admin.bat), INV-02 (backend/Dockerfile painel), INV-03 (servidor_admin), INV-04 (agent-example), F-01/F-02 (deploy), rotação de chaves, refactor `_probe`.
- Classificar sem remover: `POTENTIAL_DEAD_CODE` (F-12): `get_embedding_cached` (main.py:128), `load_summary` (main.py:1663), `settings` (config.py:22), `call_n8n_llm` (n8n_integration.py:107), `week_start/week_end` (cinebot_routes.py:170).

## 5. Ordem sugerida para a próxima fase (DEBUG BLOCKS)
1. **BLOCO A — AuthN/AuthZ**: A-02 (auto-approve — testado, guard seguro), A-01 (monitor/report — testado), A-06 (docs — painel expõe), ~~T-04~~ (**implementado**: middleware `app/middleware/appcheck.py` + 8 testes PASS; `APP_CHECK_REQUIRED=false` por padrão — ver deploy-checklist), T-27.
2. **BLOCO B — Financeiro**: T-15..T-17, T-32, FIN-01..FIN-07, R-07.
3. **BLOCO C — Webhook**: T-26, ASA-01..ASA-07 (T-10..T-13 já testados PASS).
4. **BLOCO D — SSRF/Injection**: T-24, INJ-01 (testado), INJ-03 (prompt injection).
5. **BLOCO E — Rate/DoS/Hardening**: T-28, O-04..O-08, T-29 (BLOCKED).

## 6. Harness de testes criado (AUDIT 00)
- **Painel** (`Painel gerenciamento/tests/`): `conftest.py`, `test_appcheck.py`, `test_appcheck_middleware.py`, `test_auto_approve.py`, `test_webhook.py`, `test_monitor_projects.py`, `test_payout_lock.py`, `test_docs.py` → **34 testes, 34 PASS** (atualizados ao código vigente: webhook `payment.externalReference` + HMAC, auto-approve Bearer, transactions `committed`/`value`, `sanitize_string`/`clamp_number`).
- **Site** (`CineCash-por-IA/tests/`): `conftest.py`, `test_auth.py`, `test_webhook.py`, `test_financial.py`, `test_misc.py` → **19 testes, 19 PASS**.
- **Total: 53/53 PASS**, 0 FAIL, 0 PARTIAL. 8 testes do plano não criados (T-15..T-17, T-24, T-26..T-28, T-32) + 1 BLOCKED (T-29).
- Nada tocou produção/rede: RTDB, Asaas e N8N totalmente mockados.
