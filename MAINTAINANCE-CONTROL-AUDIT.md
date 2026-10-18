# Controle de Manutenção — Relatório de Implementação e Validação

**Data:** 2026-10-05
**Escopo:** `Painel gerenciamento` (CyberCore IA) — adição de controle real de modo de manutenção, com fonte de verdade compartilhada com o site `cinecash.com.br`
**Estado:** **CÓDIGO TECNICAMENTE CORRIGIDO E AUDITADO, COM EVIDÊNCIAS LOCAIS. PRODUÇÃO AINDA NÃO LIBERADA.**

---

## 1. Causa raiz (já confirmada antes desta tarefa)

| Item | Valor | Fonte |
|---|---|---|
| Nó no RTDB | `config/maintenance` | `CineCash-por-IA/www/app.js` (listener `onValue`) |
| Valor em produção | `true` (booleano real) | leitura RTDB no projeto `playearn-b001b` |
| `projectId` | `playearn-b001b` | idêntico em site e painel |
| `databaseURL` | `https://playearn-b001b-default-rtdb.firebaseio.com` | idêntico em site e painel |

**O painel não refletia o estado porque não possuía UI nem escrita para esse nó.** Não era dessincronização — era ausência de controle.

Achados anteriores que motivaram esta tarefa:

| Achado | Classificação |
|---|---|
| `settings.js:3` lia `#toggle-maintenance`, elemento inexistente no HTML (0 ocorrências de `manuten`) | **MORTO COMPROVADO** (código morto) |
| `🔌 DESCONNECTAR` nos cards → `toggleProjectConnection` → `POST /api/project/toggle` com `online|offline` | **ATIVO**, mas **não é manutenção** (altera `neural/nodes/<id>/health/override`) |
| `updateStatusIndicators()` era chamado por `main.js` a cada evento do listener `config`, mas não renderizava nada | **MORTO COMPROVADO** |
| Rótulo invertido (`ATIVAR` quando ativo) em `CineCash-por-IA/www/admin/app.js` | **ATIVO** no outro projeto — não alterado aqui |

---

## 2. O que foi implementado

### 2.1 Backend — `backend/app/routers/admin.py`

Duas rotas novas, sob o prefixo já existente `/api/admin`:

```
GET  /api/admin/maintenance   leitura de config/maintenance
POST /api/admin/maintenance   gravação de config/maintenance
```

Garantias implementadas:

| Garantia | Como |
|---|---|
| Autorização server-side | `get_current_user(request)` + `is_admin_user(uid, decoded)` — o booleano do navegador nunca decide quem grava |
| Gravação só via Admin SDK | `ref.set(enabled)` — nunca escrita direta pelo frontend, contorna `.write` restrito a admin |
| Booleano real obrigatório | `_coerce_strict_bool` rejeita `"true"`, `1`, `"1"`, `null`, `[]`, `{}` com **422** |
| ATIVAR exige confirmação | `enabled=true` sem `confirm=true` → **422** |
| DESATIVAR nunca exige confirmação | desbloqueio sempre possível (uma manutenção acidental sempre tem saída) |
| Leitura de confirmação | After write, relê o nó; divergência → **500**, nunca `success` |
| Falha de RTDB visível | `reference()` e `set()` em `try` próprio → **500** com corpo, não exceção opaca |
| Auditoria | `log_admin_action(uid, "admin_maintenance", {enabled, previous, reason, path})` |
| `reason` limitado | 200 caracteres, **422** acima disso |
| Falha de leitura ≠ manutenção | `GET` devolve **503** com `read_ok: false`, `maintenance: null` |

**Motivo do `422` para string/número** (não é estilo, é operacional): em JS, `if (val)` trata a string `"false"` como *truthy*. Uma gravação de `"false"` manteria o site em manutenção para sempre enquanto o painel reportava sucesso.

### 2.2 Frontend — `www/admin/js/modules/maintenance.js` (novo)

