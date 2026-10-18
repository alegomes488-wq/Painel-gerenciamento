// Firebase Service Worker (Sincronizado)
importScripts('https://www.gstatic.com/firebasejs/9.6.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.6.1/firebase-messaging-compat.js');

const firebaseConfig = {
    apiKey: "AIzaSyDBa-yJArg3bkz9ouwqlNmPXKj_pTsl_1E",
    authDomain: "playearn-b001b.firebaseapp.com",
    databaseURL: "https://playearn-b001b-default-rtdb.firebaseio.com",
    projectId: "playearn-b001b",
    storageBucket: "playearn-b001b.appspot.com",
    messagingSenderId: "563829659490",
    appId: "1:563829659490:web:db9c377615bb5da941fe3b"
};

firebase.initializeApp(firebaseConfig);

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
    console.log('[sw.js] Background Message:', payload);
    const title = payload.notification?.title || "CyberCore IA";
    const options = {
        body: payload.notification?.body || "Nova notificação do sistema.",
        icon: 'https://cdn-icons-png.flaticon.com/512/2592/2592186.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/2592/2592186.png',
        data: payload.data
    };
    self.registration.showNotification(title, options);
});
