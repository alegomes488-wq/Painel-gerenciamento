/**
 * ============================================================
 *  Watch / Monitoramento Canarinho “ Módulo do Painel Admin
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
        b.classList.remove('active');
        b.style.background = '';
        b.style.color = '';
    });
    el.classList.add('active');
    watchCurrentType = el.dataset.type;

    const input = document.getElementById('watch-project-url');
    const meta = WATCH_FIELD_META[watchCurrentType];
    if (input && meta) {
        input.placeholder = meta.placeholder;
        input.value = '';
        input.focus();
    }
    validateWatchInput();
}

// Textos do campo de entrada conforme o tipo de projeto selecionado
const WATCH_FIELD_META = {
    website: { placeholder: 'https://meusite.com.br' },
    android: { placeholder: 'Link da loja (play.google.com / apps.apple.com) ou pacote (com.empresa.app)' },
    api: { placeholder: 'https://api.suaempresa.com/v1' },
};

// Validacao em tempo real do identificador conforme o tipo selecionado
const WATCH_VALIDATORS = {
    website: v => /^https:\/\/([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(:\d{1,5})?(\/.*)?$/i.test(v),
    android: v => /^https:\/\/(play\.google\.com|apps\.apple\.com)\/.+/i.test(v) ||
                 /^([a-z0-9]+\.){2,}[a-z0-9]+$/i.test(v),
    api: v => /^https:\/\/([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(\/\S*)?$/i.test(v),
};

function validateWatchInput() {
    const input = document.getElementById('watch-project-url');
    const btn = document.getElementById('watch-connect-btn');
    if (!input || !btn) return;
    const value = input.value.trim();
    const validator = WATCH_VALIDATORS[watchCurrentType] || WATCH_VALIDATORS.website;

    input.classList.remove('is-valid', 'is-invalid');
    if (!value) {
        btn.disabled = true;
        btn.style.opacity = '0.4';
        btn.style.cursor = 'not-allowed';
        return;
    }
    const valid = validator(value);
    btn.disabled = !valid;
    btn.style.opacity = valid ? '1' : '0.4';
    btn.style.cursor = valid ? 'pointer' : 'not-allowed';
    input.classList.toggle('is-valid', valid);
    input.classList.toggle('is-invalid', !valid);
}

async function watchConnectProject() {
    const url = document.getElementById('watch-project-url')?.value.trim();
    if (!url) return showToast("Digite a URL do projeto.", "error");

    const btn = document.getElementById('watch-connect-btn');
    const original = btn.textContent;
    btn.textContent = 'ANALISANDO...';
    btn.disabled = true;

    try {
        // TAREFA 3.1: endpoints /api/project/analyze e /api/project/save agora existem.
        // O ID do projeto é gerado no SERVIDOR (push key), nunca aqui no cliente.
        const baseUrl = BRASILHEXA_BACKEND_URL;
        const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : '';

        // 1) Analisa (retorna nome/framework/health) “ sem gravar
        const resp = await fetch(`${baseUrl}/api/project/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
            body: JSON.stringify({ type: watchCurrentType, identifier: url })
        });
        const data = await resp.json();
        if (!resp.ok || data.status !== 'success') {
            throw new Error(data.detail || data.msg || 'Falha ao conectar');
        }

        // 2) Salva “ o backend valida e gera o projectId
        const saveResp = await fetch(`${baseUrl}/api/project/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
            body: JSON.stringify({
                type: watchCurrentType,
                identifier: url,
                name: data.name || url,
                framework: data.framework || '“'
            })
        });
        const saveData = await saveResp.json();
        if (!saveResp.ok || saveData.status !== 'success') {
            throw new Error(saveData.detail || 'Erro ao salvar projeto');
        }

        showToast(`âœ… ${data.name || url} conectado ao Watch!`, "success");
        document.getElementById('watch-project-url').value = '';
        // RTDB listener (main.js) re-renderiza automaticamente com o novo node
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

// TAREFA 3.2: status efetivo = health.override (operador) tem prioridade sobre
// health.reported (agente). Se não houver override, usa o status reportado.
function _effectiveStatus(project) {
    const health = project?.health || {};
    return health.override?.status || health.status || 'offline';
}

function getUserCount() {
    return Object.keys(rtState.users || {}).length;
}

/**
 * Contador de usuários cadastrados exibido no card do projeto monitorado,
 * ao lado dos botões de ação/manutenção. Chamado sempre que o nó `users`
 * muda (main.js) e a cada render da lista de projetos.
 */
