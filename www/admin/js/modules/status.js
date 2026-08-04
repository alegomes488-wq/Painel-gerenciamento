function checkPythonCoreStatus() {
    const url = BRASILHEXA_BACKEND_URL ? `${BRASILHEXA_BACKEND_URL}/health` : '/health';
    fetch(url).then(r => {
        const dot = document.getElementById('python-core-ping');
        const text = document.getElementById('python-core-status');
        if (dot) dot.style.background = r.ok ? '#10b981' : '#ef4444';
        if (text) text.innerText = r.ok ? 'ONLINE' : 'OFFLINE';
    }).catch(() => {
        const dot = document.getElementById('python-core-ping');
        if (dot) dot.style.background = '#ef4444';
    });
}
