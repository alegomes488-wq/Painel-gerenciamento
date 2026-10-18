# TAREFA 6.1 — EXPOSIÇÃO DE SEGREDOS PELA RAIZ ESTÁTICA DO PAINEL

**Data:** 2026-10-05
**Branch:** `main` — HEAD `7c7caec feat(appcheck): frontend patches + rebranding CyberCore IA v4.0`
**Classificação:** `CORRIGIDO` (com risco residual operacional registrado abaixo)

---

## 1. Resumo

Auditoria contínua. Ao procurar as pendências de App Check (FASE 3), encontrei
uma condição pior e **comprovada**: o painel servia, por HTTP, uma chave privada
do Firebase Admin SDK e um arquivo `.env` com credenciais de API.

| Item | Antes | Depois |
|---|---|---|
| `GET /backend/.env` | **200** (720 bytes, começa com `GROQ_API_KEY=`) | 404 |
| `GET /backend/firebase-adminsdk.json` | **200** (contém `BEGIN PRIVATE KEY`) | 404 |
| `GET /backend/Dockerfile` | **200** | 404 |
| `GET /backend/app/main.py` | **200** (backend inteiro) | 404 |
| `git add .` commitaria a chave | **sim** (`.gitignore` não cobria) | não (ignorado) |

Uma chave Admin SDK do Realtime Database dá **leitura e escrita totais** no
`playearn-b001b`, sem passar pelas regras do RTDB nem por App Check. A chave
Auth usada pelo painel no cliente é pública por natureza; a do Admin SDK não.

**Não escrevi nada em produção. Não commitei nada. Não apaguei nenhum arquivo.**

---

## 2. Causa raiz

Duas causas independentes que se somaram.

### 2.1 `StaticFiles` puro na raiz `/`

```
backend/app/main.py:27   ADMIN_DIR = os.path.join(PROJECT_ROOT, "www", "admin")
backend/app/main.py:157  app.mount("/", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
```

`www/admin/` é ao mesmo tempo **a raiz estática do painel** e **o diretório onde
acabou uma cópia do backend** (`www/admin/backend/`, 52 arquivos). O
`StaticFiles` do Starlette entrega qualquer arquivo que consiga abrir.
`html=True` altera apenas o índice de diretório — **não restringe extensão nem
tipo de arquivo**. E o mount está na raiz `/`, sem prefixo que isole subpastas.

### 2.2 `.gitignore` ancorado na raiz do projeto

O `.gitignore` protegia a chave com caminho explícito:

```
backend/firebase-adminsdk.json
```

Isso casa **apenas** com `backend/` na raiz do repositório. A cópia aninhada em
`www/admin/backend/firebase-adminsdk.json` — byte-idêntica à original
(`sha1` `297c4f22…`) — **não era coberta** e aparecia como `??` no `git status`.
Um `git add .` normal teria versionado a chave privada.

---

## 3. Evidência

### 3.1 As três chaves encontradas

Todas para `project_id = playearn-b001b`, todas com `private_key` válido
(`-----BEGIN PRIVATE KEY`, 1704 caracteres):

| Caminho | `private_key_id` | `sha1` (16) | Git |
|---|---|---|---|
| `backend/firebase-adminsdk.json` | `99dffeaa…` | `297c4f2270d26de5` | ignorado |
| `firebase-secrets/firebase-adminsdk.json` | `16f9e6f5…` | `40919df520a82c9f` | ignorado |
| `www/admin/backend/firebase-adminsdk.json` | `99dffeaa…` | `297c4f2270d26de5` | **NÃO ignorado** |

São **duas chaves distintas** (mesmo projeto). `backend/` e
`www/admin/backend/` são byte-idênticas em 9 de 10 arquivos — é a mesma chave
duplicada.

Valores mascarados de propósito: nenhum caractere de `private_key`, `client_email`
ou chave de API aparece neste relatório.

### 3.2 Prova de exposição (HTTP real, sem rede externa)

Script `_verify_static_exposure.py` — monta o mesmo app com `StaticFiles` puro
e faz as requisições que um visitante faria:

