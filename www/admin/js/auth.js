let loginInProgress = false;

async function login() {
    console.log("[AUTH] Iniciando login...");
    const email = document.getElementById('login-email').value.trim();
    const pass = document.getElementById('login-pass').value;

    if (!email || !pass) return showToast('Preencha e-mail e senha.', 'error');
    if (loginInProgress) return;

    loginInProgress = true;
    try {
        await auth.signInWithEmailAndPassword(email, pass);
        // Reparo do custom claim admin: as Security Rules usam auth.token.admin, que
        // só aparece no token após o claim ser gravado e o token ser renovado.
        try {
            const u = auth.currentUser;
            if (u) {
                await fetch(`${BRASILHEXA_BACKEND_URL}/api/auth/refresh-admin-claim`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${await u.getIdToken()}`,
                        'Content-Type': 'application/json'
                    }
                });
                await u.getIdToken(true); // força renovação para propagar o claim
            }
        } catch (e) {
            console.warn('[AUTH] Reparo de claim admin falhou:', e);
        }
        loginInProgress = false;
        showToast('Acesso Master concedido!', 'success');
    } catch (e) {
        loginInProgress = false;
        console.error("[AUTH] Erro:", e);
        showToast('Credenciais inválidas.', 'error');
    }
}

function logout() {
    // TAREFA 5.1: remove o listener de `config/maintenance` antes de encerrar a
    // sessão, para não deixar realtime ativo após o logout (e evitar registro
    // duplicado caso initRealTimeSystem rode de novo).
    if (typeof stopMaintenanceListener === 'function') {
        try { stopMaintenanceListener(); } catch (e) { /* nosec */ }
    }
    if (auth) auth.signOut().then(() => location.reload());
}

// ─────────────────────────────────────────────
// TAREFA 4.7: Session idle timeout (15 min) com countdown de 60s.
// ─────────────────────────────────────────────
const IDLE_TIMEOUT_MS = 15 * 60 * 1000;   // 15 minutos de inatividade
const COUNTDOWN_MS = 60 * 1000;            // aviso nos últimos 60s
let _idleTimer = null;
let _idleCountdown = null;
let _idleLastActivity = Date.now();
let _idleCountdownActive = false;

function _resetIdleTimer() {
    _idleLastActivity = Date.now();
    if (_idleCountdownActive) {
        const banner = document.getElementById('idle-countdown');
        if (banner) banner.style.display = 'none';
        _idleCountdownActive = false;
    }
    if (_idleTimer) clearTimeout(_idleTimer);
    if (_idleCountdown) clearInterval(_idleCountdown);
    _idleTimer = setTimeout(_startIdleCountdown, IDLE_TIMEOUT_MS - COUNTDOWN_MS);
}

function _startIdleCountdown() {
    _idleCountdownActive = true;
    let remaining = COUNTDOWN_MS / 1000;
    const banner = document.getElementById('idle-countdown');
    if (banner) {
        banner.style.display = 'block';
        banner.textContent = `Sessão expira em ${remaining}s por inatividade.`;
    }
    _idleCountdown = setInterval(() => {
        remaining -= 1;
        if (banner) banner.textContent = `Sessão expira em ${remaining}s por inatividade.`;
        if (remaining <= 0) {
            clearInterval(_idleCountdown);
            showToast('Sessão encerrada por inatividade.', 'warning');
            logout();
        }
    }, 1000);
}

function _bindIdleListeners() {
    const events = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll'];
    events.forEach(ev => {
        window.addEventListener(ev, _resetIdleTimer, { passive: true });
    });
    _resetIdleTimer();
}

if (auth) {
    auth.onAuthStateChanged(user => {
        const loader = document.getElementById('loader');
        if (loader) {
            loader.style.opacity = '0';
            setTimeout(() => loader.remove(), 500);
        }

        if (user && user.email === 'alegomes488@gmail.com') {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('hub-app').style.display = 'grid';

            // --- PATCH 3: INJEÇÃO DE IDENTIDADE SEGURA ---
            const userDisplay = document.getElementById('user-display-name');
            const userAvatar = document.querySelector('.badge-avatar');
            const FALLBACK_NAME = "Administrador";
            if (userDisplay) {
                const displayName = user.displayName || user.email || FALLBACK_NAME;
                userDisplay.textContent = displayName;
                // Atualiza as iniciais do avatar dinamicamente (2 primeiras letras do nome)
                if (userAvatar) {
                    const initials = displayName.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
                    userAvatar.textContent = initials || 'AD';
                }
            }
            // ----------------------------------------------

            // --- JS-P0-05: INICIALIZAÇÃO COM EVENTO ---
            if (typeof initRealTimeSystem === 'function') {
                initRealTimeSystem();
            } else {
                window.addEventListener('realtime-ready', () => {
                    if (typeof initRealTimeSystem === 'function') {
                        initRealTimeSystem();
                    }
                }, { once: true });
            }
            // -------------------------------------------

            // TAREFA 4.7: inicia o idle timeout ao entrar (e para ao sair)
            _bindIdleListeners();
        } else {
            // Para o timer de idle ao deslogar
            if (_idleTimer) clearTimeout(_idleTimer);
            if (_idleCountdown) clearInterval(_idleCountdown);
            _idleCountdownActive = false;
            document.getElementById('login-screen').style.display = 'flex';
            document.getElementById('hub-app').style.display = 'none';
            if (user) auth.signOut();
        }
    });
}
