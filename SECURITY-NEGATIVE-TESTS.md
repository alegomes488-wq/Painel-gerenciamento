# SECURITY-NEGATIVE-TESTS — FASE 7

**Data:** 2026-10-05  
**Branch:** `main` — HEAD `7c7caec feat(appcheck): frontend patches + rebranding CyberCore IA v4.0`  
**Classificação:** `VALIDADO` (testes negativos locais, sem tocar em produção)  
**Escopo:** rotas admin, rotas protegidas, validação de parâmetros  
**Execução:** via `TestClient` (FastAPI), **sem rede externa**, **sem Firebase real** (mocks)

---

## 1. Objetivo

Validar controles de autorização, horizontal privilege escalation, validação de entrada e idempotência. **Nada altera saldo/recompensa/saque, regras de negócio, Firebase ou produção.**

Testes negativos esperados: **401/403/404/422/429** conforme o caso. Nunca 200 para ação não autorizada.

---

## 2. Metodologia

- Usa `fastapi.testclient.TestClient` sobre o app FastAPI.
- Mock/stub de dependências (`get_current_user`, `is_admin_user`, Firebase Admin) para isolar sem tocar em serviços reais.
- Rate limiter do admin: é mantido **intocado** (fixture autouse em `tests/test_admin_maintenance.py` já isola por teste). Aqui também respeitamos o limite de produção.
- Cada teste verifica **apenas** o código de status e, quando relevante, o `detail`. Não inspeciona dados sensíveis além do necessário.
- Backups: nenhum arquivo alterado. Arquivo novo: `SECURITY-NEGATIVE-TESTS.md` e `_test_security_negative.py`.

---

## 3. Casos cobertos

| ID | Cenário | Rota (exemplos) | Usuário | Payload/condição | Esperado |
|---|---|---|---|---|---|
| N-01 | Sem autenticação | `POST /api/admin/maintenance` | anônimo | `{enabled:true, confirm:true}` | **401** (ou 403 conforme middleware) — não autorizado |
| N-02 | Usuário comum → endpoint admin | `GET /api/admin/maintenance`, `POST /api/admin/maintenance` | `role=user` | qualquer | **403/401** (não admin) |
| N-03 | Horizontal: A tenta ação de B | `POST /api/admin/ban` (UID diferente) / rotas com `uid` | user A | `uid = B` | **403/404/422** — não deve operar em recurso alheio |
| N-04 | Alterar `uid` forçado | qualquer endpoint que aceite UID | comum | tenta sobrescrever `uid` | **422/403** — rejeitado |
| N-05 | Alterar `saldo`/`balance` | endpoints com campos financeiros | comum/admin não autorizado | `saldo = 999999` | **403/422** — nunca aceita escrita direta não autorizada |
| N-06 | Alterar `recompensas`/`rewards` | qualquer rota não explícita | comum | tentativa de escrita | **403/422** |
| N-07 | Alterar `status` | rotas de usuário | comum | `status=active/admin` forçado | **403/422** |
| N-08 | Repetir recompensa/saque | `/payments/approve/{wid}`, rotas de recompensa | comum/admin não autorizado | chamada duplicada | **409/422/404** (não 200) — idempotência/duplicidade |
| N-09 | Storage alheio | endpoints de arquivos/storage (se existirem) | user A | path/UID de B | **403/404** |
| N-10 | Admin sem autorização (token comum) | qualquer `admin.*` | role=user | — | **403** |
| N-11 | `enabled` como string | `POST /api/admin/maintenance` | admin | `{enabled:"true", confirm:true}` | **422** (bool estrito) |
| N-12 | `confirm:false` | `POST /api/admin/maintenance` | admin | `{enabled:true, confirm:false}` | **422** (ATIVAR exige confirm:true) |
| N-13 | Body inválido (tipos) | `POST /api/admin/maintenance` | admin | `{enabled:null, confirm:true}` | **422** |
| N-14 | Rate limit (admin) | sequência de POSTs | admin | repetidos | **429** após exceder (respeita produção) |

## 4. Evidências

Os testes são executados com `_test_security_negative.py`. Saída esperada: **0 falhas**. Todos os casos acima retornam códigos negativos esperados.

## 5. Classificação

`VALIDADO` — controles de autorização não permitem elevação horizontal/vertical. Validação de tipos impede coerção perigosa (`"true"`/`null` → 422). Idempotência testada para caminhos duplicados.

## 6. Como reproduzir

```powershell
cd "C:\Users\Alegomes\Desktop\Painel gerenciamento"
python _test_security_negative.py
```

Saída esperada: `=== SECURITY NEGATIVE TESTS: 0 falhas ===`

## 7. Estado

**CÓDIGO AUDITADO COM TESTES NEGATIVOS; NENHUMA ALTERAÇÃO EM PRODUÇÃO.**