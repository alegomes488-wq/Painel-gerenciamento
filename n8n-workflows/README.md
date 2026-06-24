# Workflows N8N — CyberCore IA

Os workflows N8N podem ser importados via interface em `/n8n/`.

## Fluxos sugeridos

### 1. Alerta de Risco no Telegram
**Trigger**: Webhook do Python (`POST /api/n8n/trigger/risk-alert`)
**Ação**: Envia mensagem formatada no Telegram do admin

### 2. Resumo Financeiro Semanal
**Trigger**: Cron (cada segunda 09:00)
**Ações**:
- Busca `GET /api/metrics` no backend
- Gera resumo com revenue, debt, net profit
- Envia e-mail ou Telegram

### 3. Notificação de Novo Usuário
**Trigger**: Webhook do Firebase / Nexus
**Ação**: Notifica admin no painel + Telegram

### 4. Auto-resposta Nexus + N8N
**Trigger**: Webhook quando Nexus detecta dúvida não respondida
**Ações**:
- Busca contexto do usuário no Firebase
- Cria ticket de suporte (planilha Google ou e-mail)
- Resposta automática via agente

## Como criar
1. Acesse `/n8n/` no admin panel
2. Crie um novo workflow
3. Adicione Webhook node como trigger
4. Configure o backend para chamar o webhook
