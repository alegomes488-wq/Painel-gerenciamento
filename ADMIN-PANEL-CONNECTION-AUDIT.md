# ADMIN-PANEL-CONNECTION-AUDIT — FASE 5

**Data:** 2026-10-05
**Branch:** `main` — HEAD `7c7caec feat(appcheck): frontend patches + rebranding CyberCore IA v4.0`
**Classificação:** `PENDENTE` — **nenhuma alteração feita**, causa é decisão de configuração
**Escopo:** `www/admin/js/config.js` e a cadeia `BRASILHEXA_BACKEND_URL`
**Severidade:** a mais alta que encontrei nesta auditoria

---

## 1. Resumo

O painel admin **não tem como falar com o backend em nenhum ambiente**, incluindo
produção. A URL da API está fixada em código como constante de
desenvolvimento, e o mecanismo previsto para substituí-la **não existe em lugar
nenhum do repositório**.

```js
// www/admin/js/config.js:49
const LOCAL_BACKEND = 'http://localhost:7861';

// www/admin/js/config.js:53-55
const BRASILHEXA_BACKEND_URL = (typeof window !== 'undefined' && window.__BACKEND_URL__)
    ? window.__BACKEND_URL__
    : LOCAL_BACKEND;
```

`window.__BACKEND_URL__` **não é definido por nada.** Não é injetado pelo
FastAPI, não é substituído no build, não está em script inline no `index.html`,
não está em nenhum arquivo do repositório. Portanto, em qualquer navegador, em
qualquer ambiente, `BRASILHEXA_BACKEND_URL` vale `http://localhost:7861`.

Isto explica por que o painel reflete `config/maintenance = true` (que vem
direto do RTDB, pela SDK do Firebase no cliente — caminho que **não** depende
deste backend) mas **não consegue acionar o botão de manutenção** que eu
implementei na TAREFA 5.1/5.3: aquele botão chama
`POST ${BRASILHEXA_BACKEND_URL}/api/admin/maintenance`, que em produção aponta
para a porta 7861 da máquina de quem está com o painel aberto na tela.

---

## 2. Evidência

### 2.1 `window.__BACKEND_URL__` não existe em lugar nenhum

Busca por `__BACKEND_URL__` em todo `www/admin` (ignorando backups):

```
www/admin/js/config.js:52   // ... injetada no build/servidor (window.__BACKEND_URL__), nunca ...
www/admin/js/config.js:53   const BRASILHEXA_BACKEND_URL = (typeof window !== 'undefined' && window.__BACKEND_URL__)
www/admin/js/config.js:54       ? window.__BACKEND_URL__
```

Três ocorrências, **todas as três dentro do próprio `config.js`**: uma no
comentário que descreve o mecanismo, e duas na expressão que o implementa. Zero
definições.

Busca por `__BACKEND_URL__` em todo `backend/**/*.py`: **zero ocorrências.** O
FastAPI não injeta.

`index.html` L426–439: os 14 `<script>` são todos `<script src="js/...">`.
Nenhum inline, nenhum `data-` attribute, nada que defina a variável.

### 2.2 O comentário promete uma coisa que não existe

`config.js:50–52`:

```
// TAREFA 3.9: backend URL fixa — NUNCA lida de localStorage (atacante poderia
// redirecionar todas as chamadas). Override de desenvolvedor apenas via variável
// injetada no build/servidor (window.__BACKEND_URL__), nunca armazenamento do usuário.
```

A **intenção** está certa e é boa: ler a URL de `localStorage` seria um vetor
de redirecionamento trivial, e alguém já pensou nisso. O que falta é a
implementação do segundo caminho. O override "existe" na forma de uma leitura de
variável que ninguém escreve.

### 2.3 Quantas chamadas dependem disso

