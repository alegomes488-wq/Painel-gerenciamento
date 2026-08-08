# Auditoria Completa — CineCash / Painel CyberCore IA

- **Data:** Agosto/2026
- **Método:** Revisão de código estática completa + regras RTDB ao vivo (via service account) + grafos Graphify + histórico git
- **Escopo:** `CineCash-por-IA` (site + backend + functions + n8n) e `Painel gerenciamento` (painel admin + backend FastAPI)
- **Base:** PENTEST-REPORT.md e PENTEST-ROUND2.md (rounds anteriores) + nova auditoria dos dois repositórios

---

## 1. Arquitetura

### 1.1 Site (CineCash-por-IA)
```
Firebase (playearn-b001b)
  ├─ Auth (email/senha + Google)  ├─ RTDB (users, withdrawals, referrals, admin, config, logs)
  └─ App Check (reCAPTCHA Enterprise)
HF Space (desenvovimento-cinecash-ia.hf.space)
  ├─ FastAPI backend/main.py (~2200 linhas) — auth middleware, VAR antifraude, RAG/Nexus
  ├─ backend/cinebot_routes.py — assinatura CineBot (Pix Asaas)
  ├─ backend/n8n_integration.py — webhooks HMAC p/ n8n (LLM, auto-aprovação de saques)
  ├─ memory_manager.py + memory/ (FAQ local em arquivo)
  └─ Servidor estático www/ (SPA app.js, register.js, etc.)
Cloud Functions (functions/index.js) — validateWithdrawal (auditoria + estorno atômico)
n8n (external) — nexus-llm, withdraw-auto-approve (HMAC), webhooks
Asaas API — cobranças Pix (CineBot) e transferências (saques)
Cloudflare Worker (cybercore-api) — referenciado no frontend
```
Fluxo de dinheiro: assistir vídeos → crédito por vídeo (server-side) → milestones → saque via PIX
(Asaas transfers) → admin aprova → n8n pode auto-aprovar → webhook Asaas confirma/estorna.

### 1.2 Painel (Painel gerenciamento)
```
HF Space (Painel CyberCore IA)
  ├─ FastAPI backend/app/main.py — middleware auth (Bearer + verify_id_token + ADMIN_EMAIL)
  ├─ routers: payments (aprovação/auto-aprovação/webhook Asaas), projects (monitora URL), secops (risco)
  ├─ services: asaas_service, firebase_service, secops_agent
  └─ StaticFiles www/admin/ (SPA — index.html + js/modules/*)
Firebase (mesmo projeto playearn-b001b) — admin/pending_withdrawals, admin/asaas_mappings, neural/nodes
```
Fluxo: usuário pede saque no site (grava em `withdrawals/{uid}` + `admin/pending_withdrawals`) → painel
lista pendentes → admin aprova (chama Asaas transfer) → webhook Asaas atualiza status.

---

## 2. Verificações positivas (defesas corretas)

- **RTDB rules AO VIVO (verificadas via SA):** `users/{uid}.balance`, `videosWatched`, `status`,
  `risk_score`, `role`, `is_admin` → `.write: false`. Cliente só escreve `fcm_token`,
  `security/last_login_fingerprint` (64-hex), `legal_acceptance` (uma vez). **Refuta a suspeita V1 do app.js**
  (auto-creditagem de saldo): regras publicadas impedem. Config/status/logs restritos a admin.
- **Backend site:** `verify_id_token(check_revoked=True)` na maioria das rotas; UID do token (não do body);
  rate limit por IP; VAR antifraude com transações atômicas; saque com `_claim` por transação; nonce único
  para jogos; estorno idempotente (`claim_refund` + transação); sanitização HTML no memory/store.
- **Webhook Asaas (site):** exigido `WEBHOOK_SECRET` (falha fechado: 503 se ausente) + `hmac.compare_digest`.
- **CR-02 corrigido:** registro Google usa id_token verificado (sem `google_uid` do body); senha forte
  obrigatória (10+ chars, 4 classes); email_verified gate opcional.
- **Painel backend:** auth em `/api/*` e `/payments/*` com Bearer + `check_revoked` + e-mail admin.
- **CSP/firebase.json (site):** headers de segurança, redirect para cinecash.com.br, `object-src 'none'`,
  `frame-ancestors 'none'`.