```
GET /backend/.env                    -> 200  <<< SERVIDO
GET /backend/firebase-adminsdk.json  -> 200  <<< SERVIDO
GET /backend/diagnosticar.py         -> 200  <<< SERVIDO
GET /backend/renovar_admin.py        -> 200  <<< SERVIDO
GET /js/config.js                    -> 200  (legítimo)

  /backend/.env: 720 bytes | marca de segredo: True | 1a linha: 'GROQ_API_KEY='
  /backend/firebase-adminsdk.json: 2393 bytes | marca de segredo: True
```

Este script **sai com código 1 de propósito** — é a prova do estado anterior.

### 3.3 Por que só agora

O `.dockerignore` que eu mesmo criei na TAREFA anterior já excluía
`www/admin/backend/` do contexto de build (verificado: `entregue no build? False`).
Ou seja, **a imagem Docker estava protegida, mas só por causa de um arquivo meu
com 86 padrões.** Se o build rodasse sem esse arquivo, ou se houvesse outro caminho
de publicação, as credenciais iam junto. Ponto único de falha, sem teste que
detectasse a regressão.

---

## 4. Correções aplicadas

### 4.1 `backend/app/core/static_guard.py` — novo

Função pura `is_blocked_static_path()` + classe `GuardedStaticFiles` que
sobrescreve `lookup_path`. Bloqueia:

1. **qualquer segmento que comece com `.`** — `.env`, `.git/…`, `.pytest_cache/…`
2. **a subárvore `backend`** na raiz estática (lista explícita `BLOCKED_ROOTS`)
3. **`.env` com prefixo** — `config.env`, `prod.env`
4. **extensões de chave** — `.pem`, `.key`, `.p12`

Devolve `(path, None)` para o `StaticFiles` cair no **404 normal dele** — resposta
idêntica à de um arquivo inexistente, então não serve de oráculo para sondagem
do host (há teste comparando os dois).

**Por que guardar em vez de apagar a pasta:** apagar `www/admin/backend/`
resolveria o sintoma, mas sem provar que nada depende daquele caminho (deploy
legado, manual, referência em script) seria remover às cegas. A guarda mantém os
arquivos onde estão e faz o servidor recusar a entrega — reversível e sem efeito
colateral.

### 4.2 `backend/app/main.py`

```diff
- app.mount("/", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
+ app.mount("/", GuardedStaticFiles(directory=ADMIN_DIR, html=True), name="admin")
```

Removi o `from fastapi.staticfiles import StaticFiles`, que ficou sem uso.
O `main.py` fica com **exatamente os mesmos 10 achados do ruff** de antes, nas
mesmas regras (`BLE001, DTZ003, DTZ005, F401, F841, I001, PIE810, RUF010`) —
conjunto idêntico, confirmado por comparação com o backup.

### 4.3 `.gitignore`

```diff
+ **/firebase-adminsdk.json
+ **/firebase-adminsdk.json.bak
+ www/admin/backend/
```

O padrão sem barra casa em qualquer nível. Confirmado com `git check-ignore -v`:
os 3 caminhos da chave agora são ignorados, e `git status --short
www/admin/backend/` voltou a vazio.

### 4.4 `tests/test_static_guard.py` — 52 testes

Camada 1, função pura (sem I/O): 27 caminhos sensíveis bloqueados, 17 assets
legítimos liberados, normalização de barras e `./`.

Camada 2, HTTP real com `TestClient`: 12 caminhos proibidos em 404 sem vazar
material de segredo no corpo, 5 assets do painel ainda em 200, 404 da guarda
indistinguível do 404 normal.

**Teste de controle negativo:** `test_controle_o_que_a_guarda_muda_e_realmente_o_static_files_puro`
afirma que o `StaticFiles` **puro** retorna 200 e a guarda retorna 404. Sem ele, os
outros testes não provariam que a guarda é o que corrige — apenas que 404 acontece.

---

## 5. Validações

