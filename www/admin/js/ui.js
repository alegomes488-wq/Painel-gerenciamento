function showPanel(id, filterType = null) {
    // 1. Ocultar todos os painéis e remover classes ativas dos botões
    document.querySelectorAll('.panel-view').forEach(p => safeClass(p, 'remove', 'active'));
    document.querySelectorAll('.nav-link').forEach(b => safeClass(b, 'remove', 'active'));
    document.querySelectorAll('.sub-link').forEach(b => safeClass(b, 'remove', 'active'));

    // 2. Mostrar o painel alvo
    const target = document.getElementById('panel-' + id);
    if (target) {
        safeClass(target, 'add', 'active');
    }

    // 3. Destacar o botão correspondente no menu
    const navBtn = document.getElementById('btn-nav-' + id);
    if (navBtn) {
        safeClass(navBtn, 'add', 'active');
    }

    // 4. Gerenciamento de Submenus (Monitoramento)
    if (id === 'watch') {
        const watchBtn = document.getElementById('btn-nav-watch');
        if (watchBtn) safeClass(watchBtn, 'add', 'active');

        if (filterType) {
            document.querySelectorAll('.sub-link').forEach(link => {
                if (link.onclick && link.onclick.toString().includes(filterType)) {
                    safeClass(link, 'add', 'active');
                }
            });
            if (typeof filterWatchProjects === 'function') filterWatchProjects(filterType);
        }
    }

    // 5. Gerencia auto-refresh do SecOps — SÓ inicia se usuário for admin
    if (id === 'secops') {
        _startSecOpsIfAdmin();
    } else {
        if (typeof stopSecOpsAutoRefresh === 'function') stopSecOpsAutoRefresh();
    }

    // 5.2 Painel HUB — renderiza e inicia auto-refresh (falha graciosamente se não admin)
    if (id === 'hub') {
        if (typeof startHubPanel === 'function') startHubPanel();
    } else {
        if (typeof stopHubAutoRefresh === 'function') stopHubAutoRefresh();
    }

    // 5.3 Copiloto flutuante — disponível em qualquer painel (idempotente).
    if (typeof hubWidgetStart === 'function') hubWidgetStart();

    if (id === 'settings' && typeof loadConfigUI === 'function') {
        loadConfigUI();
    }

    const titleMap = {
        hub:      '[SYS_HUB] // PAINEL HUB — DESEMPENHO / ACOMPANHAMENTO / SEGURANÇA',
        watch:    '[SYS_CORE] // MONITORAMENTO',
        saques:   '[SYS_FINANCE] // SOLICITAÇÕES PIX',
        'ia-info':'[SYS_BRAIN] // INFORMAÇÕES IA',
        secops:   '[SYS_SECOPS] // SENTINEL AI — CYBER SECURITY',
        settings: '[SYS_CONFIG] // CONFIGURAÇÕES'
    };

    const titleEl = document.getElementById('current-panel-name');
    if (titleEl) {
        titleEl.textContent = titleMap[id] || '[CYBERCORE IA] // IA EXECUTIVA';
    }
}

/**
 * Inicia o auto-refresh do SecOps apenas se o usuário for admin.
 * Evita requisições 401 desnecessárias.
 */
async function _startSecOpsIfAdmin() {
    if (!auth || !auth.currentUser) return;
    try {
        const tokenResult = await auth.currentUser.getIdTokenResult();
        if (tokenResult.claims.admin && typeof startSecOpsAutoRefresh === 'function') {
            startSecOpsAutoRefresh();
        } else {
            console.warn('[UI] Usuário não é admin. SecOps auto-refresh não iniciado.');
        }
    } catch (e) {
        console.error('[UI] Erro ao verificar admin para SecOps:', e);
    }
}
