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
                if (link.onclick.toString().includes(filterType)) {
                    safeClass(link, 'add', 'active');
                }
            });
            // Aqui você pode adicionar lógica para filtrar a lista de projetos baseada no filterType
            if (typeof filterWatchProjects === 'function') filterWatchProjects(filterType);
        }
    }

    // 5. Atualizar o Título da Workspace
    // Gerencia auto-refresh do SecOps
    if (id === 'secops') {
        if (typeof startSecOpsAutoRefresh === 'function') startSecOpsAutoRefresh();
    } else {
        if (typeof stopSecOpsAutoRefresh === 'function') stopSecOpsAutoRefresh();
    }

    const titleMap = {
        watch:    '[SYS_VAR] // MONITORAMENTO',
        saques:   '[SYS_FINANCE] // SOLICITAÇÕES PIX',
        'ia-info':'[SYS_BRAIN] // INFORMAÇÕES IA',
        secops:   '[SYS_SECOPS] // SENTINEL AI — CYBER SECURITY',
        settings: '[SYS_CONFIG] // CONFIGURAÇÕES'
    };

    const titleEl = document.getElementById('current-panel-name');
    if (titleEl) {
        titleEl.textContent = titleMap[id] || '[BRASIL HEXA] // IA EXECUTIVA';
    }
}