| Verificação | Resultado |
|---|---|
| `pytest -q` | **143 passed** (52 novos) |
| `pytest tests/test_static_guard.py -q` | 52 passed |
| `compileall backend` | exit 0 |
| `ruff` nos arquivos novos | **All checks passed** |
| `ruff` `main.py` antes vs depois | 10 achados, conjunto **idêntico** |
| `import app.core.static_guard` | OK |
| `_verify_static_guard.py` | **exit 0** — 12 proibidos em 404, 7 assets em 200, `index.html` íntegro (35755 bytes) |
| `_verify_static_exposure.py` | exit 1 — prova do estado anterior, comportamento esperado |

Arquivos do painel confirmados intactos após a guarda: `index.html` 35755 B,
`styles.css` 87288 B, `sw.js`, `firebase-messaging-sw.js`, `favicon.svg`,
`icons.svg`, `LEIA-ME.txt`.

Backups: `.gitignore.bak-audit-20261005`, `backend/app/main.py.bak-audit-20261005`
(criados antes de editar, não sobrescritos).

---

## 6. Risco residual — `PENDENTE`, exige operação de segurança

O código está corrigido. **A chave não foi rotacionada** e não posso rotacionar —
isso é operação no Google Cloud/Firebase, fora do repositório.

Três pontos que precisam de decisão sua:

1. **Rotacionar a chave do service account.** Se o host já publicou
   `/backend/…` publicamente em algum momento, a chave deve ser considerada
   comprometida. Uma chave Admin SDK publicada dá escrita total no
   `playearn-b001b` — inclusive em `config/`, `adminBalance`, `banca`,
   `baseProfit`. Recomendo rotacionar **antes** de continuar a usar o painel em
   produção, independentemente da correção.

2. **`www/admin/backend/` continua no disco.** Agora é servido como 404 e está
   no `.gitignore`, mas é uma cópia do backend com `.env` dentro da raiz
   estática. **Não apaguei** —nao confirmei as 7 condições de remoção, e a pasta
   pode estar referenciada por algum fluxo de deploy ou script. Recomendo
   investigar a origem dela e movê-la para fora de `www/`.

3. **Duas chaves para o mesmo projeto.** `backend/` e `firebase-secrets/` têm
   `private_key_id` diferentes. Convém saber qual é a canônica e revogar a
   outra.

Também continuam válidos: **`.dockerignore` é ponto único de falha.** A guarda
agora é a segunda barreira, e é a que tem teste.

---

## 7. Achados relacionados (não corrigidos aqui)

| Achado | Classificação |
|---|---|
| `www/admin/index.html.bak-audit-20261005` e `styles.css.bak-audit-20261005` dentro da raiz estática | `NÃO ALTERADO POR SEGURANÇA` — backups dentro de `www/` são servidos se o `.dockerignore` falhar; movê-los quebra a rastreabilidade dos backups |
| `www/admin/estyle/` — diretório vazio, provável typo de `style` | `MORTO COMPROVADO` (0 arquivos) — mas apagar diretório vazio não tem ganho; deixei |
| `www/admin/backend/.pytest_cache/` | `PENDENTE` — servido como 404 agora (dotfile), mas indica que testes rodaram dentro da raiz estática |
| Backups `.bak-audit-*` de `styles.css` serviriam fonte com regras antigas | `INDETERMINADO` — não é segredo, mas pode expor código removido |

---

## 8. Estado

**CÓDIGO TECNICAMENTE CORRIGIDO E AUDITADO, COM EVIDÊNCIAS LOCAIS;
PRODUÇÃO AINDA NÃO LIBERADA.**

Não afirmo que o sistema esteja "seguro" nem "sem vulnerabilidades". Afirmei, com
medição: `GET /backend/.env` e `GET /backend/firebase-adminsdk.json` devolviam
200 com credenciais e agora devolvem 404, há teste que falha se isso voltar, e a
chave não entra mais no Git.

---

## 9. Como reproduzir

```powershell
python _verify_static_exposure.py   # ANTES  -> exit 1, mostra o vazamento
python _verify_static_guard.py      # DEPOIS -> exit 0, mostra a proteção
python -m pytest tests/test_static_guard.py -q
git check-ignore -v www/admin/backend/firebase-adminsdk.json
```