---

## 3. VULNERABILIDADES ATIVAS (por prioridade)

### 🔴 CRÍTICAS

**C1 — Service account do Firebase no histórico do git (não resolvido).**
`git log --all` ainda lista `backend/firebase-adminsdk.json`, `.bak` e `backups/firebase - Copia.json`
(commits: c91b36b, 1012abe, b3e457d, 701872d...). O commit `c91b36b` só remove do índice — o blob com a
`private_key` segue acessível no histórico. `.gitleaks.toml` **não existe** em disco (o pre-commit chama
`--config .gitleaks.toml` e cairia no fallback). Nenhum sinal de que a chave foi revogada no GCP.
→ **Ação imediata:** revogar no console + purgar história (`git filter-repo`) + rotacionar.
**Status (Ago/2026):** ✅ **CONTIDO** — chaves vazadas revogadas (5× `invalid_grant`); histórico purgado
com `git-filter-repo` + force-push (`hf-admin` → `41c7352`, `hf-user` produção → `c9ae9db`, árvores
preservadas); `origin` limpo; verificado em produção (HTTP 200 + `/health`). **Residual:** rotacionar a
`geminiKey` antiga no AI Studio (ainda reconhecida, quota 429).

**C2 — Webhook Asaas do PAINEL sem exigir segredo configurado (divergência do site).**
`backend/app/routers/payments.py:117-122`: o site **exige** `WEBHOOK_SECRET` (503 sem ele); o painel
**só valida se** `webhook_secret` existir: `if webhook_secret: if not compare_digest(...): return forbidden`.
Se `WEBHOOK_SECRET` não estiver no env do painel, **qualquer pessoa** pode POSTar `TRANSFER_PAID` para
qualquer `asaas_id` (ou `TRANSFER_FAILED`/`TRANSFER_CANCELLED` para **estornar saldo**) — desde que conheça
o `asaas_id`. O estorno credita `balance` na transação do usuário. → **Risco de roubo via estorno.**
→ Corrigir para exigir o segredo (fail-closed) como no site.
**Status (Ago/2026):** ✅ **CORRIGIDO EM CÓDIGO** — `payments.py` agora é fail-closed (503 sem
`WEBHOOK_SECRET`, 403 token inválido) + validações (evento, mapping, usuário, valor, estado) + estorno
idempotente com claim dentro da transação. Teste automatizado **13/13**. `WEBHOOK_SECRET` confirmado no
env de produção do painel. **Deploy pendente** (push `hf-admin`).

### 🟠 ALTAS

**A1 — `/api/monitor/report` e `/api/monitor/agent-script` públicos no painel.**
`backend/app/main.py:32` isenta `/api/monitor/` do auth; `projects.py:202-222` grava em
`neural/nodes/{projectId}/health` sem validação (spoof de status/métricas; vetor de HTML forjado que o
Watch renderiza). `agent-script` é público e o frontend manda o admin executar `wget -O- ... | python3 -`
(`watch.js:168-184`) → se o backend for comprometido, RCE no servidor do admin (e vice-versa).
→ Restringir a admin; validar `projectId`; não instruir pipe de script remoto sem pinning.
**Status (Ago/2026):** ✅ **CORRIGIDO EM CÓDIGO** — `agent-script` exige Bearer admin; `report` valida
projeto existente, sanitiza strings e clampa números; instrução `wget | python3 -` removida (download
autenticado). Teste **11/11**. **RCE server-side refutado** (sem execução de comando no backend).
**Deploy pendente** (push `hf-admin`).

**A2 — Stored XSS no PAINEL admin (dados do usuário renderizados em innerHTML).**
- `www/admin/js/modules/withdrawals.js:43-52` — `fullname` e `pixKey` em `<strong>/<code>` sem escape
  (campos do pedido de saque, controlados pelo usuário).
