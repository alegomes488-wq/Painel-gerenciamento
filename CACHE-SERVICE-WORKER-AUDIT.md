# CACHE-SERVICE-WORKER-AUDIT — FASE 4

**Data:** 2026-10-05
**Branch:** `main` — HEAD `7c7caec feat(appcheck): frontend patches + rebranding CyberCore IA v4.0`
**Classificação:** `CORRIGIDO` (item 4.1) + `PENDENTE` (itens 4.2, 4.3, 4.4) + `INDETERMINADO` (item 4.5)
**Escopo:** site (`CineCash-por-IA/www`) e painel (`Painel gerenciamento/www/admin`)

---

## 1. Resumo

Auditei os dois lados para responder a uma pergunta específica: **o site estar em
manutenção por cache era possível?**

**Resposta: não.** O service worker do site é *network-first* com fallback para
cache, então com rede o `index.html`, `app.js` e `firebase-config.js` sempre
vêm do servidor. O estado de manutenção é lido do RTDB, que o SW não cacheia
(não é `script`/`style`/`image`/`document`/`font`, e `shouldCache` barra
origem diferente da própria). **A causa raiz continua sendo
`config/maintenance = true` no `playearn-b001b-default-rtdb.firebaseio.com`** —
já confirmada e já diagnosticada antes.

No painel,achei o oposto: **nenhum service worker é registrado.** Os dois
arquivos de SW existem mas são código morto.

**Uma correção aplicada** (item 4.1): backups de auditoria dentro da raiz
estática agora respondem 404.

---

## 2. Site (`CineCash-por-IA/www`)

### 2.1 `sw.js`  — estratégia network-first, correto

| Item | Valor medido |
|---|---|
| `CACHE_NAME` | `cinecash-v25` (L51) |
| `MAX_CACHE_ITEMS` | 80 (L52), FIFO via `cache.keys()[0]` (L88–91) |
| Estratégia | **`fetch()` primeiro, cache só no `.catch()`** (L139–164) |
| `install` | precache de `SHELL_ASSETS` + `skipWaiting()` (L116–126) |
| `activate` | apaga todo cache ≠ `CACHE_NAME`, depois `trimCache()`, depois `clients.claim()` (L128–136) |
| Domínios ignorados | `hf.space`, `gstatic.com`, `googleapis.com`, `firebasestorage.googleapis.com`, `fcmregistrations.googleapis.com` (L66–72) |
| Só GET, só mesma origem | sim (L77–78) |
| Documentos legais | **fora do cache**, com justificativa escrita no código (L54–63, L80) |

`shouldCache` só aceita `script`, `style`, `image`, `document`, `font`, `/`, e
`/assets/*` (L81–82). Uma chamada RTDB é `fetch` com destino vazio e URL de
origem `*.firebaseio.com` — barrada duas vezes (L76 e L78). **`config/maintenance`
nunca entra no cache. CONFIRMADO.**

### 2.2 Versões — três convenções divergentes

| Onde | Valor |
|---|---|
| `app.js:728` — URL do registro | `navigator.serviceWorker.register('./sw.js?v=19')` |
| `sw.js:51` — nome do cache | `cinecash-v25` |
| `sw.js:98–112` — assets | `?v=4` (e `?v=1`, `?v=2` nos dois arquivos de App Check) |
| `index.html` do site | `?v=4` — **bate** com `SHELL_ASSETS` |

`?v=` no `?v=4` bate: `index.html` e `SHELL_ASSETS` usam a mesma versão, então o
precache não guarda chaves que ninguém pede.

O `?v=19` no registro do SW vs `cinecash-v25` vs `?v=4` nos assets são três
convenções que derivaram sem converge. **Não é bug funcional**: o navegador
compara **bytes** do script do SW, não a query, e `activate()` apaga caches
antigos pelo `CACHE_NAME`. Mas é sinal de que o nome do cache é **subido à mão**
e pode ficar desatualizado sem ninguém perceber — se alguém subir `CACHE_NAME`
para `v26` e esquecer de revisar um `SHELL_ASSETS`, os assets antigos ficam
órfãos até o `trimCache`.

**Classificação: `INDETERMINADO` — não é bug, é convenção frágil.**

### 2.3 `fetch` sem timeout (risco real de disponibilidade)

`sw.js:139–163` — `e.respondWith(fetch(e.request).then(...).catch(cache))`.
Se a rede **travar** (não cair), `fetch()` fica pendurado, o `.catch()` nunca
dispara, e `respondWith` nunca resolve. O usuário fica com a página carregando
para sempre — o fallback de cache existe, mas **não para este caso**.

Isso não é regressão e não explica a manutenção. É limitação conhecida de
network-first sem timeout. **Não alterei** — mexer na estratégia de cache do
site é fora do escopo do painel e tem risco de comportamento offline que não
consigo validar aqui.