function refreshUserCounters() {
    const n = getUserCount();
    document.querySelectorAll('[data-user-counter]').forEach(el => {
        el.innerHTML = `👤 <b>${n}</b> USUÁRIOS`;
    });
}

// ─────────────────────────────────────────────────────────────
//  Detalhe do projeto monitorado + usuários cadastrados
// ─────────────────────────────────────────────────────────────
let _projectDetailId = null;

function _pdUserArray() {
    return Object.entries(rtState.users || {})
        .map(([uid, u]) => ({ uid, ...(u || {}) }))
        .sort((a, b) => _pdUserName(a).localeCompare(_pdUserName(b), 'pt-BR'));
}

function _pdUserName(u) {
    if (!u) return '—';
    const full = u.fullname || [u.firstname, u.lastname].filter(Boolean).join(' ');
    return full || u.username || u.email || '—';
}

function _pdIsBanned(u) {
    return !!(u && (u.status === 'banido' || u.banned === true));
}

function _pdDate(u) {
    const raw = u && (u.createdAt || u.created_at || u.registeredAt);
    const n = Number(raw);
    if (!isFinite(n) || n <= 0) return '—';
    try { return new Date(n).toLocaleString('pt-BR'); } catch (_) { return '—'; }
}

function _pdMoney(v) {
    const n = parseFloat(v);
    return 'R$ ' + (isFinite(n) ? n : 0).toFixed(2);
}

function _pdUserStats() {
    const users = _pdUserArray();
    const banned = users.filter(_pdIsBanned).length;
    const active = users.length - banned;
    const total = users.reduce((s, u) => s + (parseFloat(u.balance) || 0), 0);
    return `${users.length} cadastrado(s) · <b style="color:#10b981">${active} ativo(s)</b> · <b style="color:#f87171">${banned} banido(s)</b> · saldo total <b style="color:var(--cyan)">${_pdMoney(total)}</b>`;
}

function _pdFilterUsers(query) {
    const q = (query || '').trim().toLowerCase();
    if (!q) return _pdUserArray();
    return _pdUserArray().filter(u =>
        (_pdUserName(u) + ' ' + (u.email || '') + ' ' + (u.username || '') + ' ' + u.uid).toLowerCase().includes(q)
    );
}

function _pdUserRows(query) {
    const list = _pdFilterUsers(query);
    if (!list.length) {
        return `<tr><td colspan="7" class="pd-empty">Nenhum usuário encontrado${query ? ' para "' + escapeHtml(query) + '"' : ''}.</td></tr>`;
    }
    return list.map(u => {
        const banned = _pdIsBanned(u);
        const uidSafe = escapeHtml(u.uid);
        return `<tr>
            <td>
                <div class="pd-user-name">${escapeHtml(_pdUserName(u))}</div>
                <div class="pd-user-uid">${uidSafe}</div>
            </td>
            <td>${escapeHtml(u.email || '—')}</td>
            <td class="pd-balance">${_pdMoney(u.balance)}</td>
            <td>${Number(u.videosWatched || 0)}</td>
            <td>${Number(u.referralCount || 0)}</td>
            <td>${banned ? '<span class="status-tag offline">● Banido</span>' : '<span class="status-tag online">● Ativo</span>'}</td>
            <td>
                <button class="btn-table-action" onclick="toggleUserBan('${uidSafe}', ${!banned})">${banned ? 'REATIVAR' : 'BANIR'}</button>
            </td>
        </tr>`;
    }).join('');
}

function _pdRefreshUsers() {
    const tbody = document.getElementById('pd-users-tbody');
    if (!tbody) return;
    const q = document.getElementById('pd-user-search')?.value || '';
    tbody.innerHTML = _pdUserRows(q);
    const stats = document.getElementById('pd-user-stats');
    if (stats) stats.innerHTML = _pdUserStats();
    const count = document.getElementById('pd-users-count');
    if (count) count.textContent = _pdUserArray().length;
}

