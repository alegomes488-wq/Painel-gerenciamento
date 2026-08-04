function updateTelemetria() {
    const hits = rtState.config?.stats?.hits || 0;
    const revEl = document.getElementById('header-rev');
    if (revEl) revEl.textContent = `R$ ${((hits / 1000) * (rtState.config?.cpm || 0.18) * 5.25).toFixed(2)}`;
}

function renderGlobalStats() {
    const usersCount = Object.keys(rtState.users).length;
    updateEl('stat-users', usersCount);
}
