/**
 * ============================================================
 *  Watch / Monitoramento Canarinho — Módulo do Painel Admin
 *  Conecta sites, apps e APIs ao VAR via URL inserida no painel.
 *  Portado do monólito app.js (SYS_WATCH).
 * ============================================================
 */

let connectedProjects = [];
let currentWatchFilter = null;
let watchCurrentType = 'website';

function filterWatchProjects(type) {
    currentWatchFilter = type;
    renderWatchProjects();
}

function watchSelectType(el) {
    document.querySelectorAll('.watch-type-btn').forEach(b => {
        b.style.background = 'transparent';
        b.style.color = 'var(--text-secondary)';
    });
    el.style.background = 'rgba(0,243,255,0.1)';
    el.style.color = 'var(--cyan)';
    watchCurrentType = el.dataset.type;
}

async function watchConnectProject() {
    const url = document.getElementById('watch-project-url')?.value.trim();
    if (!url) return showToast("Digite a URL do projeto.", "error");

    const btn = document.querySelector('.btn-premium');
    const original = btn.textContent;
    btn.textContent = '🔍 ANALISANDO...';
    btn.disabled = true;

    try {
        const baseUrl = localStorage.getItem('BRASILHEXA_BACKEND_URL') || LOCAL_BACKEND;
        const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : '';
        const resp = await fetch(`${baseUrl}/api/project/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
            body: JSON.stringify({ type: watchCurrentType, identifier: url })
        });
        const data = await resp.json();

        if (data.status === 'success') {
            const projectId = 'PRJ' + Date.now().toString(36).toUpperCase();
            const projectData = {
                id: projectId,
                name: data.name || url,
                type: watchCurrentType,
                identifier: url,
                framework: data.framework || '—',
                addedAt: new Date().toISOString(),
                health: data.health || { status: 'online', last_checked: new Date().toISOString() }
            };

            const saveResp = await fetch(`${baseUrl}/api/project/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
                body: JSON.stringify({ id: projectId, data: projectData })
            });
            const saveData = await saveResp.json();

            if (saveData.status === 'success') {
                showToast(`✅ ${data.name || url} conectado ao Watch!`, "success");
                document.getElementById('watch-project-url').value = '';
                renderWatchProjects();
            } else {
                showToast("Erro ao salvar projeto.", "error");
            }
        } else {
            showToast(data.msg || "Falha ao conectar.", "error");
        }
    } catch (e) {
        showToast("Erro de conexão: " + e.message, "error");
    }

    btn.textContent = original;
    btn.disabled = false;
}

function watchFilter(type) {
    currentWatchFilter = type;
    document.querySelectorAll('.watch-filter-btn').forEach(b => {
        b.style.background = 'transparent';
        b.style.color = 'var(--text-secondary)';
    });
    const active = document.querySelector(`.watch-filter-btn[onclick*="'${type}'"]`);
    if (active) { active.style.background = 'rgba(0,243,255,0.1)'; active.style.color = 'var(--cyan)'; }
    renderWatchProjects();
}

function renderWatchProjects() {
    const container = document.getElementById('watch-projects-list');
    if (!container) return;

    const filtered = currentWatchFilter === null || currentWatchFilter === 'all' ? connectedProjects : connectedProjects.filter(p => p.type === currentWatchFilter);

    if (filtered.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-secondary); font-size: 12px;">Nenhum projeto ${currentWatchFilter && currentWatchFilter !== 'all' ? 'deste tipo' : ''} monitorado.</div>`;
        return;
    }

    container.innerHTML = filtered.map(p => {
        const health = p.health || {};
        const isOnline = health.status === 'online';
        const isDegraded = health.status === 'degraded';
        const statusClass = isOnline ? 'online' : (isDegraded ? 'degraded' : 'offline');

        const toPct = (v) => { const n = parseFloat(v); return (isFinite(n) && n >= 0) ? n.toFixed(0) + '%' : '--'; };
        const cpu = toPct(health.cpu);
        const ram = toPct(health.ram);
        const latMs = parseFloat(health.latency_ms);
        const latency = isFinite(latMs) && latMs >= 0 ? latMs.toFixed(0) + 'ms' : '--';
        const lastReport = health.last_report ? new Date(health.last_report).toLocaleTimeString() : null;

        const color = isOnline ? '#10b981' : (isDegraded ? '#fbbf24' : '#ef4444');
        const tech = escapeHtml(p.tech_stack ? p.tech_stack.join(', ') : (p.framework || 'N/A'));

        return `
            <div class="project-watch-card ${statusClass}" style="border-left-color: ${color}; position: relative; overflow: hidden;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <div style="font-weight: 800; font-size: 13px; color: white;">${escapeHtml(p.name || p.identifier)}</div>
                        <div style="font-size: 9px; color: var(--text-secondary); margin-top: 4px; text-transform: uppercase;">
                            TYPE: ${escapeHtml(p.type || '').toUpperCase()} | STACK: ${tech}
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-family: 'JetBrains Mono'; font-size: 11px; color: ${color}; font-weight: 900;">
                            ${isOnline ? '✓ ONLINE' : (isDegraded ? '⚠ DEGRADADO' : '✗ OFFLINE')}
                        </div>
                        <div style="font-size: 9px; opacity: 0.6; margin-top: 2px;">LATENCY: ${latency}</div>
                    </div>
                </div>

                <div style="margin-top: 15px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div class="mini-stat">
                        <div style="display: flex; justify-content: space-between; font-size: 9px; margin-bottom: 3px;">
                            <span>CPU</span> <span>${cpu}</span>
                        </div>
                        <div class="mini-bar-bg"><div class="mini-bar-fill" style="width: ${cpu}; background: ${color}"></div></div>
                    </div>
                    <div class="mini-stat">
                        <div style="display: flex; justify-content: space-between; font-size: 9px; margin-bottom: 3px;">
                            <span>RAM</span> <span>${ram}</span>
                        </div>
                        <div class="mini-bar-bg"><div class="mini-bar-fill" style="width: ${ram}; background: ${color}"></div></div>
                    </div>
                </div>

                <div style="margin-top: 10px; display: flex; gap: 5px;">
                     <button data-action="copy" data-id="${escapeHtml(p.id)}" class="btn-minimal" style="font-size: 8px; padding: 2px 6px;">ID</button>
                     <button data-action="agent" data-id="${escapeHtml(p.id)}" class="btn-minimal" style="font-size: 8px; padding: 2px 6px; color: var(--cyan);">AGENT</button>
                     <button data-action="toggle" data-id="${escapeHtml(p.id)}" data-identifier="${escapeHtml(p.identifier)}" class="btn-minimal" style="font-size: 8px; padding: 2px 6px; color: var(--warning);">${rtState?.config?.maintenance ? '🔌 ATIVAR' : '🔌 DESCONECTAR'}</button>
                </div>

                ${isOnline ? '<div class="pulse-ring"></div>' : ''}
            </div>
        `;
    }).join('');

    container.onclick = (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const id = btn.dataset.id;
        const action = btn.dataset.action;
        if (action === 'copy') copyToClipboard(id);
        else if (action === 'agent') installAgent(id);
        else if (action === 'toggle') toggleProjectConnection(id, btn.dataset.identifier);
    };
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => showToast("Copiado!", "success"));
}