/** Re-renderiza a lista de usuários do modal aberto quando o RTDB muda. */
function refreshProjectDetail() {
    if (!_projectDetailId) return;
    _pdRefreshUsers();
}

function openProjectDetail(projectId) {
    const p = connectedProjects.find(x => x.id === projectId);
    if (!p) { showToast('Projeto não encontrado.', 'error'); return; }

    _projectDetailId = projectId;
    document.getElementById('project-detail-overlay')?.remove();

    const health = p.health || {};
    const status = _effectiveStatus(p);
    const color = status === 'online' ? '#10b981' : (status === 'degraded' ? '#fbbf24' : '#ef4444');
    const latency = isFinite(parseFloat(health.latency_ms)) ? parseFloat(health.latency_ms).toFixed(0) + 'ms' : '—';
    const lastReport = health.last_report ? new Date(health.last_report).toLocaleString('pt-BR') : '—';
    const cpu = isFinite(parseFloat(health.cpu)) ? parseFloat(health.cpu).toFixed(0) + '%' : '—';
    const ram = isFinite(parseFloat(health.ram)) ? parseFloat(health.ram).toFixed(0) + '%' : '—';
    const tech = p.tech_stack ? p.tech_stack.join(', ') : (p.framework || '—');
    const badge = status === 'online' ? '✓ ONLINE' : (status === 'degraded' ? '⚠ DEGRADADO' : '✗ OFFLINE');

    const overlay = document.createElement('div');
    overlay.className = 'project-detail-overlay';
    overlay.id = 'project-detail-overlay';
    overlay.innerHTML = `
        <div class="project-detail-box" role="dialog" aria-modal="true" aria-label="Detalhes do projeto">
            <div class="project-detail-header">
                <div style="min-width:0;">
                    <div class="project-detail-title">${escapeHtml(p.name || p.identifier || 'Projeto')}</div>
                    <div class="project-detail-sub">${escapeHtml(p.identifier || '')}</div>
                    <div style="margin-top:8px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                        <span class="status-tag ${status === 'online' ? 'online' : (status === 'degraded' ? 'degraded' : 'offline')}" style="color:${color};">${badge}</span>
                        <span style="font-size:9px;color:var(--text-muted);text-transform:uppercase;">TYPE: ${escapeHtml(p.type || '—')} · STACK: ${escapeHtml(tech)}</span>
                    </div>
                </div>
                <button class="project-detail-close" onclick="closeProjectDetail()" aria-label="Fechar">✕</button>
            </div>

            <div class="project-detail-body">
                <div class="pd-info-grid">
                    <div class="pd-info-item"><span>Latência</span><strong style="color:${color}">${latency}</strong></div>
                    <div class="pd-info-item"><span>Último relatório</span><strong>${lastReport}</strong></div>
                    <div class="pd-info-item"><span>CPU</span><strong>${cpu}</strong></div>
                    <div class="pd-info-item"><span>RAM</span><strong>${ram}</strong></div>
                    <div class="pd-info-item"><span>ID do projeto</span><strong style="font-size:10px;">${escapeHtml(p.id)}</strong></div>
                </div>

                <div class="pd-users-head">
                    <div>
                        <div class="pd-users-title">👤 Usuários cadastrados — <b id="pd-users-count">${_pdUserArray().length}</b></div>
                        <div class="pd-user-stats" id="pd-user-stats">${_pdUserStats()}</div>
                    </div>
                    <div class="pd-users-actions">
                        <button class="pd-btn" onclick="copyProjectUserEmails()">COPIAR E-MAILS</button>
                        <button class="pd-btn" onclick="exportProjectUsersCsv()">EXPORTAR CSV</button>
                    </div>
                </div>

                <div class="pd-search-row">
                    <input id="pd-user-search" class="pd-search" type="search" autocomplete="off"
                           placeholder="Buscar por nome, e-mail, @usuário ou UID..."
                           oninput="_pdRefreshUsers()">
                </div>

                <div class="pd-table-wrap">
                    <table class="pd-table">
                        <thead>
                            <tr>
                                <th>Usuário</th>
                                <th>E-mail</th>
                                <th>Saldo</th>
                                <th>Vídeos</th>
                                <th>Indicações</th>
                                <th>Status</th>
                                <th>Ação</th>
                            </tr>
                        </thead>
                        <tbody id="pd-users-tbody">${_pdUserRows('')}</tbody>
                    </table>
                </div>
            </div>
        </div>`;

    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeProjectDetail(); });
    document.addEventListener('keydown', _pdEscClose);
    setTimeout(() => document.getElementById('pd-user-search')?.focus(), 60);
}