Fonte de verdade única: `config/maintenance`. Estados separados:

| Estado | Quando | Rótulo na badge |
|---|---|---|
| `MAINTENANCE_ACTIVE` | valor booleano `true` | MANUTENCAO ATIVA — SITE EXIBINDO OVERLAY (âmbar) |
| `SERVICE_OPERATIONAL` | `false` ou nó ausente | SISTEMA OPERACIONAL — SEM MANUTENCAO (verde) |
| `CONFIG_LOAD_ERROR` | erro do listener, tipo inesperado, ou `read_ok !== true` | ERRO AO LER CONFIG — ESTADO DESCONHECIDO (vermelho) |
| `SERVICE_UNAVAILABLE` | `hubDb` ausente ou backend inalcançável | BACKEND INDISPONIVEL — ESTADO DESCONHECIDO (cinza) |

Comportamentos implementados:

- **Listener único** — guarda `_maintListenerAtivo`; chamadas duplicadas retornam `false` sem criar segundo listener.
- **Teardown** — `stopMaintenanceListener()` remove o listener; chamado no `logout()`.
- **Erro nunca vira manutenção** — `_applyMaintenanceError` marca `CONFIG_LOAD_ERROR`, `confiavel = false`, desabilita os controles e emite toast explicitando *"Isso NAO significa manutencao ativa"*.
- **Tipo inesperado** — valor não booleano e não nulo gera `CONFIG_LOAD_ERROR` + aviso, em vez de ser tratado como `true` (seria o comportamento do site).
- **Sem estado em `localStorage`** — sempre o RTDB.
- **Trava contra clique duplo** — `_maintEmVoo`.
- **Escrita com re-sincronização** — falha no POST chama `refreshMaintenanceFromBackend()` e a UI volta a refletir a verdade; se a releitura também falhar, o controle **permanece desabilitado**.
- **Rótulo acompanha o estado** — `Manutenção LIGADA` / `DESLIGADA` / `ESTADO DESCONHECIDO`. Corrige o padrão de rótulo invertido do painel antigo.
- **Alerta ao ligar** — transição para `MAINTENANCE_ACTIVE` dispara aviso, porque derrubar o site sem registro no painel era o sintoma original.

### 2.3 UI — `www/admin/index.html`

Card "🚧 Modo Manutenção (Site)" dentro de `panel-settings`:

- `maint-state-badge` — badge de estado com as 4 cores distintas
- `maint-toggle` — switch acessível (`role="switch"`, input invisível, foco visível, `label` ligado)
- `maint-toggle-label` — rótulo textual que acompanha o estado
- `maint-reason` — motivo para auditoria (max 200)
- `maint-apply` — botão de aplicação

**54 IDs no HTML, zero duplicados.** Sem ID duplicado (o que quebraria `getElementById`).

### 2.4 Scripts

`maintenance.js` carregado **antes** de `auth.js`, para que `stopMaintenanceListener` exista quando `logout()` for chamado. Cache-busting `?v=4.1.3` → `?v=4.2.0` em todos os scripts (14 tags).

### 2.5 Código morto eliminado

`settings.js` — `updateStatusIndicators()` lia `#toggle-maintenance` (elemento inexistente). Agora delega a `renderMaintenanceUI()`. Mantido como ponto de entrada porque `main.js` o chama a cada evento do listener `config`.

---

## 3. Validações executadas

### 3.1 Testes automatizados — `pytest`

```
91 passed in 1.77s
```

`tests/test_admin_maintenance.py` — 25 casos: 401 sem token, 403 usuário comum (com verificação de que nada foi gravado), 422 para `enabled` ausente/string/número/`null`/lista (parametrizado), 422 ativar sem `confirm`, desativar sem `confirm` permitido, `reason` > 200, body não-objeto, gravação no caminho exato, `false` gravado como `False` booleano real, auditoria com `actor_uid`/`enabled`/`reason`/`path`, confirmação divergente → 500, `GET` refletindo o RTDB, nó ausente → operacional, falha de leitura → 503 com `read_ok: false`.

