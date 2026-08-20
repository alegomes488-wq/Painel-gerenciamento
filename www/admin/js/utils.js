// --- Firebase App Check Interceptors (Patch 2/3) ---
async function getAppCheckToken(forceRefresh = false) {
    if (!window.__appCheckInstance) {
        console.warn('[AppCheck] Instância não encontrada. Verifique o Patch 1.');
        return null;
    }
    try {
        const result = await window.__appCheckInstance.getToken(forceRefresh);
        return result ? result.token : null;
    } catch (err) {
        console.error('[AppCheck] Erro ao obter token:', err);
        return null;
    }
}

// Intercepta fetch()
const _originalFetch = window.fetch;
window.fetch = async function(...args) {
    let [resource, config = {}] = args;
    const url = typeof resource === 'string' ? resource : resource.url;
    const isApiCall = url.includes('/api/') || url.includes(window.location.hostname);
    if (isApiCall) {
        const token = await getAppCheckToken(false);
        if (token) {
            config.headers = config.headers || {};
            if (config.headers instanceof Headers) {
                config.headers.set('X-Firebase-AppCheck', token);
            } else {
                config.headers['X-Firebase-AppCheck'] = token;
            }
        } else {
            console.warn('[AppCheck] Token ausente — request pode ser bloqueada pelo backend');
        }
    }
    return _originalFetch(resource, config);
};

// Intercepta XMLHttpRequest
const _originalXhrOpen = XMLHttpRequest.prototype.open;
const _originalXhrSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
const _originalXhrSend = XMLHttpRequest.prototype.send;

XMLHttpRequest.prototype.open = function(method, url, async, user, password) {
    this._appCheckUrl = url;
    this._appCheckHeaders = this._appCheckHeaders || {};
    return _originalXhrOpen.apply(this, arguments);
};

XMLHttpRequest.prototype.setRequestHeader = function(header, value) {
    this._appCheckHeaders = this._appCheckHeaders || {};
    this._appCheckHeaders[header] = value;
    return _originalXhrSetRequestHeader.apply(this, arguments);
};

XMLHttpRequest.prototype.send = async function(body) {
    const url = this._appCheckUrl || '';
    const isApiCall = url.includes('/api/') || url.includes(window.location.hostname);
    if (isApiCall) {
        const token = await getAppCheckToken(false);
        if (token) {
            _originalXhrSetRequestHeader.call(this, 'X-Firebase-AppCheck', token);
        }
    }
    return _originalXhrSend.apply(this, arguments);
};

console.log('[AppCheck] ✅ Interceptores de fetch() e XMLHttpRequest ativados');
// --- Fim Patch 2 ---

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
