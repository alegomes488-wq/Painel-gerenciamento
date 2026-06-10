// Service Worker CineCash IA (Versão Compat)
importScripts('https://www.gstatic.com/firebasejs/9.6.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.6.1/firebase-messaging-compat.js');

const firebaseConfig = {
    apiKey: "AIzaSyDBa-yJArg3bkz9ouwqlNmPXKj_pTsl_1E",
    authDomain: "playearn-b001b.firebaseapp.com",
    databaseURL: "https://playearn-b001b-default-rtdb.firebaseio.com",
    projectId: "playearn-b001b",
    storageBucket: "playearn-b001b.appspot.com",
    messagingSenderId: "563829659490",
    appId: "1:563829659490:web:a2f4a40d4a3d165541fe3b"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
    console.log('[sw.js] Mensagem em background:', payload);
    const title = payload.notification?.title || "CineCash IA";
    const options = {
        body: payload.notification?.body || "Você tem uma nova atualização.",
        icon: '/bg.png',
        data: payload.data
    };
    self.registration.showNotification(title, options);
});

const CACHE_NAME = 'cinecash-v12';

self.addEventListener('install', e => {
    self.skipWaiting();
    e.waitUntil(
        caches.open(CACHE_NAME).then(cache =>
            cache.addAll(['./', './index.html', './style.css']).catch(() => {})
        )
    );
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET' || e.request.url.includes('hf.space')) {
        return;
    }

    e.respondWith(
        fetch(e.request)
            .then(response => {
                if (!response || response.status !== 200 || response.type !== 'basic') {
                    return caches.match(e.request).then(cached => cached || response);
                }
                const clone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
                return response;
            })
            .catch(() => caches.match(e.request).then(cached => cached || new Response('', { status: 503 })))
    );
});

