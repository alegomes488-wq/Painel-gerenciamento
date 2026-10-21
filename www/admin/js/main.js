/**
 * ============================================================
 *  Sistema de Inicialização em Tempo Real — Painel Admin v4.1
 *  Com integração ao SecOps Sentinel AI
 * ============================================================
 */

/**
 * Verifica se o usuário atual tem claim admin antes de inicializar.
 */
async function ensureAdminBeforeInit() {
    if (!auth || !auth.currentUser) {
        console.warn('[SYSTEM] Usuário não autenticado. Abortando inicialização.');
        return false;
    }
    try {
        const tokenResult = await auth.currentUser.getIdTokenResult(true);
        if (!tokenResult.claims.admin) {
            console.warn('[SYSTEM] Usuário sem claim admin. Abortando inicialização.');
            return false;
        }
        return true;
    } catch (e) {
        console.error('[SYSTEM] Erro ao verificar claim:', e);
        return false;
    }
}

async function initRealTimeSystem() {
    console.log("[SYSTEM] Inicializando listeners...");

    // --- Firebase App Check Boot (Patch 3) ---
    if (window.__appCheckInstance) {
        try {
            console.log("[AppCheck] ⏳ Aguardando token inicial...");
            const token = await getAppCheckToken(true);
            if (token) {
                console.log("[AppCheck] ✅ Token inicial obtido. App pronto.");
            } else {
                console.warn("[AppCheck] ⚠️ Token inicial vazio.");
            }
        } catch (e) {
            console.error("[AppCheck] ❌ Falha crítica no boot:", e);
        }
    }
    // --- Fim Patch 3 ---

if (!hubDb) {
        console.warn('[SYSTEM] Firebase Database não disponível.');
        return;
    }

    // ── Health check do backend (tempo real) ──
    // TAREFA: checkPythonCoreStatus estava definida mas nunca era chamada — o badge
    // "Sistema" e o card SENTINEL ficavam estáticos. Agora é chamado no boot e a cada 15s.
    if (typeof checkPythonCoreStatus === 'function') {
        checkPythonCoreStatus();
        setInterval(checkPythonCoreStatus, 15000);
    }

    // Copiloto flutuante (Cyber Core IA) — ativo em todos os painéis.
    if (typeof hubWidgetStart === 'function') hubWidgetStart();

    // ── Usuários ──
    hubDb.ref('users').on('value', snap => {
        rtState.users = snap.val() || {};
        if (typeof renderUsersTable === 'function') renderUsersTable();
        if (typeof refreshUserCounters === 'function') refreshUserCounters();
        if (typeof refreshProjectDetail === 'function') refreshProjectDetail();
    }, err => {
        console.error('[SYSTEM] Erro no listener users:', err.message);
    });

    // ── Saques Pendentes ──
    hubDb.ref('admin/pending_withdrawals').on('value', snap => {
        const previous = Object.keys(rtState.pending_withdrawals || {}).length;
        rtState.pending_withdrawals = snap.val() || {};
        if (typeof renderWithdrawalsTable === 'function') renderWithdrawalsTable();

        // Alertar SecOps se houver novos saques
        const current = Object.keys(rtState.pending_withdrawals).length;
        if (current > 0 && current > previous) {
            _checkSecOpsAlert();
        }

        // Limpar alerta se a fila estiver vazia
        if (current === 0) {
            _setSecOpsNavAlert(false);
        }
    }, err => {
        console.error('[SYSTEM] Erro no listener pending_withdrawals:', err.message);
    });

    // ── Configurações ──
    hubDb.ref('config').on('value', snap => {
        rtState.config = snap.val() || {};
        if (typeof updateStatusIndicators === 'function') updateStatusIndicators();
        if (typeof loadConfigUI === 'function') loadConfigUI();
    }, err => {
        console.error('[SYSTEM] Erro no listener config:', err.message);
    });

    // ── TAREFA 5.1: Manutenção global (fonte de verdade = RTDB config/maintenance)
    // Registrado aqui, dentro de initRealTimeSystem, que só roda após login admin
    // confirmado — o listener nunca fica ativo para visitante deslogado.
    // initMaintenanceListener() é idempotente: protege contra registro duplo.
    if (typeof initMaintenanceListener === 'function') {
        initMaintenanceListener();
    }

// ── Nós (Projetos) — sincroniza o monitoramento Watch ──
    hubDb.ref('neural/nodes').on('value', snap => {
        if (!rtState.neural) rtState.neural = {};
        const nodes = snap.val() || {};
        rtState.neural.nodes = nodes;
        connectedProjects = Object.keys(nodes).map(k => ({ id: k, ...nodes[k] }));
        if (typeof renderWatchProjects === 'function') renderWatchProjects();
        // Atualiza o card SENTINEL com a contagem real de projetos online
        const online = connectedProjects.filter(p => (p.health ? (p.health.override ? p.health.override.status : p.health.status) : 'offline') === 'online').length;
        if (typeof updateSentinel === 'function') updateSentinel(null, online, connectedProjects.length);
    }, err => {
        console.error('[SYSTEM] Erro no listener neural/nodes:', err.message);
    });
}

/**
 * Verifica se há saques críticos na fila e acende o alerta na sidebar.
 * Só executa se o usuário for admin confirmado.
 */
async function _checkSecOpsAlert() {
    if (!auth.currentUser) return;

    // Verifica claim admin antes de fazer requisição
    try {
        const tokenResult = await auth.currentUser.getIdTokenResult();
        if (!tokenResult.claims.admin) {
            console.warn('[SECOPS] Sem claim admin. Abortando check.');
            return;
        }
    } catch (e) {
        console.error('[SECOPS] Erro ao verificar claim:', e);
        return;
    }

    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/secops/summary`, {
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        if (!resp.ok) {
            console.warn('[SECOPS] API retornou', resp.status);
            return;
        }
        const data = await resp.json();
        const rc = data.risk_counts || {};
        const hasCritical = (rc.critical > 0 || rc.high > 0);
        _setSecOpsNavAlert(hasCritical);
    } catch (e) {
        console.error('[SECOPS] Erro na requisição:', e.message);
    }
}

/**
 * Acende ou apaga o LED de alerta no menu SecOps
 */
function _setSecOpsNavAlert(show) {
    const dot = document.getElementById('secops-nav-alert');
    if (dot) dot.style.display = show ? 'inline-block' : 'none';
}


// SINALIZA QUE A FUNÇÃO ESTÁ PRONTA PARA SER CHAMADA
window.dispatchEvent(new CustomEvent('realtime-ready'));
