# Painel de Gerenciamento — Resumo do Projeto

## Stack
- **Frontend**: HTML/CSS/JS puro, Firebase Auth + Realtime Database, Lucide icons
- **Backend**: Python FastAPI (backend/main.py), Firebase Realtime Database
- **Admin**: `www/admin/` — painel separado com Firebase compat SDK

## Estrutura
- `www/index.html` — Site principal (login, dashboard, gamecash, etc.)
- `www/style.css` — Estilos
- `www/admin/index.html` — Admin panel
- `backend/main.py` — API FastAPI

## Regras de Negócio

### Metas de Anúncios (Milestones)
- Nenhum crédito por vídeo individual
- Recompensa apenas ao bater milestones:
  - 200 ads → R$ 0,50
  - 800 ads → R$ 3,00
  - 1.000 ads → R$ 5,00
  - 2.000 ads → R$ 10,00
  - 10.000 ads → R$ 50,00
- Backend: `POST /video/complete/{uid}` em `main.py:2399`
- Frontend: `updateUI()` em `index.html:1310` — tabela em `goals-table-body`
- Campo `milestones: {"200": true, ...}` no Firebase, marcado só quando creditado
- `triggerStrategicAd()` injeta scripts das redes quge5.com / al5sm.com

### Fluxo de Processamento
1. Clique em "INICIAR PROCESSAMENTO ▶"
2. `POST /video/start/{uid}` — abre sessão
3. Overlay de 30s com timer, partículas, status dinâmicos
4. `POST /video/complete/{uid}` — incrementa `videosWatched`, checa milestones
5. Toast "VALIDAÇÃO CONCLUÍDA!" ou "🎉 META ATINGIDA! +R$ X,XX"
6. Confetti especial ao bater milestone

### GameCash
- Flappy Bird: metas 10 pts → R$ 0,01, 30 pts → R$ 0,03
- Jogo da Memória: <60s → R$ 0,03, <30s → R$ 0,05
- Limite de partidas por dia por jogo
- Game 2048 removido
- Anúncios são escondidos ao abrir jogos (display:none + limpeza de scripts)

### Saques (Intercâmbio)
- Valores: R$ 0,50 / R$ 3,00 / R$ 5,00 / R$ 10,00 / R$ 50,00
- Chaves: CPF, CNPJ, e-mail, telefone, aleatória
- Backend: `POST /payments/request/{uid}` em `main.py:2491`

### Indicações (Referral)
- R$ 0,20 por indicado que atingir 25 anúncios
- +R$ 1,00 a cada 5 indicados válidos
- Slug único por usuário (válido 30 dias)
- Cadastro cria entrada em `referrals/{referrerUid}/{uid}` via frontend Web SDK
- `loadReferrals()` lê de `ref(db, 'referrals/' + uid)` (Firebase Web SDK, não API)
- `updateUI()` sincroniza `videosWatched` para `referrals/{referredBy}/{uid}` a cada carregamento
- `referrals` nó no Firebase: cada um lê só a própria lista, indicado/indicador podem escrever

### Bônus Diário
- R$ 0,20 disponível apenas em dias úteis (segunda a sexta) — verificação `isWeekday` no frontend
- 1x por dia
- `claimDailyBonus()` escreve direto no Firebase via Web SDK (`update()` com `balance + 0.20`)
- Regra `.validate` no Firebase permite `balance + 0.20` + `last_daily_bonus_date`
- Backend `POST /user/claim-daily/{uid}` não é mais chamado pelo frontend

### Firebase Admin SDK — BLOQUEADO
- Service account `playearn-b001b` com `invalid_grant: Invalid JWT Signature`
- Todos os endpoints que usam `db.reference()` (video/complete, payments/request, etc.) falham
- Workaround: frontend Web SDK para operações críticas (daily bonus, referrals)
- `backend/firebase-adminsdk.json.bak` precisa ser substituído por chave nova do Firebase Console

### Segurança
- Regras Firebase restritas em `rules.json`
- `users/` e `withdrawals/` apenas admin pode ler
- `users/$uid/` usuário pode ler próprio registro
- `referrals/` usuário lê própria lista; indicado/indicador escrevem entrada
- Cooldown de 28s entre processamentos (anti-bot)
- Risk score incrementado se processamento muito rápido
- Sessão com trava (sessionStorage) ao perder foco/refresh
- Fingerprint no login

### Anúncios (Monetag)
- Banner `#monetag-banner` no topo da aba Início
- Scripts: quge5.com (20%) ou al5sm.com (80%) com zone IDs
- `data-ad-active="true"` marca script ativo
- `keepDuration=30000` — script removido após 30s
- `onerror` detecta adblock e mostra fallback
- **Não carrega anúncios** durante jogos (verifica `gameState.current`)
- Scripts e timer limpos ao abrir um jogo
- **Ad Slot Controller**: `enforceAdSlots()` limita a no máximo 3 elementos de anúncio (`MAX_AD_SLOTS = 3`)
- `_adObserver` (MutationObserver) monitora injeções e remove excessos em tempo real
- Obs: as redes de anúncio podem injetar múltiplos iframes/divs — o slot controller garante que no máximo 3 fiquem visíveis

## Endpoints da API
- `GET /video/start/{uid}`
- `POST /video/complete/{uid}`
- `POST /payments/request/{uid}`
- `POST /user/claim-daily/{uid}`
- `GET /api/referral/list/{uid}`
- `POST /api/referral/create/{uid}`
- `GET /api/referral/resolve/{slug}`
- `POST /api/game/reward/{uid}`
- `GET /api/n8n/url`
- `POST /api/n8n/trigger/risk-alert`
- `POST /api/n8n/trigger/new-user`
- `POST /api/n8n/trigger/weekly-report`

> Nota: endpoints que usam `db.reference()` (video/complete, payments/request, referral/list, etc.) estão quebrados até que o service account seja substituído.

## N8N Automação
- N8N roda no mesmo container HF Space (porta 5678), acessível via `/n8n/` proxy
- FastAPI faz proxy com httpx.AsyncClient em `/n8n/{path}`
- Rotas `/n8n/*` são públicas (sem auth)
- start.sh gerencia n8n + uvicorn em paralelo
- Templates de workflow em `n8n-workflows/README.md`
- Webhooks N8N escutam em `/webhook/risk-alert`, `/webhook/new-user`, `/webhook/weekly-report`

## Modificações Recentes (CyberCore)
- Admin rebranded: "Brasil Hexa" → "[CYBERCORE] // PAINEL ADMIN"
- Tema: navy escuro (#0b0e14), azul/cyan/roxo — sem verde/ouro
- CT Canarinho extraído para `C:\Users\Alegomes\Desktop\Agentes\`
- GameCash oculto em produção (cinecash.com.br, HF Space)
- apiBase dinâmico: `window.location.origin`
- `/api/nexus/report` e `/api/metrics` públicos
- app.js reduzido de ~3652 → ~2565 linhas
- N8N integrado (start.sh, proxy, webhooks, admin UI)
- Bônus diário movido para frontend Web SDK (bypass backend)
- Indicações lidas de `referrals/{uid}` via Web SDK em vez da API
