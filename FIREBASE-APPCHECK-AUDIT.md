# FIREBASE-APPCHECK-AUDIT — FASE 3

**Data:** 2026-10-05
**Branch:** `main` — HEAD `7c7caec feat(appcheck): frontend patches + rebranding CyberCore IA v4.0`
**Classificação:** `PENDENTE` — **nenhuma alteração feita**, por decisão deliberada
**Escopo:** painel admin (`Painel gerenciamento`)

---

## 1. Resumo

Investiguei a pendência `403 exchangeRecaptchaEnterpriseToken` e o
`app-check/throttled`. **Não alterei nenhum arquivo**, porque App Check é
Firebase e a regra do projeto proíbe mexer em Firebase sem sua autorização
explícita. O que segue é diagnóstico com evidência, mais três defeitos
**comprovados no código** que precisam da sua decisão.

O achado mais importante não é o 403: é que o painel **não consegue falar com o
backend em nenhum ambiente**, porque a URL da API está fixada em
`http://localhost:7861`. Isso está detalhado em `ADMIN-PANEL-CONNECTION-AUDIT.md`
(FASE 5) e é causa suficiente para explicarchamar falhando porApp Check — porque
`localhost:7861` nunca emite token de produção válido.

---

## 2. Estado real do App Check

### 2.1 Backend — `backend/app/middleware/appcheck.py`

| Item | Valor medido |
|---|---|
| Enforcement | `os.getenv("APP_CHECK_REQUIRED", "true")` → **ativo por padrão** |
| Escopo | só `/api/*` e `/payments/*` (L158) |
| Preflight `OPTIONS` | não exige (L152) |
| Excluídos do App Check | `/health`, `/docs`, `/redoc`, `/openapi.json`, `/favicon.ico`, `/favicon.svg` + prefixos `/payments/webhook`, `/api/monitor/report`, `/payments/auto-approve/`, `/api/auto-approve/` (L30–43) |
| Sem header | **401** `X-Firebase-AppCheck header required` (L168) |
| Token inválido | **401** (L174) |
| Serviço indisponível (rede) | **503** (L172) |

Validação via REST `appcheck.googleapis.com/v1/.../apps/{app_id}:verifyToken`
(L25–27), porque o SDK Python `firebase-admin` não expõe
`app_check.verify_token()` — o docstring diz isso corretamente.

### 2.2 Frontend — `www/admin/js/utils.js` + `js/config.js`

| Item | Valor medido |
|---|---|
| Site key reCAPTCHA Enterprise | `6Leds3UtAAAAAGsYCTgVeGmQQfyzmSZc_KC73Wzs` (`config.js:24`) |
| Ativação | `firebase.appCheck().activate(new ReCaptchaEnterpriseProvider(key))` (`config.js:30`) |
| Instância exposta | `window.__appCheckInstance` (`config.js:42`) |
| Injeção do header | `utils.js:27` (fetch), `utils.js:29` (fetch, objeto), `utils.js:61` (XHR) |
| Ordem de carga | `config.js` L426 → `utils.js` L427 — **correta**: o interceptor só existe depois de `activate()` |

**A cadeia está bem montada.** O `fetch` global é substituído antes de qualquer
código de módulo rodar.

### 2.3 `403 exchangeRecaptchaEnterpriseToken`

Este erro vem do **SDK JS no navegador**, não do backend. Ele significa: o
`getToken()` falhou ao trocar a site key por um token App Check.

Causas possíveis, **nenhuma verificável sem acesso ao Console do Firebase**:

1. A site key é de **reCAPTCHA Enterprise** mas o provider do App Check no
   Console está registrado como `reCAPTCHA v3` (ou vice-versa). O código pede
   `ReCaptchaEnterpriseProvider`, então o Console precisa ter Enterprise.
2. O projeto Firebase não tem **App Check ativado** para o app
   `1:563829659490:web:db9c377615bb5da941fe3b`, ou tem com enforce desligado.
3. A chave está com **restrição de domínio** (HTTP referrer) e o domínio real do
   painel não está na lista.
4. **A chave é de um projeto diferente.** `config.js:24` é hardcoded e não bate
   com `FIREBASE_APP_ID` por construção — não há como validar isso sem o Console.

O que **posso afirmar** é que `.env:30` tem `FIREBASE_APP_ID` definido e
`.env` está presente no ambiente de desenvolvimento, e o `config.py` faz
`raise RuntimeError` no startup se faltar `FIREBASE_SERVICE_ACCOUNT`. Logo,
**se o painel está no ar, o `APP_CHECK_REQUIRED` está ativo em produção** —
isto é, o 401 do backend está de fato sendo exercitado.

---