function closeProjectDetail() {
    document.getElementById('project-detail-overlay')?.remove();
    document.removeEventListener('keydown', _pdEscClose);
    _projectDetailId = null;
}

function _pdEscClose(e) {
    if (e.key === 'Escape') closeProjectDetail();
}

function copyProjectUserEmails() {
    const emails = _pdUserArray().map(u => u.email).filter(Boolean);
    if (!emails.length) { showToast('Nenhum e-mail cadastrado.', 'info'); return; }
    copyToClipboard(emails.join(', '));
    showToast(`${emails.length} e-mail(s) copiado(s).`, 'success');
}

function exportProjectUsersCsv() {
    const users = _pdUserArray();
    if (!users.length) { showToast('Nenhum usuário para exportar.', 'info'); return; }
    const esc = (v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    const header = ['UID', 'Nome', 'E-mail', 'Usuário', 'Saldo', 'Vídeos', 'Indicações', 'Status', 'Cadastro', 'Provedor'];
    const lines = users.map(u => [
        u.uid,
        _pdUserName(u),
        u.email || '',
        u.username || '',
        (parseFloat(u.balance) || 0).toFixed(2).replace('.', ','),
        Number(u.videosWatched || 0),
        Number(u.referralCount || 0),
        _pdIsBanned(u) ? 'Banido' : 'Ativo',
        _pdDate(u),
        u.auth_provider || 'email'
    ].map(esc).join(';'));
    const csv = '\uFEFF' + [header.map(esc).join(';'), ...lines].join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `usuarios-${(new Date()).toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    showToast(`${users.length} usuário(s) exportado(s).`, 'success');
}

function renderWatchProjects() {
    const container = document.getElementById('watch-projects-list');
    if (!container) return;
    if (typeof watchStartAiTicker === 'function') watchStartAiTicker();

    const filtered = currentWatchFilter === null || currentWatchFilter === 'all' ? connectedProjects : connectedProjects.filter(p => p.type === currentWatchFilter);

    if (filtered.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-secondary); font-size: 12px;">Nenhum projeto ${currentWatchFilter && currentWatchFilter !== 'all' ? 'deste tipo' : ''} monitorado.</div>`;
        return;
    }

    container.innerHTML = filtered.map(p => {
        const health = p.health || {};
        const isOnline = _effectiveStatus(p) === 'online';
        const isDegraded = _effectiveStatus(p) === 'degraded';
        const statusClass = isOnline ? 'online' : (isDegraded ? 'degraded' : 'offline');

        const toPct = (v) => { const n = parseFloat(v); return (isFinite(n) && n >= 0) ? n.toFixed(0) + '%' : '--'; };
        const cpu = toPct(health.cpu);
        const ram = toPct(health.ram);
        const latMs = parseFloat(health.latency_ms);
        const latency = isFinite(latMs) && latMs >= 0 ? latMs.toFixed(0) + 'ms' : '--';
        const lastReport = health.last_report ? new Date(health.last_report).toLocaleTimeString() : null;

        const color = isOnline ? '#10b981' : (isDegraded ? '#fbbf24' : '#ef4444');
        const tech = escapeHtml(p.tech_stack ? p.tech_stack.join(', ') : (p.framework || 'N/A'));
        const typeLabel = ({ website: 'WEB', android: 'APK', ios: 'iOS', api: 'API' })[p.type] || (p.type || 'N/A').toUpperCase();

        return `
            <div class="project-watch-card ${statusClass}" data-project-id="${escapeHtml(p.id)}" style="border-left-color: ${color}; position: relative; overflow: hidden;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <div style="font-weight: 800; font-size: 13px; color: white;">${escapeHtml(p.name || p.identifier)}</div>
                        <div style="font-size: 9px; color: var(--text-secondary); margin-top: 4px; text-transform: uppercase;">
                            TYPE: ${escapeHtml(p.type || '').toUpperCase()} | STACK: ${tech}
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-family: 'JetBrains Mono'; font-size: 11px; color: ${color}; font-weight: 900;">
                            ${isOnline ? '✓ ONLINE' : (isDegraded ? 'âš  DEGRADADO' : '✗ OFFLINE')}
                        </div>
                        <div style="font-size: 9px; opacity: 0.6; margin-top: 2px;">LATENCY: ${latency}</div>
                    </div>
                </div>

                <div class="project-chip-row">
                    <span class="project-chip" style="color:${color};border-color:${color}55;">${escapeHtml(typeLabel)}</span>
                    <span class="project-chip">CPU <b>${cpu}</b></span>
                    <span class="project-chip">RAM <b>${ram}</b></span>
                    ${isFinite(latMs) ? `<span class="project-chip">LAT <b>${latency}</b></span>` : ''}
                    ${lastReport ? `<span class="project-chip muted">${escapeHtml(lastReport)}</span>` : ''}
                </div>


                <div style="margin-top: 10px; display: flex; gap: 5px; align-items: center;">
                      <button data-action="copy" data-id="${escapeHtml(p.id)}" class="btn-minimal" style="font-size: 8px; padding: 2px 6px;">ID</button>
                      <button data-action="agent" data-id="${escapeHtml(p.id)}" class="btn-minimal" style="font-size: 8px; padding: 2px 6px; color: var(--cyan);">AGENT</button>
                      ${typeof renderMaintenanceButton === 'function' ? renderMaintenanceButton() : ''}
                      <button data-action="detail" data-id="${escapeHtml(p.id)}" data-user-counter class="btn-minimal pd-user-counter-btn" title="Clique para ver os detalhes do projeto e todos os usuários cadastrados" style="font-size: 8px; padding: 2px 6px; margin-left: auto; color: #10b981; white-space: nowrap;">👤 <b>${getUserCount()}</b> USUÁRIOS</button>
                </div>

                ${isOnline ? '<div class="pulse-ring"></div>' : ''}
            </div>
        `;
    }).join('');

    container.onclick = (e) => {
        const el = e.target.closest('[data-action]');
        if (!el) {
            // Clique no corpo do card (fora dos botões) abre os detalhes.
            const card = e.target.closest('.project-watch-card');
            if (card && card.dataset.projectId) openProjectDetail(card.dataset.projectId);
            return;
        }
        const id = el.dataset.id;
        const action = el.dataset.action;
        if (action === 'copy') copyToClipboard(id);
        else if (action === 'agent') installAgent(id);
        else if (action === 'detail') openProjectDetail(id);
        // TAREFA 5.3: manutencao e GLOBAL. `id` NAO e passado de proposito —
        // o no(config/maintenance) e o mesmo para todos os projetos, e
        // repassar o id sugeriria uma manutencao por projeto que nao existe.
        else if (action === 'maintenance') toggleMaintenanceFromCard();
    };
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => showToast("Copiado!", "success"));
}

