# SECURITY-FIXES — CineCash / Painel CyberCore IA (Agosto/2026)

- **Escopo:** repositório `Painel gerenciamento` (backend FastAPI + www/admin) e `CineCash-por-IA` (site)
- **Método:** um item por vez, com localização → grafo Graphify → causa raiz → correção mínima →
  teste automatizado → reanálise → verificação em produção quando aplicável
- **Regra:** nenhum item é declarado "resolvido" sem evidência (teste de código e/ou verificação ao vivo)

---

## ✅ C1 — Service account do Firebase no histórico do git (P0)

**Problema:** chaves de service account commitadas no histórico dos dois repositórios (`backend/firebase-adminsdk.json`, `.bak`, `backups/firebase - Copia.json`).

**Causa raiz:** arquivos de credencial foram commitados no início do projeto e só removidos do índice depois (o blob seguiu no histórico).

**Correção (contenção + purga):**
1. Teste das chaves vazadas no Google: **todas revogadas** (resposta `invalid_grant / Invalid JWT Signature`).
2. Purga do histórico com `git-filter-repo` (sem `--replace-refs`):
   - clone mirror do painel → purge → força `hf-admin/main` → `41c7352` (árvore idêntica `6d28267`)
   - clone mirror do site → purge → força `hf-user/main` (produção) → `c9ae9db` (árvore preservada `b363aab`)
3. Clone completo da produção `hf-user` purgado (HEAD `91417e2` preservado).
4. Verificação: `hf-admin/staging` e `hf-user/staging` limpos; `origin` (GitHub) nunca teve SA; commits com SA não eram ancestrais do `origin`.
5. `origin` re-adicionado nos dois repositórios; backups em bundle em `%TEMP%\opencode\backup-*.bundle`.
6. Restauração do `www/admin/js/config.js` do painel (working tree resetado pela purga) a partir do cofre.
7. Remanescentes `PRIVATE KEY`/`private_key_id` no histórico são **padrões de guardrail** (`.gitleaks.toml`, `predeploy-check.mjs`), não credenciais.

**Arquivos:** histórico dos dois repositórios (rewrite).

**Evidência:** 5× `invalid_grant`; git verificado limpo; site `desenvovimento-cinecash-ia.hf.space` e painel `desenvovimento-cybercore-ia.hf.space` respondem HTTP 200 + `/health` online.

**Risco residual:** a `geminiKey` antiga (blob `c06f904c:data/config.json`) ainda é reconhecida pelo Google (HTTP 429 quota, não 401) — **pendência do dono: rotacionar no AI Studio**.

**Status:** ✅ **Contido** (rotação + purga) — verificado em produção.

---

## ✅ C2 — Webhook Asaas do painel fail-open (P0)

**Problema:** `backend/app/routers/payments.py` validava o token **somente se** `WEBHOOK_SECRET` existisse (`if webhook_secret:`). Sem o segredo no env, qualquer pessoa podia POSTar `TRANSFER_FAILED`/`TRANSFER_CANCELLED` e **creditar saldo ilimitado** (estorno forjado), ou `TRANSFER_PAID` e corromper estados.

**Causa raiz:** divergência do padrão fail-closed já adotado no site (`backend/main.py` → 503 sem segredo); o estorno ainda checava `status != "refunded"` **fora** da transação (risco de estorno duplo em webhooks concorrentes).

**Correção mínima** (`payments.py:116-215`):
- Fail-closed: **503** sem `WEBHOOK_SECRET`; **403** token ausente/inválido (`hmac.compare_digest`).
- Validações: allowlist de eventos (400 p/ desconhecido); `mapping` e `uid`/`wid` obrigatórios; saque e usuário existentes; `amount > 0`; estados terminais (`paid`/`refunded`/`blocked_by_audit`) bloqueiam.
- Idempotência: claim do estado **dentro** da transação (padrão do site `claim_refund`) — webhook duplicado/concorrente não estorna 2x.
- `TRANSFER_PAID` idempotente e logado (`logs/financial`).

**Arquivos:** `backend/app/routers/payments.py`.

**Evidência:** teste automatizado **13/13** (503/403/sem crédito, estorno único, duplicado ignorado, evento inválido 400, usuário inexistente, mapping ausente). Produção do painel com `WEBHOOK_SECRET` configurado (probe não-destrutivo: resposta `forbidden` só ocorre quando o token é checado, i.e., segredo existe).

**Risco residual:** respostas 503/403 fazem o Asaas reenviar (comportamento esperado do fail-closed).

**Status:** ✅ **Corrigido em código** — **deploy pendente** (push `hf-admin`).

---

## ✅ M5 — Lock anti-concorrência no approve_payment (P1)

**Problema:** `approve_payment`/`auto_approve_withdrawal` do painel pagavam **sem lock**: dois cliques (ou admin + N8N, ou dois webhooks N8N) geravam **duas transferências Asaas** para o mesmo WID.

**Causa raiz:** o site já usa o campo `processing_by` como mutex; o painel não fazia claim atômico (o `auto-approve` checava, mas não gravava o lock — TOCTOU).

**Correção mínima** (`payments.py`):
- `approve_payment` e `auto_approve_withdrawal`: **claim atômico por transação** no nó `admin/pending_withdrawals/{wid}` — aborta se `processing_by` setado ou `status != "pending"` (idempotente), grava o dono (`uid` do admin ou `n8n-auto`).
- Em erro do Asaas, **libera o lock** (delete do campo) para retry — melhoria sobre o site (não deixa saque preso).
- Sucesso remove o nó da fila (o lock morre com o nó).

**Arquivos:** `backend/app/routers/payments.py`.

**Evidência:** teste automatizado **19/19** (claim único, duplo-clique 1× Asaas, lock externo bloqueia, erro libera lock, N8N vs admin, auto-approve com/sem lock).