**Classificação: `PENDENTE — decisão sua`.**

### 2.4 Documentos legais — intocado

`LEGAL_DOC_PATHS` (`/termos.html`, `/politica-privacidade.html`,
`/politica-cookies.html`) é regra de negócio sobre aceite e registro de
versão por SHA-256. **Não toquei, não converti link, não mexi em regra.** O
comentário em L54–63 explica o porquê e está correto.

---

## 3. Painel (`www/admin`)

### 3.1 Nenhum service worker é registrado — `MORTO COMPROVADO`

Busca por `serviceWorker` em **todo** `*.js` e `*.html` sob `www/admin`
(ignorando backups):

```
(vazio)
```

**Zero ocorrências.** Consequências, todas comprovadas:

| Arquivo | O que é | Status |
|---|---|---|
| `www/admin/sw.js` (1182 B) | handler de FCM, importa Firebase **9.6.1** | nunca registrado |
| `www/admin/firebase-messaging-sw.js` (641 B) | `skipWaiting()` + `clients.claim()` | nunca registrado |

Portanto **mensagem push em segundo plano não funciona no painel.** Não é bug —
é funcionalidade que nunca foi ligada. `utils.js` tem `getToken` 1 ocorrência, e
`utils.js` é o wrapper de App Check, não FCM; não achei chamada a
`messaging()`/`onMessage`/`requestPermission` em nenhum módulo do painel.

**Classificação: `MORTO COMPROVADO`.** **Não apaguei** — apagar exige confirmar
que nada depende, e um registro de SW pode estar sendo feito por script
servido dinamicamente que não está neste repositório (ver FASE 6/9).

### 3.2 Divergência de versão do Firebase entre `index.html` e `sw.js`

| Arquivo | Versão |
|---|---|
| `index.html:10–13` | Firebase **10.7.1** (`app`, `auth`, `database`, `messaging`) |
| `index.html:14` | `lib/firebase-app-check-compat.js` (local) |
| `www/admin/sw.js:2–3` | Firebase **9.6.1** (`app`, `messaging`) |

Um service worker roda em **escopo próprio**, com seu próprio escopo de globals.
`importScripts` de 9.6.1 ali é independente do `window` da página com 10.7.1.
Se alguém registrar o `sw.js` do painel hoje, teria duas versões compat do SDK
no mesmo worker — que **não** é a mesma situação da página, porque são contextos
de execução separados, mas continua sendo uma divergência que ninguém notou.

**Classificação: `INDETERMINADO` — latente, sem impacto hoje** (nada registra).

### 3.3 `sw.js` do painel não tem App Check

`www/admin/sw.js` não contém a string `appCheck`. O painel **exige** App Check
no backend (`FIREBASE-APPCHECK-AUDIT.md`, FASE 3). Se o `sw.js` fosse
registrado, `messaging.getToken()` exigiria App Check no próprio worker, que
não está lá.

**Classificação: `INDETERMINADO` — consequence de 3.1.**

### 3.4 Cache no painel: só `?v=`

Não há nenhum uso de `caches` / `CacheStorage` / `cacheName` em `www/admin`.
O único controle de cache é o cache-busting `?v=4.2.0` nas **14** tags
`<script>` (`index.html:426–439`) e no `<link>` do CSS.

**Consequência prática:** o painel **não tem risco de JS/CSS obsoleto por
service worker.** O risco é o oposto — se `?v=` não for suitability bumped a cada
mudança, o navegador pode reaproveitar o script antigo por cache heurístico
(`StaticFiles` do Starlette **não** define `Cache-Control`). É por isso que a
TAREFA 5.1/5.3 usou `?v=4.2.0`: é a única defesa.

**Classificação: `VALIDADO` (o `?v=` é necessário e está presente).**

---

## 4. Correção aplicada — 4.1

### 4.1 Backups de auditoria servidos pela raiz estática

`www/admin/` é a raiz estática do painel (ver `SECRETS-STATIC-EXPOSURE-AUDIT.md`).
Dentro dela estavam:

| Arquivo | Tamanho |
|---|---|
| `www/admin/index.html.bak-audit-20261005` | 28738 B |
| `www/admin/styles.css.bak-audit-20261005` | 68390 B |
| `www/admin/styles.css.truncado-20261005` | 2095 B |

Eles **não** eram bloqueados pela `GuardedStaticFiles` da TAREFA 6.1: nenhum
segmento começa com `.`, o primeiro segmento não é `backend`, e a extensão não
é `.env`/`.pem`/`.key`/`.p12`. Ficavam **HTTP 200**.

Não são segredos. Mas são **código removido servido publicamente** — incluindo a
versão de `styles.css` de antes do reparo dos `@import` de fonte, e o
`index.html` anterior à TAREFA 5.3. Quem visse isso não consegue entender o
estado atual do painel.