## 3. Defeitos **comprovados** (não corrigidos — aguardam sua decisão)

### 3.1 `429` do Google é reportado ao usuário como "token inválido"

`appcheck.py:138–145`:

```python
if resp.status_code == 200:
    return True
if resp.status_code in (400, 401, 403):
    return False
logger.error(f"[AppCheck] Erro inesperado da API: {resp.status_code} ...")
return False          # <-- 429 cai aqui
```

O `verifyToken` do Google **tem limite de taxa**. Quando estoura, responde
**429**. O código cai no `return False` final → `dispatch` devolve **401 "App
Check token invalid"**.

Cadeia de realimentação:

```
429 do Google
  → backend devolve 401 "token invalid"
  → o frontend interpreta "token ruim" e chama getToken(forceRefresh)
  → mais uma troca de token no Google
  → mais throttling
```

Isso é a explicação mecânica do `app-check/throttled` observado. O
`httpx.post` de L133 é feito **síncrono** dentro do `dispatch`, um por
requisição, sem cache — cada chamada de API do painel gera **uma** verificação
remota ao Google. Não há memoização do token verificado.

**Correção proposta (não aplicada):** distinguir 429 de token inválido e
devolver 503 com `Retry-After`, que é o que o `dispatch` já faz para erro de
rede (L172). Uma linha de mudança de comportamento, mas mexe em App Check.

### 3.2 `XMLHttpRequest.prototype.send` virou `async`

`utils.js:55`:

```js
XMLHttpRequest.prototype.send = async function(body) {
    ...
    const token = await getAppCheckToken(false);
    ...
    return _originalXhrSend.apply(this, arguments);
};
```

A especificação de XHR exige que `send()` retorne **`undefined`**. Com `async`,
passa a retornar uma `Promise`. Além disso o envio é **adiado** em um microtask
ou mais (espera a rede do Google) — o que muda a ordem observável: qualquer
código que faça `xhr.send(); xhr.abort();` aborta **antes** do envio, e o
`send` pendente dispara mesmo assim.

Nenhuma falha medida hoje porque o painel **não usa XHR** — todas as ~25
chamadas usam `fetch`. Então isto é `INDETERMINADO` quanto a impacto real, e
`MORTO COMPROVADO` quanto ao caminho de execução: nenhum `new XMLHttpRequest`
no painel.

### 3.3 O interceptor anexa o token a qualquer URL que contenha `/api/`

`utils.js:21` e `utils.js:57`:

```js
const isApiCall = url.includes('/api/') || url.includes(window.location.hostname);
```

Isto é uma **comparação de substring, não de origem**. Uma requisição para
`https://qualquer-coisa.example/api/x` satisfaz `includes('/api/')` e recebe o
`X-Firebase-AppCheck`.

Verifiquei se isso é explorável hoje:

- `window.__BACKEND_URL__` **não é definido por nada no repositório** — nem
  servidor, nem build, nem script inline no `index.html`. Logo não é
  manipulável por devtools sem XSS.
- `LOCAL_BACKEND` é constante de código (`config.js:49`).
- O comentário em `config.js:50–52` documenta **exatamente** esse risco e diz que
  a URL **nunca** é lida de `localStorage`. A mitigação existe e está correta.

**Classificação: `NÃO ALTERADO POR SEGURANÇA` / risco latente.** A proteção
atual é "ninguém controla `window.__BACKEND_URL__`", não "o interceptor checa
origem". Se alguém um dia injetar essa variável (que é o propósito declarado
dela), o interceptor passa a mandar o token para qualquer host que o
`__BACKEND_URL__` apontar, sem verificar que é o mesmo host da página.

O conserto correto é comparar `new URL(url, location.href).origin` com
`location.origin` antes de anexar o header. **Não apliquei** — é Firebase.

---

## 4. Verificações que passaram (o que NÃO está quebrado)

| Verificação | Resultado |
|---|---|
| Ordem de carregamento `config.js` → `utils.js` | correta |
| `window.__appCheckInstance` definido antes de qualquer `getToken()` | sim (`config.js:42` antes de `utils.js:2`) |
| Token ausente → 401 (fail-closed) | sim (`appcheck.py:168`) |
| Erro de rede → 503 (fail-closed, **não** fail-open) | sim (`appcheck.py:172`) — este ponto está **certo** |
| Estáticos (`/`, `/js/*`, `/styles.css`) não exigem App Check | sim (`appcheck.py:158`) |
| `POST /api/auto-approve/` isento de App Check **e** de `admin_auth_middleware` | **não é bypass de autenticação** — a rota faz a própria checagem (`payments.py:290–313`): `hmac.compare_digest` do `X-N8N-Secret`, ou Firebase ID token + `is_admin_user`. Com `N8N_SHARED_SECRET` vazio, `is_n8n` é `False` e cai no Firebase admin → fail-closed. |
| `SIMULATION_MODE` impede chamada real ao Asaas | sim (`payments.py:356`) |
| `main.py` não gained novos achados de ruff nesta fase | confirmado, nenhuma edição feita |

