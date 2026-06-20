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
  - 500 ads → R$ 0,25
  - 2.000 ads → R$ 0,50
  - 5.000 ads → R$ 1,00
  - 10.000 ads → R$ 2,00
  - 25.000 ads → R$ 3,50
- Backend: `POST /video/complete/{uid}` em `main.py:2399`
- Frontend: `updateUI()` em `index.html:1310` — tabela em `goals-table-body`
- Campo `milestones: {"500": true, ...}` no Firebase, marcado só quando creditado
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
- `GET /api/referral/list/{uid}` — lista indicações via API

### Bônus Diário
- R$ 0,20 disponível apenas sábado e domingo
- 1x por dia
- `POST /user/claim-daily/{uid}`

### Segurança
- Regras Firebase restritas em `rules.json`
- `users/` e `withdrawals/` apenas admin pode ler
- `users/$uid/` usuário pode ler próprio registro
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

## Endpoints da API
- `GET /video/start/{uid}`
- `POST /video/complete/{uid}`
- `POST /payments/request/{uid}`
- `POST /user/claim-daily/{uid}`
- `GET /api/referral/list/{uid}`
- `POST /api/referral/create/{uid}`
- `GET /api/referral/resolve/{slug}`
- `POST /api/game/reward/{uid}`