| Arquivo | Linhas | Chamada |
|---|---|---|
| `js/auth.js` | 19 | `${BRASILHEXA_BACKEND_URL}/api/auth/refresh-admin-claim` |
| `js/main.js` | 141 | `${BRASILHEXA_BACKEND_URL}/api/secops/summary` |
| `js/modules/maintenance.js` | 405, 477 | `${BRASILHEXA_BACKEND_URL}/api/admin/maintenance` |
| `js/modules/secops.js` | 34, 96, 242, 294 | `/api/secops/risk-analysis/{wid}`, `/api/secops/summary`, `/api/secops/health-audit` |
| `js/modules/settings.js` | 27 | `${BRASILHEXA_BACKEND_URL}/api/admin/config` |
| `js/modules/status.js` | 2 | `${BRASILHEXA_BACKEND_URL}/health` |
| `js/modules/users.js` | 25 | `${BRASILHEXA_BACKEND_URL}/api/admin/ban` |
| `js/modules/watch.js` | 71, 230, 287, 314 | `baseUrl` para `/api/project/*` |
| `js/modules/withdrawals.js` | 144 | `${BRASILHEXA_BACKEND_URL}/payments/approve/{wid}` |

**10 arquivos, 9 deles consumidores** (o décimo é o `config.js` que define a constante):

```
auth.js 1 | config.js 1 (a definição) | main.js 1
maintenance.js 2 | secops.js 4 | settings.js 1 | status.js 2
users.js 1 | watch.js 4 | withdrawals.js 1
```

**18 referências no total.** Incluindo o `POST /api/admin/maintenance` da TAREFA
5.1, o `/api/admin/ban` e o `/payments/approve/{wid}` — aprovação de saque.

**Painel funcionalmente completo depende desta constante estar certa. E ela
não está.**

Isso vale inclusive para `status.js`, que é o que escreve o indicador
`✓ ONLINE` / `✗ OFFLINE`: em produção ele também mede `localhost:7861`, então o
painel mostra o backend como offline mesmo com a API no ar.

### 2.4 `CORS` reforça o problema

`.env:16`:

```
ALLOWED_ORIGINS=http://localhost:8080,https://seu-dominio.com
```

Dois placeholders: `localhost:8080` (nunca será o painel real) e
`seu-dominio.com` (domínio de exemplo). Mesmo que `__BACKEND_URL__` fosse
injetado corretamente, o CORS do backend rejeitaria a origem real do painel —
`allow_origins` não inclui o domínio de produção.

E `.env` **não vai para a imagem**: `.dockerignore` exclui `.env`, `.env.*`,
`**/.env`, `**/.env.*`. Então em produção o `ALLOWED_ORIGINS` também precisa vir
de variável de ambiente do host.

### 2.5 Os dois caminhos de configuração são incoerentes entre si

| | `ALLOWED_ORIGINS` em `.env` | `ALLOWED_ORIGINS` em `.env.example` |
|---|---|---|
| valor | `http://localhost:8080, https://seu-dominio.com` | `https://admin.seudominio.com, https://app.seudominio.com` |

Os dois são placeholders, e **são placeholders diferentes**. Nenhum dos dois é
um domínio real. Quem copiar `.env.example` para `.env` recebe um conjunto
diferente de quem copiou o `.env` atual.

---

## 3. Agravante: o token de App Check viaja para `localhost:7861` em texto claro

O interceptor de App Check (`utils.js:21`) anexa o header a qualquer URL que
contenha `/api/`:

```js
const isApiCall = url.includes('/api/') || url.includes(window.location.hostname);
```

`http://localhost:7861/api/admin/maintenance` satisfaz `includes('/api/')`, então
recebe `X-Firebase-AppCheck`. Combinado com `http://` (não `https://`), isso
significa que, **se** algo estiver escutando na porta 7861 da máquina do
administrador, ele recebe o token de App Check em texto claro.

**Classificação deste ponto: `INDETERMINADO` quanto a exploited; o vetor
existe e é trivial de fechar.** Em produção, `localhost:7861` normalmente não
tem nada — a conexão é recusada. Mas a proteção atual é "não há servidor
nessa porta", não "o token não sai para fora". E se o `__BACKEND_URL__` for
injetado apontando para um host externo por alguém tentando consertar isso
errado, o token vai para esse host.

---

## 4. Por que isso é `PENDENTE` e não `CORRIGIDO`

Consertar exige escolher **um** destino, e a escolha é sua:

| Opção | O que implica | Risco |
|---|---|---|
| **A. Relativa** — `BRASILHEXA_BACKEND_URL = ''` | API vira mesma-origem: `fetch('/api/...')` | Correto se painel e API forem servidos pelo **mesmo** host. E são: `main.py:157` monta o painel em `/` e as rotas em `/api/*`, **no mesmo app FastAPI**. |
| **B. Absoluta por build** | Gerar `config.js` no startup com o host real | Correto para host separado, mas exige passo de build |

