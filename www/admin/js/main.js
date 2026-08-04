/**
 * ============================================================
 *  Sistema de Inicialização em Tempo Real — Painel Admin v4.1
 *  Com integração ao SecOps Sentinel AI
 * ============================================================
 */
function initRealTimeSystem() {
    console.log("[SYSTEM] Inicializando listeners...");

    if (hubDb) {
        // ── Usuários ──
        hubDb.ref('users').on('value', snap => {
            rtState.users = snap.val() || {};
            if (typeof renderUsersTable === 'function') renderUsersTable();
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
        });

        // ── Configurações ──
        hubDb.ref('config').on('value', snap => {
            rtState.config = snap.val() || {};
            if (typeof updateStatusIndicators === 'function') updateStatusIndicators();
        });

        // ── Nós (Projetos) — sincroniza o monitoramento Watch ──
        hubDb.ref('neural/nodes').on('value', snap => {
            if (!rtState.neural) rtState.neural = {};
            const nodes = snap.val() || {};
            rtState.neural.nodes = nodes;
            connectedProjects = Object.keys(nodes).map(k => ({ id: k, ...nodes[k] }));
            if (typeof renderWatchProjects === 'function') renderWatchProjects();
        });
    }
}

/**
 * Verifica se há saques críticos na fila e acende o alerta na sidebar
 */
async function _checkSecOpsAlert() {
    if (!auth.currentUser) return;
    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/secops/summary`, {
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const rc = data.risk_counts || {};
        const hasCritical = (rc.critical > 0 || rc.high > 0);
        _setSecOpsNavAlert(hasCritical);
    } catch (e) {
        // Silencioso — não bloqueia a interface
    }
}

/**
 * Acende ou apaga o LED de alerta no menu SecOps
 */
function _setSecOpsNavAlert(show) {
    const dot = document.getElementById('secops-nav-alert');
    if (dot) dot.style.display = show ? 'inline-block' : 'none';
}
