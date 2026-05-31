// Firebase Service Worker (Versão 9 Compat - Estável)
importScripts('https://www.gstatic.com/firebasejs/9.6.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.6.1/firebase-messaging-compat.js');

const firebaseConfig = {
    apiKey: "AIzaSyDpB0dNIjeS6KnFDt057rbm0QGrcX3AvJE",
    authDomain: "playearn-b001b.firebaseapp.com",
    databaseURL: "https://playearn-b001b-default-rtdb.firebaseio.com",
    projectId: "playearn-b001b",
    messagingSenderId: "1071946051515",
    appId: "1:1071946051515:web:c065f49b1652397278602b"
};

firebase.initializeApp(firebaseConfig);

const messaging = firebase.messaging();

// Listener para mensagens em segundo plano
messaging.onBackgroundMessage((payload) => {
    console.log('[sw.js] Background Message:', payload);

    const title = payload.notification?.title || "CyberCore IA";
    const options = {
        body: payload.notification?.body || "Nova notificação do sistema.",
        icon: 'https://cdn-icons-png.flaticon.com/512/2592/2592186.png', // Ícone genérico de IA
        badge: 'https://cdn-icons-png.flaticon.com/512/2592/2592186.png',
        data: payload.data
    };

    self.registration.showNotification(title, options);
});