- `www/admin/js/modules/users.js:7-8` — `u.email` em `<strong>` sem escape.
- `www/admin/js/modules/secops.js:195,303,327-331,338` — fullname/pixKey/motivos.
- `www/admin/js/modules/watch.js:153-155` — `identifier` injetado em `onclick` sem escape.
- `www/admin/js/utils.js:28` — `showToast` usa innerHTML sem escape (mensagens de erro/name de sites).
O backend valida admin por e-mail, mas um usuário comum que consiga gravar um saque com `pixKey` = payload
HTML executa no browser do admin ao abrir o painel → roubo de token/sessão.
→ **Falta de uso do `escapeHtml()` que já existe em `utils.js:12` (está morto).**
**Status (Ago/2026):** ✅ **CORRIGIDO EM CÓDIGO** — `escapeHtml()` aplicado em withdrawals (fullname/
pixKey/pixType/platform/avatar), users (uid/email), secops (motivos/fullname/pixKey/pixType/uid/auditoria),
watch (name/identifier/framework + botões com delegação) e `showToast` (textContent). Teste **5/5**.
**Deploy pendente** (push `hf-admin`).

**A3 — Rate limit e VAR dependentes de IP forjável (site).**
`backend/main.py:159-169` `_get_client_ip` confia no último hop do `X-Forwarded-For`; se o app for
acessado fora do proxy HF (ou o proxy não anexar), o header é forjável → bypass de rate limit e do VAR.
→ Validar que a conexão direta vem do proxy confiável antes de confiar no XFF.

**A4 — Execução de código de terceiros sem SRI (site).**
`app.js:1459-1471` injeta `<script>` de `quge5.com` e `al5sm.com` (redes de anúncio) no body. Não há SRI
(os fornecedores não publicam hashes estáveis) e o CSP precisa allowlist deles. Se comprometidos → XSS pleno
(acesso a tokens Firebase, localStorage). Risco inerente ao modelo, mas deve ser isolado (iframe sandbox).

**A5 — CORS wildcard + credentials no painel.**
`backend/app/main.py:13-19`: `allow_origins=["*"]` + `allow_credentials=True` (combinação que browsers
rejeitam, mas config incorreta). O site corrigiu (credentials só com origens explícitas); o painel não.

### 🟡 MÉDIAS

**M1 — App Check do SITE com chave antiga/errada (bloqueia login do usuário).**
`www/firebase-config.js:31` ainda usa `6LdQzXMt...` — a chave que **não é Enterprise** (análise do
`enterprise.js`: retorna `render:'onload'`) e que o backend do Firebase **agora aponta para `6Leds3Ut...`**
(PATCH aplicado). Resultado: browser recebe `appCheck/recaptcha-error` + `auth/firebase-app-check-token-is-invalid`.
O painel já foi corrigido localmente (`www/admin/js/config.js:23` → `6Leds3Ut...`, appId `db9c...`) mas o
site não foi publicado. **Este é o bug ativo que impede o login.**
**Status (Ago/2026):** ✅ **CORRIGIDO EM CÓDIGO** — `www/firebase-config.js` → `appCheckSiteKey
6Leds3Ut...` (mesma do painel/console). **Pendente:** commit + push `hf-user` + teste de login em janela
anônima (atenção ao throttle de 24h do App Check).

**M2 — Painel: regras RTDB perigosas versionadas/local.**
`database.rules.json` (painel, untracked) permite `users/$uid .write` ao próprio usuário (só `fullname`/`username`
têm `.read` público; o resto cai no `.write` amplo) — **não é o que está publicado** (publicado = rules do site,
seguras). Risco: alguém rodar `firebase deploy --only database` a partir do painel e sobrescrever as regras
boas com as permissivas. → Alinhar o arquivo às regras publicadas ou removê-lo.

**M3 — Fim do `database.rules.json` do site no repositório.**
O `firebase.json` do site referencia `database.rules.json`, mas o arquivo foi removido do tracking (último
registro: ec54ab5). As regras **publicadas** estão corretas, mas não há mais single source of truth no repo
→ `firebase deploy --only database` falha hoje. → Recriar o arquivo com as regras publicadas (obtive cópia).

**M4 — `/api/n8n/url` expõe base de webhooks (baixo/médio).** `n8n_integration.py:129-135` — protegida a admin,
mas expõe a URL base n8n. Aceitável, mas desnecessário.

