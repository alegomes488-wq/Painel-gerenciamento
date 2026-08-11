# Deploy Checklist — Painel CyberCore IA

## Antes de fazer push para produção

### Backend
- [ ] `ADMIN_EMAIL` configurado no `.env` ou secrets
- [ ] `WEBHOOK_SECRET` configurado e não vazio
- [ ] `ASAAS_API_KEY` configurada (produção, não sandbox)
- [ ] `FIREBASE_SERVICE_ACCOUNT` válida e com permissões
- [ ] `FIREBASE_PROJECT_ID` e `FIREBASE_APP_ID` configurados no `.env` (App Check backend)
- [ ] **`APP_CHECK_REQUIRED` permanece `false`** até o frontend enviar `X-Firebase-AppCheck`
- [ ] Middleware `admin_auth_middleware` com `settings.ADMIN_EMAIL` definido
- [ ] CORS configurado para origens de produção (não `*`)
- [ ] Teste de login com admin → claim aplicado
- [ ] Teste de login com não-admin → rejeitado (403)
- [ ] Teste de webhook Asaas → 403 sem token, 200 com token válido
- [ ] Teste de lock anti-concorrência → duplo-clique gera 1 transferência

### Frontend
- [ ] `config.js` com `appCheckSiteKey` da chave Enterprise correta
- [ ] `sw.js` com App ID sincronizado com `config.js`
- [ ] App Check registrado no Firebase Console para o app web
- [ ] Debug tokens registrados (apenas para dev, NÃO em produção)
- [ ] Teste de login em janela anônima → sem erros de App Check
- [ ] Teste de XSS → payloads em pixKey/fullname não executam
- [ ] **Wrapper central de fetch envia `X-Firebase-AppCheck`** em TODAS as chamadas `/api/*` e `/payments/*` (hoje `auth.js` e módulos usam `fetch` direto) — condição para ativar `APP_CHECK_REQUIRED=true`

### Ativação do enforcement App Check (somente após tudo acima)
- [ ] Frontend enviando `X-Firebase-AppCheck` com sucesso em produção
- [ ] Testar com `APP_CHECK_REQUIRED=true` em staging: rotas de API exigem o header (401 sem ele); `/health`, `/docs`, webhook Asaas, `/api/monitor/report`, auto-approve e OPTIONS continuam funcionando
- [ ] Promover `APP_CHECK_REQUIRED=true` para produção apenas com os testes verdes

### Geral
- [ ] Cache do navegador limpo
- [ ] Service Worker re-registrado
- [ ] `npm audit` sem vulnerabilidades críticas
- [ ] Logs do backend sem erros de auth
- [ ] `/health` retorna 200

## Após deploy
- [ ] Monitorar métricas do App Check (Firebase Console)
- [ ] Verificar se Authentication está em "Monitorar" (não ENFORCE ainda)
- [ ] Testar fluxo completo: login → saque → webhook → notificação