#### O que mudou no código

`backend/app/core/static_guard.py` ganhou um segundo conjunto de padrões, e ele
casa por **substring**, não por sufixo:

```python
BLOCKED_SUFFIXES: frozenset[str] = frozenset({".env", ".pem", ".key", ".p12"})

# Marcadores que, aparecendo em QUALQUER ponto do nome do arquivo, indicam
# cópia de trabalho. Aqui é SUBSTRING, não sufixo, e isso é deliberado.
BLOCKED_MARKERS: frozenset[str] = frozenset({".bak", ".truncado"})
```

E o ponto 5 da função pura:

```python
# 5. cópia de trabalho (.bak / .bak-audit-AAAAmmdd / .truncado-AAAAmmdd).
#    Substring, porque a data fica no FIM do nome.
return any(marker in last for marker in BLOCKED_MARKERS)
```

#### Por que substring e não sufixo

Escrevi primeiro com `BLOCKED_SUFFIXES` e `.bak-audit-`, casando com
`last.endswith(suf)`. **Não funcionaria**, e a razão é concreta: os backups
deste projeto carregam data no fim do nome.

```
styles.css.bak-audit-20261005   termina em "-20261005"
styles.css.truncado-20261005    termina em "-20261005"
```

`endswith(".bak-audit-")` é `False` para os dois. Os arquivos teriam
continuado em HTTP 200, e um teste que só conferisse o código teria passado.

Por isso existe o teste
`test_marcadores_de_backup_casam_por_substring_nao_por_sufixo`, que **afirma as
três negativas** antes de afirmar que o caminho é bloqueado:

- `not nome.endswith(".bak")`
- `not nome.endswith(".bak-audit-")`
- `not nome.endswith(".truncado")`
- `is_blocked_static_path(nome) is True`

Se alguém trocar substring por sufixo de novo, esse teste falha.

`.bak` como marcador cobre também `app.js.bak-lgpd-20261003` e qualquer `.bak`
simples que apareça depois, sem precisar de lista de variantes.

#### Nenhum asset legítimo foi engolido

`test_marcador_nao_engole_asset_legitimo` fixa a lista do que precisa continuar
servido: `index.html`, `styles.css`, `sw.js`, `firebase-messaging-sw.js`,
`favicon.svg`, `icons.svg`, `LEIA-ME.txt`, `js/main.js`,
`js/modules/maintenance.js`, `lib/chart.js`.

Verificado também em HTTP real por `_verify_static_backups.py`: **14 assets do
painel em 200**, incluindo `js/modules/maintenance.js` (19895 B) e
`js/modules/watch.js` (17020 B).

#### Backups no disco, intocados

Nenhum `.bak-audit-*` ou `.truncado-*` foi apagado — apenas deixou de ser
servido.

---


## 5. Classificação final por item

| # | Item | Arquivo | Classificação |
|---|---|---|---|
| 4.1 | Backups `.bak-audit-*` / `.truncado-*` servidos | `www/admin/*` | `CORRIGIDO` |
| 4.2 | `fetch` sem timeout no SW do site | `CineCash-por-IA/www/sw.js:139` | `PENDENTE` |
| 4.3 | `sw.js` e `firebase-messaging-sw.js` nunca registrados (painel) | `www/admin/` | `MORTO COMPROVADO` |
| 4.4 | Firebase 9.6.1 no `sw.js` vs 10.7.1 no `index.html` | `www/admin/sw.js:2` | `INDETERMINADO` |
| 4.5 | `CACHE_NAME='cinecash-v25'` vs `sw.js?v=19` vs `?v=4` | site | `INDETERMINADO` |
| 4.6 | `www/admin/estyle/` — diretório vazio | `www/admin/estyle/` | `MORTO COMPROVADO` (0 arquivos) |
| 4.7 | Documentos legais fora do cache | site `sw.js:54–63` | `UTILIZADO DINAMICAMENTE` — **não alterado por regra de negócio** |
| 4.8 | RTDB fora do cache (mantutenção não é artefato de cache) | site | `VALIDADO` |

---

## 6. Validações

Todas executadas em `C:\Users\Alegomes\Desktop\Painel gerenciamento`, branch
`main`, HEAD `7c7caec`, **working tree sujo — nada commitado**.

### 6.1 Antes e depois da correção 4.1

| Verificação | Antes de 4.1 | Depois de 4.1 |
|---|---|---|
| `GET /index.html.bak-audit-20261005` | **200** (28738 B) | **404** |
| `GET /styles.css.bak-audit-20261005` | **200** (68390 B) | **404** |
| `GET /styles.css.truncado-20261005` | **200** (2095 B) | **404** |

### 6.2 Estado final

