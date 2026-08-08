// ============ CONFIGURAÇÃO FIREBASE ============
const hubConfig = {
    apiKey: "AIzaSyDBa-yJArg3bkz9ouwqlNmPXKj_pTsl_1E",
    authDomain: "playearn-b001b.firebaseapp.com",
    databaseURL: "https://playearn-b001b-default-rtdb.firebaseio.com",
    projectId: "playearn-b001b",
    storageBucket: "playearn-b001b.appspot.com",
    messagingSenderId: "563829659490",
    appId: "1:563829659490:web:db9c377615bb5da941fe3b"
};

if (!firebase.apps.length) firebase.initializeApp(hubConfig);
let auth, hubDb;
try {
    auth = firebase.auth();
    hubDb = firebase.database();
} catch(e) {
    console.warn('[FIREBASE] Erro:', e.message);
}

// App Check (reCAPTCHA Enterprise) — cole a nova site key abaixo.
// Enquanto vazio, o App Check fica desativado no frontend.
const appCheckSiteKey = '6Leds3UtAAAAAGsYCTgVeGmQQfyzmSZc_KC73Wzs';
try {
    if (typeof firebase.appCheck !== 'undefined' && appCheckSiteKey) {
        firebase.appCheck().activate(
            appCheckSiteKey,
            new firebase.appCheck.ReCaptchaEnterpriseProvider(appCheckSiteKey)
        );
    }
} catch(e) {
    console.warn('[APP CHECK] Erro:', e.message);
}

const LOCAL_BACKEND = 'http://localhost:7861';
let BRASILHEXA_BACKEND_URL = localStorage.getItem('BRASILHEXA_BACKEND_URL') || LOCAL_BACKEND;

let rtState = {
    users: {},
    config: {},
    withdrawals: {},
    history: {},
    devices: {},
    logs: {},
    status: {},
    neural: {},
    stock: {},
    pending_withdrawals: {}
};

let _withdrawalFilter = 'all';
let lastWithdrawCount = 0;
let _pendingWrite = false;