Suíte completa: 91 passed. Nenhuma regressão.

### 3.2 Harness do JS real — 44/44

`_verify_maintenance_js.cjs` executa o `maintenance.js` **real** (o mesmo arquivo servido ao navegador) num sandbox `vm` com DOM e Firebase simulados.

```
=== resultado: 44 passou, 0 falhou ===
```

Cobre: registro único (3 chamadas → 1 listener), teardown idempotente, `true`→`MAINTENANCE_ACTIVE`, `false`→`SERVICE_OPERATIONAL`, nó ausente→`SERVICE_OPERATIONAL` (paridade com o site), erro→`CONFIG_LOAD_ERROR` com `valor === null`, controles desabilitados, aviso "NÃO significa manutenção", string `"true"`→`CONFIG_LOAD_ERROR`, propagação em tempo real `false→true→false`, falha de escrita com releitura ok (volta à verdade) e sem releitura (permanece travado), `confirm:true` no payload, motivo propagado, recusa de valor não booleano antes do `fetch`, rótulo acompanhando estado.

### 3.3 Verificação da API real

`_verify_maintenance_api.py` sobe o FastAPI real (`app.main:app`) com RTDB substituído por dublê em memória. **Não toca no Firebase de produção.**

```
=== 1. Rotas /api/admin/maintenance no OpenAPI ===
  /api/admin/maintenance  ->  GET, POST

=== 2. Autorizacao (middleware real) ===
  POST sem token      -> 401
  POST usuario comum  -> 403
  GET  usuario comum  -> 403

=== 3. Estado inicial real do no ===
  GET  -> 200 {'status': 'success', 'read_ok': True, 'maintenance': True, 'stored_raw_type': 'bool'}

=== 4. Validacao (nada deve ser gravado) ===
  sem enabled              -> 422  enabled e obrigatorio
  enabled="true" (string)  -> 422  enabled deve ser booleano (true/false); string ou numero
  enabled=1 (numero)       -> 422  enabled deve ser booleano (true/false); string ou numero
  ativar sem confirm       -> 422  Ativar manutencao exige confirm=true
  reason 201 chars         -> 422  reason deve ter no maximo 200 caracteres
  no apos rejeicoes: True  (deve continuar True)

=== 5. Gravacao real (caminho e tipo) ===
  POST desativar -> 200 {... 'confirmed': False ...}
  config/maintenance gravado = False  tipo=bool
  e booleano real?            True
  POST ativar    -> 200 confirmed=True

=== 7. Falha de gravacao => 500 visivel (nao 'success') ===
  detail: Falha ao acessar o RTDB em config/maintenance: RTDB indisponivel
  retornou 'success'? False
```

### 3.4 Paridade site ↔ painel — `_verify_paridade.py`

```
=== RESULTADO: PARIDADE CONFIRMADA ===
```

`projectId` idêntico, `databaseURL` idêntico, mesmo caminho `config/maintenance`, mesma interpretação de "nó ausente", gravação de booleano real dos dois lados, nenhum estado em `localStorage`, erro do listener não marca `MAINTENANCE_ACTIVE`, listener único removido no logout, autorização server-side nos dois caminhos, ordem de scripts e cache-busting corretos.

### 3.5 Validação visual no navegador

Servido em `http://127.0.0.1:8931`, inspeção via browser. **Zero erros de console.**

| Estado | Cor da badge | Fundo |
|---|---|---|
| `SERVICE_OPERATIONAL` | `rgb(16, 185, 129)` | `rgba(16, 185, 129, 0.25)` |
| `MAINTENANCE_ACTIVE` | `rgb(245, 158, 11)` | `rgba(245, 158, 11, 0.25)` |
| `CONFIG_LOAD_ERROR` | `rgb(239, 68, 68)` | `rgba(239, 68, 68, 0.25)` |
| `SERVICE_UNAVAILABLE` | `rgb(148, 163, 184)` | `rgba(148, 163, 184, 0.1)` |