**M5 — `process_all_payments` / `approve_payment` (painel) sem lock anti dupla-pagamento.**
`payments.py:12-45` — o site usa `processing_by` (lock) em `approve_payment`; o painel **não** usa
(`withdrawals.js` até tenta via SecOps cache, mas o backend não bloqueia concorrência). Dois cliques/
requests paralelos → duas transferências Asaas para o mesmo WID. O `auto-approve` do painel já checa
`processing_by`, mas o `approve` manual não.
**Status (Ago/2026):** ✅ **CORRIGIDO EM CÓDIGO** — `approve_payment` e `auto_approve_withdrawal` com
claim atômico por transação no nó da fila (dono = uid do admin ou `n8n-auto`); lock liberado em erro.
Teste **19/19**. **Deploy pendente** (push `hf-admin`).

**M6 — Admin por igualdade de e-mail hardcoded (painel).** `main.py:45` e `auth.js:35` — funciona, mas sem
custom claims (o site migrou para claims; o painel não).

### 🟢 BAIXAS / INFO
- `withdrawals.js:144` usa `/payments/approve` sem prefixo `/api` (inconsistência de rotas no painel).
- `watch.js:186-195` "DESCONECTAR" alterna `config.maintenance` global (não o projeto) — bug de lógica.
- Painel: `main.js` engole 401/403 (sem logout forçado); `_secopsCache` race ao aprovar sem análise.
- Painel: `sw.js`/`firebase-messaging-sw.js` apontam para projeto Firebase DIFERENTE (`...1071946051515`) e
  nunca são registrados — código morto + credenciais legadas espalhadas.
- Site: `app.js` — typos `desenvovimento-...hf.space`; logout remove chave errada (sessionStorage vs
  localStorage); milestone duplicado (578 vs 583-591); `renderMarkdown` quebra URLs com `&`.
- Site: `nexus` FAQ em arquivo local (`memory/faq.json`) — não escala em múltiplas réplicas (documentado).
- Rate limits (site): buckets globais quando atrás do proxy se o XFF não for confiável (ver A3).
- VAPID de exemplo removido (bom) — push só com `config/vapidKey` real (pendência do dono).

---

## 4. LÓGICA NEGOCIÁVEL NO CLIENTE (site) — residual
- `/video/complete`: validado server-side (sessão ≥29s, rate 3/min, VAR velocidade) — **correto**; não dá
  para farmar sem esperar.
- Saque: valores/pix validados no backend + transação de saldo + limite 1/h — **correto**.
- Jogos: nonce de sessão + caps diários + recompensas baixas — mitigado (IN-01 resolvido).
- Bônus de fim de semana: validado no backend (weekday) — **correto**.
- Referral: crédito 0.30/0.20 em transações atômicas com flag `credited` (idempotente) — **correto**.

---

## 5. PENTEST anteriores → status
| Achado | Status |
|---|---|
| CR-01 SA no git | **CONTIDO** (revogação + purga + force-push; seção 3-C1) |
| C2 webhook painel | **Corrigido em código** (fail-closed + validações; 13/13) — deploy pendente |
| A1 monitor público | **Corrigido em código** (auth agent-script + report endurecido; 11/11) — deploy pendente |
| A2 stored XSS painel | **Corrigido em código** (escapeHtml em todos os innerHTML; 5/5) — deploy pendente |
| M1 App Check site | **Corrigido em código** (site key Enterprise) — pendente push + teste login |
| M5 lock dupla-pagamento | **Corrigido em código** (claim atômico; 19/19) — deploy pendente |
| CR-02 google_uid | Corrigido (verificado no código) |
| AL-01 CORS | Corrigido no SITE; **reaberto no PAINEL** (A5) |
| AL-02 rate limit/XFF | Parcialmente corrigido (A3 residual) |
| AL-03 chave N8N hardcoded | Corrigido (removido fallback) |
| AL-04 webhooks n8n públicos | Corrigido (HMAC nos workflows) |
| AL-05 refund não-atômico | Corrigido (claim_refund + transaction) |
| MD-01 referrals | Corrigido (rules ao vivo: read restrito) |
| MD-02 seen_by | Corrigido |
| MD-03 CineBot charge | Corrigido (`_charge_belongs_to`) |
| MD-04 email verify | Parcial — gate existe; fluxo de reset presente |
| MD-05 senha fraca | Corrigido (10+ chars, 4 classes) |
| MD-06 stored XSS memory/store | Corrigido (sanitização server-side) |
| MD-07 admin por e-mail | Site corrigido (claims); painel **não** (M6) |
| BA-02 docs públicos | Corrigido (ENABLE_DOCS) |
| BA-03 comparação não-ct | Corrigido no site; painel usa compare_digest ✓ |
| BA-04 SRI anúncios | Parcial (A4 — sem SRI, mas CSP) |
| BA-05 deps | `npm audit` 0 vulns (functions); painel: **não auditado** |

