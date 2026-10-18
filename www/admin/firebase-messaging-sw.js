// ⚠️ TAREFA 2.9: Service Worker unificado.
// Este arquivo (firebase-messaging-sw.js) usava uma configuração Firebase de OUTRO
// projeto (senderId/AppId divergentes de config.js) — risco de notificações e
// mensagens apontarem para o app errado.
// O Service Worker canônico é `sw.js` (mesma config de js/config.js).
// Este arquivo é mantido apenas como redirecionamento/segurança caso alguém o
// registre por engano: redireciona para o Firebase do projeto playearn-b001b.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