**Risco residual:** interoperando com o lock do site (sentinel `{"_locked": true}` em colisão no site); se o site travar um lock e falhar, exige limpeza manual (comportamento pré-existente, não introduzido aqui).

**Status:** ✅ **Corrigido em código** — **deploy pendente** (push `hf-admin`).

---

## ✅ A1 — `/api/monitor/*` público no painel (P0/P1)

**Problema:** `backend/app/main.py` isentava `/api/monitor/` do auth. `agent-script` público + frontend instruindo `wget -qO- ... | python3 -` (RCE no servidor do admin se o backend for comprometido). `report` público gravava `neural/nodes/{projectId}/health` **sem validação** (spoof de status/métricas + HTML forjado que o Watch renderiza).

**Causa raiz:** whitelist de auth excessiva + ingestão de telemetria sem saneamento + instrução perigosa de instalação do agente.

**Correção mínima:**
- `main.py`: somente `/api/monitor/report` permanece público (o agente remoto não tem token); **`agent-script` passa a exigir Bearer admin**.
- `projects.py` `monitor_report`: exige `projectId` existente em `neural/nodes/`; **sanitiza** strings (`& < > " '` → entidades, limite 200 chars); **clampa** números (cpu/ram/disk 0–100, load 0–10000).
- `watch.js` `installAgent`: **removida a instrução `| python3 -`**; download do script via fetch autenticado; sem comandos injetados em `innerHTML`/`onclick`.

**Arquivos:** `backend/app/main.py`, `backend/app/routers/projects.py`, `www/admin/js/modules/watch.js`.

**Evidência:** exposição pública confirmada ao vivo (report e agent-script 200 sem auth) **antes** da correção; teste automatizado **11/11** (HTML saneado, clamp numérico, projeto inexistente rejeitado, sem projectId rejeitado). `RCE no servidor do painel: refutado` (nenhuma execução de comando no backend).

**Risco residual:** `report` permanece público por design (agente sem token) — mitigado por saneamento/validação.

**Status:** ✅ **Corrigido em código** — **deploy pendente** (push `hf-admin`).

---

## ✅ A2 — Stored XSS no painel (dados do usuário em innerHTML) (P1)

**Problema:** `fullname`, `pixKey`, `email`, `identifier` e outros dados (controlados por usuário ou pelo site sondado) eram interpolados em `innerHTML`/atributos sem escape — um saque com `pixKey` malicioso executava no browser do admin (roubo de token/sessão).

**Causa raiz:** `escapeHtml()` existia em `utils.js:12` e **nunca era usado**; `showToast` usava `innerHTML`.

**Correção mínima (aplicar `escapeHtml()`):**
- `utils.js`: `showToast` montado com `textContent` (sem `innerHTML`).
- `withdrawals.js`: `fullname`, `pixType`, `platform`, `pixKey` (conteúdo e `title`) e iniciais do avatar escapados.
- `users.js`: `uid` e `email` escapados.
- `secops.js`: motivos (`title` e lista), `item.fullname`, `analysis.fullname`, `pixType`, `pixKey`, `uid`, itens de auditoria e `e.message` escapados.
- `watch.js`: `name`, `identifier`, `type`, `framework`/`tech_stack` escapados; `cpu`/`ram`/`latency` convertidos a números seguros; botões migrados de `onclick` inline para `data-action` + delegação (elimina injeção em atributos de handler).

**Arquivos:** `www/admin/js/utils.js`, `modules/withdrawals.js`, `modules/users.js`, `modules/secops.js`, `modules/watch.js`.

**Evidência:** teste automatizado **5/5** (5 payloads reais de pixKey/fullname neutralizados — nenhum `<` cru / atributo executável; quebras de `</strong>`, `"`, `'` viram entidades); `node --check` em todos os JS; grep confirma zero interpolações sem escape.

**Risco residual:** mínima — demais pontos de render do backend (site) já sanitizavam no servidor.

**Status:** ✅ **Corrigido em código** — **deploy pendente** (push `hf-admin`).

---

## ✅ M1 — App Check do site com chave antiga (P1)

**Problema:** `www/firebase-config.js:31` usava `6LdQzXMt...` (chave clássica, **não-Enterprise**); o backend Firebase agora aponta para `6Leds3Ut...` → o browser recebia `appCheck/recaptcha-error` e `auth/firebase-app-check-token-is-invalid` (login bloqueado).

**Causa raiz:** chave não alinhada ao console/backend após o PATCH da site key Enterprise; o painel já tinha sido corrigido, o site não.

**Correção mínima:** `www/firebase-config.js` → `appCheckSiteKey: '6Leds3Ut...'` (idêntica à do painel, validada no console).

**Arquivos:** `CineCash-por-IA/www/firebase-config.js` (1 linha).

**Evidência:** diff de 1 linha; appId já estava correto (`db9c...`).

**Risco residual:** teste de login real pendente (janela anônima; atenção ao throttle de 24h do App Check).

**Status:** 🟡 **Corrigido em código** — **pendente: commit + push `hf-user` + teste de login em janela anônima**.

---

## Deploy pendente (ações do dono)

1. **Painel** (`hf-admin`): commit das alterações (C2, M5, A1, A2) + push → verificar `/health` e fluxo de webhook/saque.
2. **Site** (`hf-user`): commit do `firebase-config.js` (M1) + push → teste de login em janela anônima nova.
3. Rotacionar a `geminiKey` antiga no AI Studio (residual de C1).
4. Itens ainda abertos da auditoria (não-código): `npm audit` no painel, VAPID push, custom claims (M6), CORS `ALLOWED_ORIGINS` (A5), `database.rules.json` do site (M2/M3), validação de XFF (A3), SRI anúncios (A4).