---

## 6. QUALIDADE / CÓDIGO MORTO (destaques)
- **Painel:** `escapeHtml()` nunca usado (utils.js:12) — irônico pois é a correção de A2; `removeProject`
  sem handler; `updateStatusIndicators` age em elemento inexistente (`#toggle-maintenance`); `checkPythonCoreStatus`
  e `updateTelemetria` nunca chamados; receita `((hits/1000)*cpm*5.25)` e ROI `+0.00%` fixo são métricas falsas.
- **Painel:** N+1 fetches de risk-analysis por snapshot sem debounce (mitigado por cache 60s).
- **Site:** variáveis nunca usadas (`heartbeatInterval`, `_referralUnsub`, `window._processTimer`);
  listener Enter duplicado; `document.execCommand('copy')` deprecated.
- **Ambos:** HTML gigante por template literal sem templating.

---

## 7. PLANO DE AÇÃO PRIORIZADO

| Pri | Ação | Acha |
|---|---|---|
| 1 | ~~Revogar SA no GCP~~ + purgar git history (ambos repos) | C1 ✅ contido |
| 2 | Publicar correção App Check: site `firebase-config.js` → `6Leds3Ut...` + testar login | M1 ✅ código; deploy pendente |
| 3 | Webhook do painel: exigir WEBHOOK_SECRET (fail-closed) + validações | C2 ✅ código; deploy pendente |
| 4 | Aplicar `escapeHtml()` em todos os innerHTML do painel | A2 ✅ código; deploy pendente |
| 5 | Autenticar `/api/monitor/agent-script`; endurecer `/api/monitor/report`; remover `curl\|python3` | A1 ✅ código; deploy pendente |
| 6 | Lock anti-dupla no `approve_payment`/`auto-approve` (claim atômico) | M5 ✅ código; deploy pendente |
| 7 | Recriar `database.rules.json` do site (regras publicadas) e alinhar/remover o do painel | M2/M3 |
| 8 | `ALLOWED_ORIGINS` explícito no painel | A5 |
| 9 | Validar XFF somente quando atrás do proxy confiável (site) | A3 |
| 10 | Migrar painel para custom claims; tratamento de 401/403; corrigir `toggleProjectConnection` | M6/qualidade |

**Pendências do dono (não-código):** deploy das correções (push `hf-admin` + `hf-user`); teste de login
anônimo (M1); rotacionar `geminiKey`; `config/vapidKey` para push; `npm audit` no painel; aplicar regras
RTDB (M2/M3); A5 CORS; A3 XFF.

---

## 8. Conclusão
A rodada de correção P0→P1 (Ago/2026) **fechou em código os itens críticos/altos do painel** (C2 webhook
fail-closed, M5 lock anti-dupla, A1 monitor autenticado/endurecido, A2 XSS) com testes automatizados
(C2 13/13, M5 19/19, A1 11/11, A2 5/5) e **conteve o C1** (revogação + purga verificada em produção). O
**M1** (App Check do site) está corrigido no código e aguarda publicação + teste de login. Faltam:
**deploy** dos dois repositórios (push `hf-admin`/`hf-user`), a rotação da `geminiKey`, e os itens de
maturidade (A5 CORS, A3 XFF, M2/M3 rules, M6 claims, A4 SRI, `npm audit`). Nenhum item foi marcado como
resolvido sem evidência (teste e/ou verificação ao vivo).