function installAgent(projectId) {
    const baseUrl = BRASILHEXA_BACKEND_URL;
    const msg = document.createElement('div');
    msg.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999;background:#0a0a0f;border:1px solid rgba(0,243,255,0.2);border-radius:12px;padding:25px;max-width:520px;width:90%;box-shadow:0 0 40px rgba(0,0,0,0.8);';
    msg.innerHTML = `
        <h3 style="color:var(--cyan);font-size:14px;margin-bottom:12px;">ðŸ¤– CYBERCORE AGENT</h3>
        <div style="font-size:11px;color:#94a3b8;line-height:1.6;margin-bottom:12px;">
            O agente reporta CPU, RAM e disco do servidor a cada 30s.
            Baixe o script (requer login), envie ao servidor Linux e execute.
            <strong style="color:#f8fafc;">Nunca execute scripts remotamente via pipe (wget | python3 -).</strong>
        </div>
        <pre style="background:rgba(0,0,0,0.4);padding:15px;border-radius:8px;font-size:11px;color:#94a3b8;white-space:pre-wrap;line-height:1.6;max-height:300px;overflow-y:auto;">pip install psutil
# edite BASE_URL e PROJECT_ID no topo do agent.py
python3 agent.py</pre>
        <div style="display:flex;gap:10px;margin-top:15px;">
            <button id="agent-download-btn" class="btn-premium" style="flex:1;padding:8px;border-radius:8px;font-size:10px;">â¬‡ï¸ BAIXAR agent.py</button>
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

function removeProject(id) {
    if (!confirm("Remover este projeto do painel?")) return;

    // TAREFA 3.1: remoção via endpoint backend (respeta regras write:false do RTDB)
    const baseUrl = BRASILHEXA_BACKEND_URL;
    const doFetch = async () => {
        const idToken = auth.currentUser ? await auth.currentUser.getIdToken() : '';
        const resp = await fetch(`${baseUrl}/api/project/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
            body: JSON.stringify({ id })
        });
        return await resp.json();
    };