function installAgent(projectId) {
    const baseUrl = localStorage.getItem('BRASILHEXA_BACKEND_URL') || LOCAL_BACKEND;
    const msg = document.createElement('div');
    msg.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:#0a0a0f;border:1px solid rgba(0,243,255,0.2);border-radius:12px;padding:25px;max-width:520px;width:90%;box-shadow:0 0 40px rgba(0,0,0,0.8);';
    msg.innerHTML = `
        <h3 style="color:var(--cyan);font-size:14px;margin-bottom:12px;">🤖 BRASIL HEXA AGENT</h3>
        <div style="font-size:11px;color:#94a3b8;line-height:1.6;margin-bottom:12px;">
            O agente reporta CPU, RAM e disco do servidor a cada 30s.
            Baixe o script (requer login), envie ao servidor Linux e execute.
            <strong style="color:#f8fafc;">Nunca execute scripts remotamente via pipe (wget | python3 -).</strong>
        </div>
        <pre style="background:rgba(0,0,0,0.4);padding:15px;border-radius:8px;font-size:11px;color:#94a3b8;white-space:pre-wrap;line-height:1.6;max-height:300px;overflow-y:auto;">pip install psutil
# edite BASE_URL e PROJECT_ID no topo do agent.py
python3 agent.py</pre>
        <div style="display:flex;gap:10px;margin-top:15px;">
            <button id="agent-download-btn" class="btn-premium" style="flex:1;padding:8px;border-radius:8px;font-size:10px;">⬇️ BAIXAR agent.py</button>
            <button onclick="this.closest('div[style]').remove()" class="btn-minimal" style="padding:8px 16px;font-size:10px;color:var(--danger);">FECHAR</button>
        </div>
    `;
    document.body.appendChild(msg);
    msg.onclick = (e) => { if (e.target === msg) msg.remove(); };

    const btn = msg.querySelector('#agent-download-btn');
    btn.onclick = async () => {
        try {
            const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : '';
            const resp = await fetch(`${baseUrl}/api/monitor/agent-script`, {
                headers: { 'Authorization': `Bearer ${idToken}` }
            });
            if (!resp.ok) throw new Error('Falha ao baixar (verifique se você está logado como admin)');
            const text = await resp.text();
            const blob = new Blob([text], { type: 'text/x-python' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'agent.py';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(a.href);
            showToast('agent.py baixado.', 'success');
        } catch (e) {
            showToast('Erro ao baixar o agente: ' + e.message, 'error');
        }
    };
}

function toggleProjectConnection(id, identifier) {
    const isMaint = rtState?.config?.maintenance || false;
    if (hubDb) {
        hubDb.ref('config').update({ maintenance: !isMaint })
            .then(() => showToast(!isMaint ? "Manutenção ativada." : "Manutenção desativada.", "info"))
            .catch(() => showToast("Erro ao atualizar configuração.", "error"));
    } else {
        showToast("Firebase indisponível.", "error");
    }
}

function removeProject(id) {
    if (!confirm("Remover este projeto do painel?")) return;
    connectedProjects = connectedProjects.filter(p => p.id !== id);
    renderWatchProjects();
    const baseUrl = localStorage.getItem('BRASILHEXA_BACKEND_URL') || LOCAL_BACKEND;
    const headers = { 'Content-Type': 'application/json' };
    if (auth && auth.currentUser) {
        auth.currentUser.getIdToken().then(t => headers['Authorization'] = `Bearer ${t}`).catch(() => {});
    }
    fetch(`${baseUrl}/api/project/remove`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ id })
    })
    .then(r => r.json())
    .then(resp => {
        showToast(resp.status === 'success' ? "Projeto removido." : "Erro ao remover.", resp.status === 'success' ? "info" : "error");
    })
    .catch(() => showToast("Erro de conexão.", "error"));
}