**Sobre a isenção de App Check no auto-approve:** é correta, não um buraco. O
N8N não tem como obter um token de App Check — ele não roda no navegador. A
isenção existe para o webhook, e a autenticação foi feita dentro da rota.

---

## 5. Bug de documentação dentro do próprio arquivo

`appcheck.py:7–9`:

```
Desativado por padrão (APP_CHECK_REQUIRED=false) para não quebrar o fluxo atual —
o frontend ainda não envia X-Firebase-AppCheck.
```

As duas frases são falsas hoje:

- `appcheck.py:53` → padrão é **`"true"`**, não `false`.
- `utils.js` **envia** `X-Firebase-AppCheck` (3 pontos de injeção).

Quem ler esse docstring hoje monta o `.env` com `APP_CHECK_REQUIRED=false`
achando que é o padrão. É um arquivo de comentário — **correção sem risco**,
mas deixei intacto para não mexer em App Check sem sua autorização.

---

## 6. Riscos de configuração em produção

`.dockerignore` exclui `.env`, `.env.*`, `**/.env`, `**/.env.*`
(deliberadamente, para não vazar credenciais na imagem). Logo, dentro do
container **não existe `.env`** — `load_dotenv()` (`config.py:4`) não acha nada
e `os.path.exists("firebase-adminsdk.json")` (`config.py:21`) também é falso
porque a chave está fora do contexto de build.

Resultado: **todo o `APP_CHECK_*`, `FIREBASE_APP_ID`, `WEBHOOK_SECRET` e
`ALLOWED_ORIGINS` precisa vir de variável de ambiente do host** (no caso de HF
Spaces, de *Variables and secrets*).

É exatamente por isso que `config.py:38–41` faz `raise RuntimeError` no startup:
sem essas variáveis o processo **não sobe**. É fail-closed e alto — bom
comportamento. E é a evidência de que, se o painel está no ar, as variáveis
estão lá.

| Situação | Efeito |
|---|---|
| Variáveis todas presentes | App Check ativo, `verifyToken` chamado a cada requisição |
| `APP_CHECK_REQUIRED=false` | App Check desligado, painel funciona sem token |
| Falta qualquer essencial | `RuntimeError` no import — **app não sobe** |

`INDETERMINADO`: não consigo ver as variáveis do Space. Não consigo afirmar se
`FIREBASE_APP_ID` bate com o app onde a site key está registrada — essa é
exatamente a verificação que fecha o `403`.

---

## 7. Como reproduzir

```powershell
# cadeia de enforce
python -c "print(open(r'backend/app/middleware/appcheck.py',encoding='utf-8').read().count('APP_CHECK_REQUIRED'))"

# header injetado pelo frontend
python -c "print(open(r'www/admin/js/utils.js',encoding='utf-8').read().count('X-Firebase-AppCheck'))"

# o 429 cai no return False?
# appcheck.py L138-145  -> ler

# testes existentes de appcheck
python -m pytest tests/test_appcheck.py tests/test_appcheck_middleware.py -q
```

---

## 8. Pendências que dependem de você

1. **Verificar no Console do Firebase** se `6Leds3UtAAAAAGsYCTgVeGmQQfyzmSZc_KC73Wzs`
   está como **Enterprise**, e se App Check está ativado e em *enforce* para
   `1:563829659490:web:db9c377615bb5da941fe3b`. Sem isso o `403` não fecha.
2. **Decidir sobre o `429` → 401** (achado 3.1). Recomendo corrigir: hoje o
   throttling é reportado ao usuário como erro de credencial.
3. **Decidir sobre o docstring falso** (achado 5). Correção de comentário, sem
   risco.
4. **Decidir sobre a checagem de origem** no interceptor (achado 3.3).
   Recomendo fortemente: hoje a proteção é indireta.

Nenhuma dessas três mudanças foi feita.

---

## 9. Estado

**CÓDIGO TECNICAMENTE AUDITADO, COM EVIDÊNCIAS LOCAIS; PRODUÇÃO AINDA NÃO
LIBERADA.**

Não afirmo que o App Check esteja funcionando. Afirmei, com leitura de código: a
cadeia de header está montada corretamente, o backend falha fechado em três
situações distintas, o `429` é indevidamente reportado como token inválido, e o
`403` só pode ser fechado no Console do Firebase. **`FIREBASE-APPCHECK-AUDIT`
— `PENDENTE`.**