**A é a resposta óbvia pela arquitetura**, e é por isso que não vou assumir:
o `LOCAL_BACKEND` é constante de código, e mudar a forma de resolução da URL
toca em **todos os 15 sítios** de uma vez e em **autenticação** (o token de
login vai no `Authorization`). A regra do projeto proíbe mexer em
autenticação sem sua autorização explícita.

Detalhe que reforça A: `main.py:157` monta `StaticFiles` em `/`, e o painel é
servido **pelo mesmo processo FastAPI** que expõe os 5 routers (`payments`,
`secops`, `projects`, `admin`, `project_router`) em `/api/*` e `/payments/*`. Então o backend
está, por construção, na mesma origem do painel. A opção A não é apenas mais
simples — é a que corresponde ao que o código já faz.

O que **não** vou fazer sem você decidir:

- Trocar `LOCAL_BACKEND` por `''` — mexe em 15 chamadas de API e no caminho de
  autenticação.
- Injetar `window.__BACKEND_URL__` no `index.html` — isso é HTML de produção.
- Mexer em `ALLOWED_ORIGINS` — valor de produção que eu não conheço.

---

## 5. Pendências relacionadas

| # | Pendência | Classificação |
|---|---|---|
| 5.1 | `BRASILHEXA_BACKEND_URL` = `http://localhost:7861` sempre | `PENDENTE` — decisão sua |
| 5.2 | `window.__BACKEND_URL__` nunca definido | `PENDENTE` — decisão sua |
| 5.3 | `ALLOWED_ORIGINS` são placeholders, e diferentes entre `.env` e `.env.example` | `PENDENTE` — preciso do domínio real |
| 5.4 | Token de App Check enviado em texto claro para `localhost:7861` | `INDETERMINADO` |
| 5.5 | Comentário em `config.js:50–52` promete override que não existe | `VALIDADO` como documentação incorreta |
| 5.6 | `is_admin_user` com fallback por `ADMIN_EMAIL` | `PENDENTE` — ainda não revisado |

---

## 6. Como reproduzir

```powershell
# 1. A variavel nao e definida em lugar nenhum (esperado: so o proprio config.js)
Get-ChildItem -Recurse -Include *.js,*.html -Path www\admin |
  Where-Object { $_.Name -notlike "*bak-audit*" } |
  Select-String -Pattern "__BACKEND_URL__"

# 2. O backend nao injeta (esperado: vazio)
Get-ChildItem -Recurse -Filter *.py -Path backend\app |
  Where-Object { $_.Name -notlike "*bak-audit*" } |
  Select-String -Pattern "__BACKEND_URL__"

# 3. Quantos sitios dependem da constante
Get-ChildItem -Recurse -Filter *.js -Path www\admin\js |
  Where-Object { $_.Name -notlike "*.bak*" } |
  Select-String -Pattern "BRASILHEXA_BACKEND_URL" |
  Group-Object Filename |
  Select-Object Name, Count

# 4. Confirmar que o painel e a API sao servidos pelo mesmo processo
Select-String -Path backend\app\main.py -Pattern "ADMIN_DIR|app.mount|include_router"
```

Saídas esperadas: passos 1 e 2 devolvem **só** as 3 ocorrências de
`config.js` e **nada** no backend; passo 3 devolve 10 arquivos; passo 4 mostra
`ADMIN_DIR` + `app.mount("/")` + os `include_router` no mesmo `main.py`.

---

## 7. Estado

**CÓDIGO TECNICAMENTE AUDITADO, COM EVIDÊNCIAS LOCAIS; PRODUÇÃO AINDA NÃO
LIBERADA.**

Este achado muda a leitura do problema original. O site em manutenção **não é**
problema de cache nem de App Check: `config/maintenance = true` no RTDB, lido
direto pela SDK do Firebase no navegador, sem passar por nenhum destes
caminhos. E o painel **não** consegue corrigir isso em produção porque o
endpoint que ele chamaria está apontado para `localhost:7861`.

**`ADMIN-PANEL-CONNECTION-AUDIT` — `PENDENTE`.** Não afirmo que a opção A seja
correta; afirmo que é a que corresponde à arquitetura atual do `main.py`, e que
a decisão de mudar 15 chamadas de API é sua.