Switch: track `52px × 28px`, `border-radius: 9999px`, thumb `20px`, deslocamento `matrix(1, 0, 0, 1, 24, 0)` quando marcado, borda do track muda para `rgba(245, 158, 11, 0.55)` em manutenção.

### 3.6 Qualidade estática

| Verificação | Resultado |
|---|---|
| `python -m compileall backend/app tests` | exit 0 |
| `node --check` nos 4 JS alterados | exit 0 (todos) |
| `git diff --check` | nenhum problema nos arquivos alterados (os achados em `main.py` e `firebase-messaging-sw.js` são **pré-existentes**) |
| `ruff` delta no `admin.py` | **nenhuma regra nova** — antes `{BLE001, F401, I001, RUF010, S110}`, depois idêntico. Os 14 achados atuais são do mesmo conjunto que já existia no arquivo |

---

## 4. Achado adicional: `.dockerignore` ausente

O `Dockerfile` raiz faz `COPY . .` e o repositório **não tinha `.dockerignore`**. Isso significa que uma imagem de produção carregaria:

- `backend/.env` (segredos reais)
- `backend/firebase-adminsdk.json` (Service Account)
- todos os backups `*.bak-audit-*`
- a suíte de testes e artefatos de auditoria

**`.dockerignore` criado** com 86 padrões efetivos, incluindo uma exceção deliberada `!.env.example` (o template não tem segredo e é útil na imagem; a negação precisa vir **depois** de `.env.*`).

Validação por `_verify_dockerignore.py`:

```
=== .dockerignore: 86 padroes efetivos ===
  --- DEVEM SER EXCLUIDOS ---
  23/23 OK  (inclui .env, firebase-adminsdk.json, *.bak-audit-*, tests/, .git/, __pycache__/, .vs/)
  --- DEVEM SER ENTREGUES ---
  18/18 OK  (inclui maintenance.js, index.html, styles.css, .env.example, README.md)

  --- varredura do disco (arquivos reais) ---
     ignorados : 6490
     entregues : 123

  --- varrredura de nomes sensiveis entre os ENTREGUES ---
  [OK   ] nenhum nome de credencial entre os entregues

RESULTADO: contexto Docker limpo
```

O `.gitignore` também passou a cobrir `*.bak-audit-*` (o padrão `*.bak` não cobria esse sufixo).

---

## 5. Backups

Backup de cada arquivo antes de qualquer edição, sufixo `.bak-audit-20261005` (não sobrescrito se já existente):

```
backend/app/routers/admin.py.bak-audit-20261005
www/admin/index.html.bak-audit-20261005
www/admin/js/modules/settings.js.bak-audit-20261005
www/admin/js/main.js.bak-audit-20261005
www/admin/js/auth.js.bak-audit-20261005
www/admin/styles.css.bak-audit-20261005
```

---

## 6. Classificação por requisito

