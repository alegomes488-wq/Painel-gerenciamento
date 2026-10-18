function checkPythonCoreStatus() {
    const url = BRASILHEXA_BACKEND_URL ? `${BRASILHEXA_BACKEND_URL}/health` : '/health';
    const dot = document.getElementById('python-core-ping');
    const badge = document.getElementById('python-core-status');

    fetch(url).then(r => r.json().then(data => ({ ok: r.ok, data })).catch(() => ({ ok: r.ok, data: {} })))
    .then(({ ok, data }) => {
        if (ok) {
            if (dot) dot.style.background = '#10b981';
            if (badge) badge.textContent = 'KERNEL ATIVO';
            // TAREFA 3.3: exibe banner de modo simulação se o backend indicar
            const banner = document.getElementById('simulation-banner');
            if (banner) banner.style.display = data.simulation === true ? 'block' : 'none';
        } else {
            if (dot) dot.style.background = '#ef4444';
            if (badge) badge.textContent = 'BACKEND INSTÁVEL';
        }
        // Atualiza o card SENTINEL conforme o estado real do backend
        updateSentinel(ok, null, null);
    }).catch(() => {
        if (dot) dot.style.background = '#ef4444';
        if (badge) badge.textContent = 'BACKEND INSTÁVEL';
        updateSentinel(false, null, null);
    });
}

/**
 * Atualiza o card [SYS_CORE] // SENTINEL ENGINE em tempo real.
 * backendOk: null = ainda verificando; true = online; false = offline.
 * onlineCount/totalCount: números de projetos monitorados (opcional).
 */
function updateSentinel(backendOk, onlineCount, totalCount) {
    const dot = document.getElementById('sentinel-dot');
    const label = document.getElementById('sentinel-label');
    const sub = document.getElementById('sentinel-sub');
    if (!dot || !label) return;

    if (backendOk === true) {
        dot.style.background = '#10b981';
        dot.style.boxShadow = '0 0 6px #10b981';
        label.textContent = 'SENTINEL ATIVO';
        label.style.color = 'var(--text-secondary)';
    } else if (backendOk === false) {
        dot.style.background = '#ef4444';
        dot.style.boxShadow = '0 0 6px #ef4444';
        label.textContent = 'BACKEND OFFLINE';
        label.style.color = '#ef4444';
    } else {
        dot.style.background = '#f59e0b';
        dot.style.boxShadow = '0 0 6px #f59e0b';
        label.textContent = 'VERIFICANDO...';
    }

    if (sub) {
        if (typeof onlineCount === 'number') {
            sub.textContent = onlineCount > 0
                ? `${onlineCount} projeto(s) monitorado(s) em tempo real`
                : 'Nenhum projeto monitorado';
        } else if (backendOk === true) {
            sub.textContent = 'Backend conectado — monitoramento ativo';
        } else if (backendOk === false) {
            sub.textContent = 'Backend indisponível — dados podem estar desatualizados';
        }
    }
}