doFetch()
        .then(resp => {
            if (resp.status === 'success') {
                connectedProjects = connectedProjects.filter(p => p.id !== id);
                renderWatchProjects();
                showToast("Projeto removido.", "info");
            } else if (resp.status === 'not_found') {
                showToast("Projeto já removido.", "info");
            } else {
                showToast(resp.detail || "Erro ao remover projeto.", "error");
            }
        })
        .catch(() => showToast("Erro de conexão ao remover.", "error"));
}

// ── Validação em tempo real do input de conexão ──
(function initWatchValidation() {
    const input = document.getElementById('watch-project-url');
    if (input) {
        input.addEventListener('input', validateWatchInput);
        input.addEventListener('change', validateWatchInput);
    }
    if (typeof validateWatchInput === 'function') validateWatchInput();
})();

// ── Ticker de IA no card "Projetos monitorados" ─────────────
let _watchAiTickerTimer = null;
let _watchAiTickerRotateTimer = null;
let _watchAiTickerMsgs = [];
let _watchAiTickerIdx = 0;

function watchStartAiTicker() {
    if (_watchAiTickerTimer) return;
    _watchAiTickerRefresh();
    _watchAiTickerTimer = setInterval(_watchAiTickerRefresh, 90_000);
}

async function _watchAiTickerRefresh() {
    if (!auth || !auth.currentUser) return;
    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/hub/overview`, {
            headers: { 'Authorization': `Bearer ${idToken}` },
        });
        if (!resp.ok) return;
        const overview = await resp.json();
        const correlations = overview.correlations || [];
        _watchAiTickerMsgs = correlations.length
            ? correlations.map(c => `${c.title || 'Alerta'}: ${c.message || ''}`)
            : ['Nenhum alerta crítico. WAF e integridade do APK operando normalmente.'];
        _watchAiTickerIdx = 0;
        _watchAiTickerShow();
        if (!_watchAiTickerRotateTimer) {
            _watchAiTickerRotateTimer = setInterval(() => {
                if (_watchAiTickerMsgs.length < 2) return;
                _watchAiTickerIdx = (_watchAiTickerIdx + 1) % _watchAiTickerMsgs.length;
                _watchAiTickerShow();
            }, 8000);
        }
    } catch (e) { /* silencioso: ticker é informativo */ }
}

function _watchAiTickerShow() {
    const el = document.querySelector('#watch-ai-ticker .hub-ai-ticker-text');
    if (!el || !_watchAiTickerMsgs.length) return;
    el.textContent = 'Cyber Core IA: ' + _watchAiTickerMsgs[_watchAiTickerIdx];
    el.classList.remove('ticker-in');
    void el.offsetWidth;
    el.classList.add('ticker-in');
}