| Requisito | Classificação |
|---|---|
| Botão de manutenção no painel | **CORRIGIDO** — `maint-toggle` + `maint-apply` em `panel-settings` |
| Tempo real | **CORRIGIDO** — listener RTDB único em `config/maintenance`, teardown no logout |
| Autorização server-side | **VALIDADO** — 401/403 nos testes e na verificação da API real |
| Estados separados | **VALIDADO** — 44/44 no harness, 4 cores distintas no navegador |
| Erro não vira manutenção | **VALIDADO** — `CONFIG_LOAD_ERROR` + toast explícito |
| Gravação nunca silenciosa | **VALIDADO** — releitura de confirmação; divergência → 500 |
| Código morto `#toggle-maintenance` | **CORRIGIDO** — removido, delegando ao módulo novo |
| `.dockerignore` ausente | **CORRIGIDO** — criado e validado (6490 arquivos ignorados) |
| Rótulo invertido | **CORRIGIDO** — rótulo acompanha o estado |
| `_pendingWrite` do `CineCash-por-IA\www\admin\app.js` | **NÃO ALTERADO** — projeto diferente; requer decisão separada |
| `GET /api/system/maintenance/off` inexistente | **PENDENTE** — `CineCash-por-IA\backend\main.py` tem 0 ocorrências de "maintenance"; 404 silencioso |
| `docker build` / `run` | **PENDENTE** — daemon do Docker não está rodando |
| Escrita em produção (`maintenance = false`) | **PENDENTE — aguarda autorização explícita** |

---

## 7. Ressalvas

- **`pytest 91/91` não prova autorização nem isolamento em produção.** Os testes usam RTDB e auth simulados; não exercitam App Check real, regras deployadas nem o provedor de identidade.
- **As regras do RTDB deployadas divergem do repositório.** `database.rules.json` no repo tem `config/maintenance: {".read": true}`, mas o REST público em `/config/maintenance.json` e `/config.json` retorna **HTTP 401**. As regras em produção **não foram lidas** (leitura via Admin de `.settings/rules` falhou com `ValueError: Invalid path: "//.settings/rules"`). Classificação: **INDETERMINADO**.
- **`.dockerignore` reduz o contexto da imagem, mas não revoga credenciais** que já tenham sido commitadas. `gitleaks`/`trufflehog` não instalados → histórico Git **não varrido** por ferramenta dedicada. `git grep` não substitui essas ferramentas.
- **`ADMIN_EMAIL` sozinho não é autorização.** `is_admin_user` aceita claim `admin`, allowlist em `system/admin_uids`, ou fallback por e-mail. O fallback por e-mail é ponto fraco a revisar (recomendação: remover ou exigir MFA).
- **O listener depende de App Check.** Se o App Check bloquear o socket do RTDB, o painel cai em `CONFIG_LOAD_ERROR` (correto — não vira manutenção), mas o operador perde a visibilidade em tempo real. Os `403 exchangeRecaptchaEnterpriseToken` e `app-check/throttled` continuam **pendência operacional** da Fase 3.
- **O nó `config/` do RTDB contém segredos vivos** (`asaasKey`, `geminiKey`, `githubToken`, `telegramToken`, `vapidKey`, entre outros). Se as regras deployadas realmente restringirem a leitura de `config`, o painel pode passar a ler `CONFIG_LOAD_ERROR` após esta mudança. Não foi possível confirmar. Classificação: **PENDENTE — evidência insuficiente**.
- **Nenhum commit foi feito.** Working tree permanece sujo.
- **Este relatório descreve código auditado localmente. Não constitui aprovação para produção.**

---

## 8. Pendências antes de liberar

1. Autorização explícita do usuário para escrever `config/maintenance = false` (ou operar pelo painel, agora possível).
2. Ler as regras do RTDB **deployadas** e comparar com `database.rules.json`.
3. `docker build` + `docker compose config` + healthcheck (requer Docker Desktop).
4. Instalar `gitleaks`/`trufflehog` e varrer `git log --all`.
5. Resolver `403 exchangeRecaptchaEnterpriseToken` / `app-check/throttled`.
6. Revisar o fallback por `ADMIN_EMAIL` em `is_admin_user`.
7. Corrigir `_pendingWrite` e o endpoint inexistente em `CineCash-por-IA` (projeto separado).
8. `gitleaks` no histórico **antes** de qualquer push.

---

**Estado final desta tarefa:**
**CÓDIGO TECNICAMENTE CORRIGIDO E AUDITADO, COM EVIDÊNCIAS LOCAIS. PRODUÇÃO AINDA NÃO LIBERADA.**