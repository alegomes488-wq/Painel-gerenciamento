window.safeClass = (idOrEl, method, className) => {
    const el = (typeof idOrEl === 'string') ? document.getElementById(idOrEl) : idOrEl;
    if (el && el.classList) {
        if (Array.isArray(className)) {
            className.forEach(c => el.classList[method](c));
        } else {
            el.classList[method](className);
        }
    }
};

function escapeHtml(text) {
    if (!text) return '';
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(String(text)));
    return d.innerHTML;
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `hexa-toast toast-${type}`;
    let icon = 'ℹ️';
    if (type === 'error') icon = '❌';
    if (type === 'success') icon = '✅';
    if (type === 'warning') icon = '⚠️';
    const iconEl = document.createElement('span');
    iconEl.className = 'toast-icon';
    iconEl.textContent = icon;
    const msgEl = document.createElement('span');
    msgEl.className = 'toast-msg';
    msgEl.textContent = String(message ?? '');
    toast.appendChild(iconEl);
    toast.appendChild(msgEl);
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'toastExit 0.5s forwards';
        setTimeout(() => toast.remove(), 500);
    }, 4000);
}

function updateEl(id, val) {
    const el = document.getElementById(id);
    if (el && val !== undefined) el.innerText = val;
}
