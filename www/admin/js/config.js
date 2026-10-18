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
// ============= APP CHECK (M1) =============
const appCheckSiteKey = '6Leds3UtAAAAAGsYCTgVeGmQQfyzmSZc_KC73Wzs';

try {
    if (typeof firebase.appCheck !== 'undefined' && appCheckSiteKey) {
        // TENTATIVA 1: reCAPTCHA Enterprise (Sintaxe correta)
        try {
            firebase.appCheck().activate(
                new firebase.appCheck.ReCaptchaEnterpriseProvider(appCheckSiteKey),
                true
            );
            console.log('[APP CHECK] Enterprise ativado.');
        } catch (enterpriseErr) {
            // TENTATIVA 2: Fallback para reCAPTCHA v3 padrão
            console.warn('[APP CHECK] Enterprise falhou, usando v3:', enterpriseErr.message);
            firebase.appCheck().activate(appCheckSiteKey, true);
            console.log('[APP CHECK] v3 ativado.');
        }
        // --- Firebase App Check (Patch 1/3): expõe a instância para os módulos ---
        window.__appCheckInstance = firebase.appCheck();
        // --- Fim Patch 1 ---
    }
} catch (e) {
    console.error('[APP CHECK] Falha crítica na ativação:', e.message);
}

// ─────────────────────────────────────────────────────────────
// TAREFA 3.9 + FASE 5 (correção autorizada): prefixo VAZIO = mesma origem.
//
// O painel (www/admin) e as rotas /api/* são servidos pelo MESMO processo
// FastAPI — ver backend/app/main.py:157, que monta StaticFiles(ADMIN_DIR) em
// "/", e os 5 include_router que expõem /api/* e /payments/*. Confirmado nos
// dois lugares que sobem o app: `backend/admin_panel.py` e `README.md:34`.
// Logo o prefixo correto é VAZIO: fetch('/api/admin/maintenance') resolve para
// a própria origem.
//
// ANTES era 'http://localhost:7861' hardcoded, e o override
// window.__BACKEND_URL__ que o comentário prometia NÃO era definido por nada
// no repositório (3 ocorrências, todas aqui; zero em backend/**/*.py; zero
// scripts inline no index.html). Efeito medido: TODA chamada de API apontava
// para a porta 7861 da máquina de quem abriu o painel, inclusive em produção —
// inclusive POST /api/admin/maintenance, /api/admin/ban e /payments/approve.
// Evidência: ADMIN-PANEL-CONNECTION-AUDIT.md.
//
// NUMERAÇÃO DE PORTA NÃO IMPORTA AQUI: ADMIN_PORT=7860, BACKEND_PORT=7861 e
// Dockerfile ENV PORT=7860 são apenas invocações diferentes do mesmo app.
//
// NUNCA ler de localStorage (TAREFA 3.9, mantida): permitiria a quem abrir o
// devtools redirecionar todas as chamadas da API, com o token de login junto.
// O override continua existindo para o caso de painel e API em hosts distintos,
// e só pode vir de variável injetada pelo servidor ou pelo build.
const LOCAL_BACKEND = '';
const BRASILHEXA_BACKEND_URL = (typeof window !== 'undefined' && window.__BACKEND_URL__)
    ? window.__BACKEND_URL__
    : LOCAL_BACKEND;

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