| Verificação | Comando | Resultado |
|---|---|---|
| Suite completa | `python -m pytest -q` | **151 passed** (era 143; +8 de 4.1) |
| Guarda de estáticos | `python -m pytest tests/test_static_guard.py -q` | **60 passed** (era 52) |
| Backups barrados, assets intactos | `python _verify_static_backups.py` | **exit 0** — 3 backups em 404, 14 assets em 200, 3 segredos em 404, `index.html` íntegro |
| Segredos barrados | `python _verify_static_guard.py` | **exit 0** — 12 proibidos em 404, 7 assets em 200 |
| Prova do estado anterior | `python _verify_static_exposure.py` | **exit 1 — esperado**, é a prova do vazamento com `StaticFiles` puro |
| Sintaxe Python | `python -m compileall backend` | **exit 0** |
| Lint nos arquivos tocados | `python -m ruff check` (4 arquivos) | **All checks passed** |
| Sintaxe JS do painel | `node --check` em todos os `.js` sob `www/admin/js` | **exit 0** (nenhum JS alterado nesta fase) |
| Harness TAREFA 5.1 | `node _verify_maintenance_js.cjs` | exit 0 |
| Harness TAREFA 5.3 | `node _verify_maintenance_card.cjs` | exit 0 |

### 6.3 Assets confirmados intactos após a guarda

```
GET /index.html                           -> 200  (35755 B)
GET /styles.css                           -> 200  (87288 B)
GET /sw.js                                -> 200  (  1184 B)
GET /firebase-messaging-sw.js             -> 200  (   641 B)
GET /favicon.svg                          -> 200  (   212 B)
GET /icons.svg                            -> 200  (  6741 B)
GET /LEIA-ME.txt                          -> 200  (  2631 B)
GET /js/main.js                           -> 200  (  6355 B)
GET /js/utils.js                          -> 200  (  4776 B)
GET /js/config.js                         -> 200  (  2572 B)
GET /js/modules/maintenance.js            -> 200  ( 19895 B)
GET /js/modules/watch.js                  -> 200  ( 17020 B)
GET /js/modules/settings.js               -> 200  (  1761 B)
GET /lib/firebase-app-check-compat.js     -> 200  ( 23375 B)
```

### 6.4 Nenhum arquivo apagado, nenhum commit

- `.bak-audit-20261005` e `.truncado-20261005` continuam **no disco** — só
  deixaram de ser servidos.
- `.gitignore.bak-audit-20261005` e `backend/app/main.py.bak-audit-20261005`
  (da TAREFA 6.1) preservados, nunca sobrescritos.
- `git log --oneline -1` continua `7c7caec`.
- Arquivos novos desta fase: `CACHE-SERVICE-WORKER-AUDIT.md`,
  `_verify_static_backups.py`, e os casos novos em
  `tests/test_static_guard.py`. Nenhum precisa de backup — são novos.

---

## 7. Como reproduzir

```powershell
# SITE: confirma que config/maintenance nao passa por shouldCache
Select-String -Path "C:\Users\Alegomes\Desktop\CineCash-por-IA\www\sw.js" `
  -Pattern "CACHE_NAME|IGNORE_DOMAINS|url.origin|LEGAL_DOC_PATHS|MAX_CACHE_ITEMS"

# SITE: confirma o registro do service worker
Select-String -Path "C:\Users\Alegomes\Desktop\CineCash-por-IA\www\app.js" `
  -Pattern "serviceWorker.register"

# PAINEL: zero registros de service worker (saida esperada: vazio)
Get-ChildItem -Recurse -Include *.js,*.html -Path www\admin |
  Where-Object { $_.Name -notlike "*bak-audit*" } |
  Select-String -Pattern "serviceWorker" -SimpleMatch

# PAINEL: versoes de Firebase no index.html vs sw.js
Select-String -Path www\admin\index.html, www\admin\sw.js -Pattern "firebasejs/"

# Item 4.1: backups barrados, assets intactos
python _verify_static_backups.py
python -m pytest tests/test_static_guard.py -q
```

Saídas esperadas:

| Comando | Resultado |
|---|---|
|PAINEL + `serviceWorker` | **vazio** |
| `python _verify_static_backups.py` | `exit 0` |
| `python -m pytest tests/test_static_guard.py -q` | `60 passed` |
| `python -m pytest -q` | `151 passed` |

---

## 8. Estado

**CÓDIGO TECNICAMENTE CORRIGIDO E AUDITADO, COM EVIDÊNCIAS LOCAIS;
PRODUÇÃO AINDA NÃO LIBERADA.**

Não afirmo que o cache esteja correto em toda hipótese. Afirmei, com leitura: o
SW do site é network-first, o nó `config/maintenance` não passa por
`shouldCache`, o painel não registra service worker nenhum, e o `?v=4.2.0` é a
única — e presente — defesa contra script obsoleto no painel.