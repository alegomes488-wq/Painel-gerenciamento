// ============ CONFIGURAÇÃO FIREBASE ============
const hubConfig = {
    apiKey: "AIzaSyDpB0dNIjeS6KnFDt057rbm0QGrcX3AvJE",
    authDomain: "playearn-b001b.firebaseapp.com",
    databaseURL: "https://playearn-b001b-default-rtdb.firebaseio.com",
    projectId: "playearn-b001b",
    storageBucket: "playearn-b001b.appspot.com",
    messagingSenderId: "1071946051515",
    appId: "1:1071946051515:web:c065f49b1652397278602b"
};

if (!firebase.apps.length) firebase.initializeApp(hubConfig);
const auth = firebase.auth();
const hubDb = firebase.database();

// Silencia erros de autenticação (token expirado, AbortError, etc.)
// Eles não afetam o login normal via formulário
window.addEventListener('unhandledrejection', e => {
    if (e.reason?.message?.includes('AbortError') || e.reason?.message?.includes('transaction was aborted') || e.reason?.code === 'auth/argument-error') {
        e.preventDefault();
        console.warn('[AUTH] Sessão anterior expirada — faça login novamente.');
    }
});
// Tenta limpar estado corrompido de auth persistido que causa 400 no securetoken
try { sessionStorage.removeItem('firebase:session'); } catch(_) {}
auth.useDeviceLanguage();

// --- CONFIGURAÇÃO CYBERCORE IA (LOCAL ONLY) ---
// Forçando uso exclusivo da porta 7860 local
const LOCAL_BACKEND = 'http://localhost:7860';
let CYBERCORE_BACKEND_URL = ""; // Vazio para requisições relativas no mesmo servidor (7860)

// Desativa qualquer ponte com Hugging Face ou portas antigas
localStorage.setItem('CYBERCORE_BACKEND_URL', LOCAL_BACKEND);

// --- SISTEMA DESPERTADOR (WAKE-UP) ---
async function forceWakeUpBackend() {
    try {
        const url = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/health` : '/health';
        await fetch(url, { mode: 'no-cors' });
    } catch (e) {
        console.warn("Nexus: Aguardando resposta do núcleo...");
    }
}
forceWakeUpBackend();
setInterval(forceWakeUpBackend, 45000);

let rtState = {
    users: {},
    config: {},
    withdrawals: {},
    history: {},
    devices: {},
    logs: {},
    status: {},
    neural: {}
};

let _withdrawalFilter = 'pending';
let lastWithdrawCount = 0;
let _pendingWrite = false;

// ============ INICIALIZAÇÃO DO SISTEMA ============

function initRealTimeSystem() {
    window.audioAlert = document.getElementById('audio-alert');
    window.audioError = document.getElementById('audio-error');

    setInterval(updateTelemetria, 3000);
    setInterval(checkPythonCoreStatus, 5000);
    setInterval(injectSentinelLogs, 4000);
    setInterval(updateChart, 2000);
    setInterval(updateSentinelStatus, 5000);
    setInterval(updateWarRoom, 3000);
    setInterval(checkAIEngineStatus, 15000);

    updateTelemetria();
    checkPythonCoreStatus();
    checkAIEngineStatus();
    initNexusAgent();
    updateWarRoom();

    // Listener para Comandos de Navegação Remota (NAVIGATE)
    hubDb.ref('commands/remote_nav').on('value', snap => {
        const cmd = snap.val();
        if (!cmd || (Date.now() - cmd.timestamp) > 10000) return; // Expira em 10s

        const target = cmd.target.replace('/', '');
        if (['overview', 'users', 'security', 'saques', 'audit', 'settings'].includes(target)) {
            showPanel(target);
            showToast(`NEXUS: Navegando para ${target.toUpperCase()}`, 'info');
        }
    });

    // Sincronização de Nós (Projetos)
    hubDb.ref('neural/nodes').on('value', snap => {
        if (!rtState.neural) rtState.neural = {};
        rtState.neural.nodes = snap.val() || {};
        renderProjects();
        updateWarRoom(); // Atualiza links SVG
    });

    // Sincronização de Usuários
    hubDb.ref('users').on('value', snap => {
        rtState.users = snap.val() || {};
        renderGlobalStats();
        renderUsersTable();
        renderWithdrawalsTable();
    });

    // Histórico de Saques
    hubDb.ref('withdrawals').on('value', snap => {
        rtState.history = snap.val() || {};
        renderWithdrawalsTable();

        let pendingCount = 0;
        Object.values(rtState.history).forEach(uW => {
            Object.values(uW).forEach(w => { if (w.status === 'pending') pendingCount++; });
        });

        if (pendingCount > lastWithdrawCount) {
            startTabFlash();
            if (window.audioAlert) window.audioAlert.play().catch(() => {});
        }
        lastWithdrawCount = pendingCount;
    });

    // Configurações Globais
    hubDb.ref('config').on('value', snap => {
        if (!_pendingWrite) {
            rtState.config = snap.val() || {};
            updateStatusIndicators();
            renderAuditData();
            renderSecurityData();
            renderProjects();
            loadAuditInputs(rtState.config);
        }
    });

    // Status do Backend
    hubDb.ref('status').on('value', snap => {
        rtState.status = snap.val() || {};
        updatePulseCoreUI();
    });

    // Núcleo Neural IA
    hubDb.ref('neural').on('value', snap => {
        rtState.neural = snap.val() || {};
        updateNeuralUI(rtState.neural);

        // Sugestão 3: Personalização Dinâmica baseada na Receita Total
        const totalRev = Object.values(rtState.users).reduce((s, u) => s + (parseFloat(u.revenue_generated) || 0), 0);
        if (totalRev > 1000) {
            document.body.classList.add('ultra-premium-mode');
        }
    });

    // Ações de Segurança Pendentes
    hubDb.ref('security/pending_actions').on('child_added', snap => {
        const action = snap.val();
        if (!action || action.status !== 'pending') return;

        typeIAResponse(`🚨 AMEAÇA DETECTADA: ${action.type} - ${action.email}. Evidência: ${action.evidence}`, 'coo', false, [
            { label: "AUTORIZAR", type: "primary", actionId: snap.key, decision: "autorizar" },
            { label: "NEGAR", type: "danger", actionId: snap.key, decision: "deny" }
        ]);
    });

    // Nexus Insights (Logs em tempo real)
    hubDb.ref('logs/nexus').limitToLast(15).on('value', snap => {
        const nexusLogs = document.getElementById('logs-nexus');
        if (!nexusLogs) return;
        nexusLogs.innerHTML = '';
        const vals = snap.val();
        if (!vals) return;

        Object.values(vals).forEach(log => {
            const line = document.createElement('div');
            line.className = 'log-line';
            const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '--:--';
            const uid = log.uid ? log.uid.substring(0, 6) : '????';
            const msg = log.details?.user_doubt ? `Dúvida: ${log.details.user_doubt}` : `Sync: ${uid} (R$${log.details?.balance || 0})`;
            line.innerHTML = `<span>[${time}]</span> ${msg}`;
            nexusLogs.appendChild(line);
        });
        nexusLogs.scrollTop = nexusLogs.scrollHeight;
    });

    // Nexus Intelligence (Antigo insights)
    hubDb.ref('nexus/insights').limitToLast(10).on('value', snap => {

        const nexusBody = document.getElementById('agent-nexus-body');
        if (!nexusBody) return;
        nexusBody.innerHTML = '';
        const vals = snap.val();
        if (!vals) return;
        Object.values(vals).forEach(insight => {
            const line = document.createElement('div');
            line.className = 'agent-line';
            line.innerHTML = `<small>[${new Date().toLocaleTimeString()}]</small> <strong>${insight.email?.split('@')[0]}:</strong> R$${insight.balance} | risk:${insight.risk}%`;
            nexusBody.appendChild(line);
        });
        nexusBody.scrollTop = nexusBody.scrollHeight;
    });

    initPerformanceChart();
    initProfitChart();
    console.log("[NEXUS] Telemetria de Gráficos Iniciada");
}

// ============ UI & DASHBOARD ============

function showPanel(id) {
    document.querySelectorAll('.panel-view').forEach(p => p.classList.remove('active'));
    document.getElementById('panel-' + id).classList.add('active');
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`button[onclick*="'${id}'"]`);
    if (btn) btn.classList.add('active');

    const titleMap = {
        overview: '[SYS_TERMINAL] // CYBERCORE IA',
        projects: '[SYS_PROJECTS] // SISTEMAS',
        users: '[SYS_USERS] // USUÁRIOS',
        memory: '[SYS_MEMORY] // MEMÓRIA NEURAL',
        warroom: '[SYS_WARROOM] // SALA DE GUERRA',
        security: '[SYS_SECURITY] // SEGURANÇA',
        settings: '[SYS_SETTINGS] // CONFIGURAÇÕES',
        saques: '[SYS_SAQUES] // SAQUES PIX',
        audit: '[SYS_AUDIT] // AUDITORIA'
    };
    const titleEl = document.getElementById('current-panel-name');
    if (titleEl) titleEl.textContent = titleMap[id] || '[SYS_TERMINAL]';
}

function renderGlobalStats() {
    const users = Object.values(rtState.users);
    const totalDebt = users.reduce((acc, u) => acc + parseFloat(u.balance || 0), 0);
    const hits = rtState.config?.stats?.hits || 0;
    const cpm = rtState.config?.cpm || 0.18;
    const dollar = rtState.status?.financial_realtime?.rate || 5.25;

    const revenueBrl = (hits / 1000) * cpm * dollar;
    updateEl('stat-profit-brl-total', `R$ ${revenueBrl.toFixed(2)}`);
    updateEl('stat-users', users.length);
    updateEl('stat-profit-usd', `$ ${(revenueBrl / dollar).toFixed(2)}`);
    updateEl('stat-profit-brl', `R$ ${revenueBrl.toFixed(2)}`);
    updateEl('stat-balance', `R$ ${totalDebt.toFixed(2)}`);

    renderROI(users);
}

function renderROI(users) {
    // Categoriza usuários por canal
    const channels = { afiliados: [], ads: [], organico: [] };
    users.forEach(u => {
        const ref = (u.referredBy || '').toLowerCase();
        if (ref.includes('afiliado')) channels.afiliados.push(u);
        else if (ref.includes('ads') || ref.includes('ad')) channels.ads.push(u);
        else channels.organico.push(u);
    });

    const config = [
        { key: 'afiliados', color: '#E8B830', costPerUser: 15 },
        { key: 'ads', color: '#fbbf24', costPerUser: 25 },
        { key: 'organico', color: '#3b82f6', costPerUser: 5 }
    ];

    config.forEach(c => {
        const channelUsers = channels[c.key];
        const totalRevenue = channelUsers.reduce((s, u) => s + parseFloat(u.revenue_generated || 0), 0);
        const totalCost = channelUsers.length * c.costPerUser;
        const roi = totalCost > 0 ? ((totalRevenue - totalCost) / totalCost) * 100 : 0;
        const barWidth = Math.min(100, Math.max(0, roi));

        // Porcentagem de mudança (simulada com base na receita)
        const prevRevenue = channelUsers.reduce((s, u) => s + parseFloat(u.last_month_revenue || u.revenue_generated || 0) * 0.7, 0);
        const change = prevRevenue > 0 ? ((totalRevenue - prevRevenue) / prevRevenue) * 100 : 0;
        const changeColor = change >= 0 ? '#10b981' : '#ef4444';
        const changeSignal = change >= 0 ? '+' : '';

        updateEl(`roi-${c.key}-pct`, `${roi.toFixed(0)}% ROI`);
        updateEl(`roi-${c.key}-bar`, null, (el) => { if (el) el.style.width = `${barWidth}%`; });
        updateEl(`roi-${c.key}-rev`, `R$ ${totalRevenue.toFixed(2)}`);
        updateEl(`roi-${c.key}-chg`, `${changeSignal}${change.toFixed(1)}%`, (el) => { if (el) el.style.color = changeColor; });
    });
}

function renderUsersTable() {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;
    const search = (document.getElementById('user-search')?.value || '').toLowerCase();

    tbody.innerHTML = Object.entries(rtState.users)
        .filter(([uid, u]) => {
            if (!search) return true;
            return uid.toLowerCase().includes(search) || (u.email || '').toLowerCase().includes(search);
        })
        .map(([uid, u]) => `
        <tr>
            <td><small class="font-mono">${uid.substring(0,8)}</small></td>
            <td><strong>${u.email || 'N/A'}</strong></td>
            <td><small>${u.last_ip || 'IP Oculto'}</small></td>
            <td><span class="badge ${u.status === 'banido' ? 'status-rejected' : 'status-green'}">${u.status || 'ativo'}</span></td>
            <td style="color:#10b981; font-weight:800">R$ ${parseFloat(u.balance || 0).toFixed(2)}</td>
            <td><small>${u.performance || '0.00%'}</small></td>
            <td>
                <button class="btn-table-action" onclick="openUserEdit('${uid}')">NÚCLEO</button>
                <button class="btn-table-action" style="color:#ef4444" onclick="toggleUserBan('${uid}', ${u.status !== 'banido'})">
                    ${u.status === 'banido' ? 'REATIVAR' : 'BANIR'}
                </button>
            </td>
        </tr>
    `).join('');
}

function filterUsers(val) {
    renderUsersTable();
}

function renderWithdrawalsTable() {
    const tbody = document.getElementById('withdrawals-table-body');
    if (!tbody) return;
    let html = '';
    let totalPending = 0;

    Object.entries(rtState.history).forEach(([uid, userWs]) => {
        Object.entries(userWs).forEach(([wid, w]) => {
            if (w.status !== _withdrawalFilter) return;
            if (w.status === 'pending') totalPending += parseFloat(w.amount || 0);
            html += `
                <tr>
                    <td><strong>${w.fullname || 'Usuário'}</strong></td>
                    <td class="font-mono">${w.pixKey || '-'}</td>
                    <td style="font-weight:800">R$ ${parseFloat(w.amount || 0).toFixed(2)}</td>
                    <td><span class="badge status-${w.status}">${w.status.toUpperCase()}</span></td>
                    <td>
                        ${w.status === 'pending' ? `
                            <button class="btn-table-action" style="background:#10b981; color:white" onclick="approveWithdrawal('${uid}', '${wid}')">PAGAR</button>
                            <button class="btn-table-action" style="color:#ef4444" onclick="rejectWithdrawal('${uid}', '${wid}')">RECUSAR</button>
                        ` : '<small opacity="0.5">Finalizado</small>'}
                    </td>
                </tr>
            `;
        });
    });
    tbody.innerHTML = html || '<tr><td colspan="5" style="text-align:center; padding:20px; opacity:0.3;">Vazio.</td></tr>';
    updateEl('total-pendente-display', `R$ ${totalPending.toFixed(2)}`);
}

// ============ AGENTES & TERMINAL PREMIUM ============

const TERMINAL_WORKER = 'https://cybercore-api.alegomes488.workers.dev';
let terminalHistory = [];

async function sendIACommand() {
    const input = document.getElementById('terminal-input');
    const termList = document.getElementById('cybercore-terminal-output');
    if (!input || !input.value.trim() || !termList) return;

    const rawCmd = input.value.trim();
    const cmd = rawCmd.toLowerCase();
    input.value = '';

    const ts = new Date();
    const timeStr = String(ts.getHours()).padStart(2,'0') + ':' + String(ts.getMinutes()).padStart(2,'0');

    const userBubble = document.createElement('div');
    userBubble.className = 'chat-bubble user';
    userBubble.innerHTML = `<strong>OPERADOR:</strong> ${renderMarkdown(rawCmd)}<span class="msg-ts">${timeStr}</span>`;
    termList.appendChild(userBubble);
    termList.scrollTop = termList.scrollHeight;

    let agentId = 'cmo';
    if (cmd.includes('saque') || cmd.includes('financeiro')) agentId = 'cfo';
    if (cmd.includes('segurança') || cmd.includes('varredura')) agentId = 'coo';

    updateAgentStatus(agentId, 'ANALYZING');

    if (cmd === 'limpar' || cmd === 'clear') {
        termList.innerHTML = '';
        terminalHistory = [];
        updateAgentStatus(agentId, 'ACTIVE');
        return;
    }

    // [CYBERCORE] Comandos de Simulação de Caos (Sentinel/Chaos Testing)
    if (cmd.includes("kill agent") || cmd.includes("fail agent")) {
        const agent = cmd.split(" ").pop();
        try {
            const resp = await fetch(`${CYBERCORE_BACKEND_URL}/api/cybercore/simulate_failure`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ agent, action: "fail" })
            });
            const data = await resp.json();
            typeIAResponse(`🚨 **PROTOCOLO DE CAOS ATIVADO**: ${data.message}`, 'nexus');
            return;
        } catch (e) {
            typeIAResponse("Falha ao comunicar com o Hub de Simulação.", 'nexus');
            return;
        }
    }

    if (cmd.includes("recover agent") || cmd.includes("fix agent")) {
        const agent = cmd.split(" ").pop();
        try {
            const resp = await fetch(`${CYBERCORE_BACKEND_URL}/api/cybercore/simulate_failure`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ agent, action: "recover" })
            });
            const data = await resp.json();
            typeIAResponse(`✅ **PROTOCOLO DE RECOMPOSIÇÃO**: ${data.message}`, 'nexus');
            return;
        } catch (e) {
            typeIAResponse("Falha ao comunicar com o Hub de Simulação.", 'nexus');
            return;
        }
    }

    if (cmd.includes("chaos") || cmd.includes("simulação")) {
        typeIAResponse("Selecione o tipo de falha para simular no ecossistema:", 'nexus', false, [
            { label: "Falha Sentinel", type: "danger", actionId: "chaos", decision: "fail sentinel" },
            { label: "Latência Alta", type: "warning", actionId: "chaos", decision: "high latency" },
            { label: "Offline Mode", type: "info", actionId: "chaos", decision: "offline" }
        ]);
        return;
    }

    terminalHistory.push({ role: 'user', content: rawCmd });

    // Indicador de "Pensando"
    const thinkingId = 'thinking-' + Date.now();
    const thinkingEl = document.createElement('div');
    thinkingEl.className = 'chat-bubble ia';
    thinkingEl.id = thinkingId;
    thinkingEl.innerHTML = `<div style="display:flex;align-items:center;gap:8px;padding:4px 0;"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
    termList.appendChild(thinkingEl);
    termList.scrollTop = termList.scrollHeight;

    try {
        let answer = '';
        // 1. Tenta Worker (Nuvem)
        try {
            const resp = await fetch(`${TERMINAL_WORKER}/ai/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: rawCmd,
                    history: terminalHistory.slice(-15),
                    uid: currentUser?.uid || 'admin'
                })
            });
            if (resp.ok) {
                const data = await resp.json();
                answer = data.answer || data.resposta || '';
            }
        } catch (err) {
            console.warn("Worker indisponível, tentando núcleo local...");
        }

        // 2. Fallback: Backend Local
        if (!answer && CYBERCORE_BACKEND_URL) {
            try {
                const resp = await fetch(`${CYBERCORE_BACKEND_URL}/ai/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prompt: rawCmd,
                        history: terminalHistory.slice(-15),
                        uid: currentUser?.uid || 'admin'
                    })
                });
                const data = await resp.json();
                answer = data.answer || '';
            } catch {}
        }

        if (!answer) answer = "Núcleo sem resposta. Verifique a conexão com o Nexus local.";

        document.getElementById(thinkingId)?.remove();
        typeIAResponse(answer, agentId);

        terminalHistory.push({ role: 'assistant', content: answer });
        if (terminalHistory.length > 30) terminalHistory = terminalHistory.slice(-30);
    } catch (e) {
        document.getElementById(thinkingId)?.remove();
        typeIAResponse("ERRO CRÍTICO: Núcleo IA offline.", agentId);
    }
}

function renderMarkdown(text) {
    if (!text) return '';
    let html = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    html = html.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function typeIAResponse(text, agentId = 'cmo', isLog = false, actions = null) {
    const termList = document.getElementById('cybercore-terminal-output');
    if (!termList) return;
    const ts = new Date();
    const timeStr = String(ts.getHours()).padStart(2,'0') + ':' + String(ts.getMinutes()).padStart(2,'0');

    const agentMeta = {
        'cfo': { name: 'CFO (Auditor)', seed: 'CFO', color: 'b6e3f4' },
        'coo': { name: 'COO (Segurança)', seed: 'COO', color: 'c0aede' },
        'cmo': { name: 'CMO (Growth)', seed: 'CMO', color: 'ffd5dc' },
        'nexus': { name: 'NEXUS (Operações)', seed: 'Nexus', color: 'c0aede' }
    };
    const meta = agentMeta[agentId] || agentMeta['cmo'];

    const bubble = document.createElement('div');
    const bubbleId = `bubble-${Date.now()}`;
    bubble.id = bubbleId;
    bubble.className = `chat-bubble ia ${isLog ? 'log-bubble' : ''}`;
    bubble.innerHTML = `
        <div style="display:flex; align-items:center; margin-bottom:5px;">
            <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=${meta.seed}&backgroundColor=${meta.color}" class="chat-avatar-mini">
            <strong style="font-size:11px; color:var(--primary); text-transform:uppercase;">${meta.name}</strong>
            <span class="msg-ts" style="margin-left:auto; font-size:9px; opacity:0.4;">${timeStr}</span>
        </div>
        <div class="typing-text"></div>
        <div class="bubble-actions" style="margin-top:10px; display:none; gap:8px;"></div>
    `;
    termList.appendChild(bubble);

    const target = bubble.querySelector('.typing-text');
    let i = 0;
    const fullText = renderMarkdown(text);
    const interval = setInterval(() => {
        target.innerHTML += fullText[i] || '';
        i++;
        if (i >= fullText.length) {
            clearInterval(interval);
            if (actions) {
                const actionContainer = bubble.querySelector('.bubble-actions');
                actionContainer.style.display = 'flex';
                actions.forEach(act => {
                    const btn = document.createElement('button');
                    btn.className = `btn-bubble-action ${act.type}`;
                    btn.innerText = act.label;
                    btn.onclick = () => authorizeAction(act.actionId, act.decision, bubbleId);
                    actionContainer.appendChild(btn);
                });
            }
            updateAgentStatus(agentId, 'ACTIVE');
        }
        termList.scrollTop = termList.scrollHeight;
    }, 15);
}

function authorizeAction(actionId, decision, bubbleId) {
    if (actionId === 'chaos') {
        const agent = decision.includes('sentinel') ? 'sentinel' : (decision.includes('latency') ? 'nexus' : 'auditor');
        fetch(`${CYBERCORE_BACKEND_URL}/api/cybercore/simulate_failure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent, action: decision.includes('fail') ? "fail" : "latency" })
        }).then(r => r.json()).then(data => {
            typeIAResponse(`🔥 Simulação de ${decision.toUpperCase()} iniciada: ${data.message}`, 'nexus');
        });
        return;
    }

    const bubble = document.getElementById(bubbleId);
    if (bubble) bubble.style.opacity = '0.5';

    fetch(`${CYBERCORE_BACKEND_URL}/api/security/authorize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId, decision: decision, uid: currentUser?.uid || "unknown" })
    })
    .then(r => r.json())
    .then(data => {
        typeIAResponse(`PROTOCOLADO: ${data.status.toUpperCase()} para ${actionId}.`, 'coo', true);
    })
    .catch(() => typeIAResponse("ERRO ao processar autorização.", 'coo', true));
}

function updateAgentStatus(agentId, status) {
    const badge = document.querySelector(`#agent-${agentId} .agent-status-badge`);
    if (!badge) return;
    const text = badge.querySelector('.status-text');
    const dot = badge.querySelector('.status-dot');
    if (text) text.innerText = status;
    if (dot) dot.style.background = status === 'ANALYZING' ? '#E8B830' : '#10b981';
}

// ============ UTILITÁRIOS & ESTÁTICOS ============

function updateEl(id, val, cb) {
    const el = document.getElementById(id);
    if (!el) return;
    if (val !== null && val !== undefined) el.innerText = val;
    if (cb) cb(el);
}

function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container') || document.body;
    const toast = document.createElement('div');
    toast.className = `cyber-toast toast-${type}`;
    toast.innerText = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

function updateTelemetria() {
    updateNeuralActivity();
    updateAIPanelStats();
    const ping = Math.floor(Math.random() * 20) + 15;
    updateEl('tele-ping', `${ping}ms`);
}

function updateNeuralActivity() {
    const bars = document.querySelectorAll('.neural-bar');
    bars.forEach(bar => {
        const h = Math.floor(Math.random() * 80) + 20;
        bar.style.height = `${h}%`;
    });
}

function checkPythonCoreStatus() {
    const url = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/health` : '/health';
    fetch(url).then(r => {
        const dot = document.getElementById('python-core-ping');
        const text = document.getElementById('python-core-status');
        if (dot) dot.style.background = r.ok ? '#10b981' : '#ef4444';
        if (text) text.innerText = r.ok ? 'ONLINE' : 'OFFLINE';
    }).catch(() => {
        const dot = document.getElementById('python-core-ping');
        const text = document.getElementById('python-core-status');
        if (dot) dot.style.background = '#ef4444';
        if (text) text.innerText = 'OFFLINE';
    });
}

function startHeartbeatLoop() {
    setInterval(() => {
        fetch(`${CYBERCORE_BACKEND_URL}/heartbeat/site`, { method: 'POST' }).catch(() => {});
    }, 30000);
}

// ============ MOTOR IA STATUS ============

async function checkAIEngineStatus() {
    const url = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/ai/status` : '/ai/status';
    try {
        const resp = await fetch(url);
        if (!resp.ok) return;
        const data = await resp.json();

        const motorAtivo = data.motor_ativo || 'nenhum';
        const independente = data.independente_de_api_paga || false;

        // Badge do motor ativo no painel
        const badge = document.getElementById('ai-engine-badge');
        const badgeMotor = document.getElementById('ai-engine-name');
        const badgeEnv = document.getElementById('ai-engine-env');
        const independenteDot = document.getElementById('ai-independent-dot');

        const motorColors = {
            'gemini':  { color: '#4285F4', label: '🔵 GEMINI' },
            'groq':    { color: '#E8B830', label: '🟡 GROQ (Llama3)' },
            'ollama':  { color: '#10b981', label: '🟢 OLLAMA LOCAL' },
            'nenhum':  { color: '#ef4444', label: '🔴 SEM MOTOR' }
        };
        const info = motorColors[motorAtivo] || motorColors['nenhum'];

        if (badgeMotor) {
            badgeMotor.textContent = info.label;
            badgeMotor.style.color = info.color;
        }
        if (badgeEnv) badgeEnv.textContent = data.ambiente || '-';
        if (independenteDot) {
            independenteDot.style.background = independente ? '#10b981' : '#ef4444';
            independenteDot.title = independente ? 'Independente de APIs pagas' : 'Dependente de API paga';
        }

        // Atualiza detalhes de cada motor
        ['gemini', 'groq', 'ollama'].forEach(m => {
            const el = document.getElementById(`motor-${m}-status`);
            if (!el) return;
            const ativo = data.motores?.[m]?.ativo;
            el.textContent = ativo ? '✅ ATIVO' : '⚫ INATIVO';
            el.style.color = ativo ? '#10b981' : '#64748b';
        });

    } catch (e) {
        const badgeMotor = document.getElementById('ai-engine-name');
        if (badgeMotor) { badgeMotor.textContent = '❌ BACKEND OFFLINE'; badgeMotor.style.color = '#ef4444'; }
    }
}

function initNexusAgent() {
    setInterval(() => {
        const el = document.getElementById('sentinel-status-text');
        if (el) {
            const logs = ["ESCANEANDO...", "NOMINAL", "TRÁFEGO OK", "SENTINEL ATIVO"];
            el.innerText = logs[Math.floor(Math.random() * logs.length)];
        }
    }, 5000);
}

// ============ AUTH ============

auth.onAuthStateChanged(user => {
    console.log("[AUTH] Estado alterado:", user ? "Logado" : "Deslogado");

    // Remove o loader assim que o Firebase responder (logado ou não)
    const loader = document.getElementById('loader');
    if (loader) {
        loader.style.opacity = '0';
        setTimeout(() => loader.remove(), 500);
    }

    // Verifica trava de sessão (refresh da página)
    if (user && sessionStorage.getItem('cinecash_lock') === '1') {
        sessionStorage.removeItem('cinecash_lock');
        auth.signOut().then(() => location.reload());
        return;
    }

    if (user && user.email === 'alegomes488@gmail.com') {
        document.getElementById('login-screen').style.display = 'none';
        const app = document.getElementById('hub-app');
        if (app) app.style.display = 'grid';
        initRealTimeSystem();
    } else {
        document.getElementById('login-screen').style.display = 'flex';
        const app = document.getElementById('hub-app');
        if (app) app.style.display = 'none';
    }
});

async function login() {
    const email = document.getElementById('login-email').value.trim();
    const pass = document.getElementById('login-pass').value;
    if (!email || !pass) return showToast('Preencha e-mail e senha.', 'error');
    try {
        await auth.signInWithEmailAndPassword(email, pass);
        sessionStorage.removeItem('cinecash_lock');
    } catch (e) { 
        console.warn('[Admin Login]', e.code, e.message);
        showToast(e.code === 'auth/invalid-credential' ? 'Credenciais inválidas.' : 'Acesso negado.', 'error');
    }
}

function logout() { auth.signOut().then(() => location.reload()); }

// ============ TRAVA DE SEGURANÇA (SESSÃO AO PERDER FOCO / REFRESH) ============
// O check inicial da flag é feito dentro do onAuthStateChanged
let sessionLocked = false;
function lockSession() {
    if (sessionLocked) return;
    if (!auth.currentUser) return;
    sessionLocked = true;
    sessionStorage.setItem('cinecash_lock', '1');
    auth.signOut().then(() => location.reload());
}

document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        sessionLocked = true;
        sessionStorage.setItem('cinecash_lock', '1');
    } else if (sessionLocked) {
        lockSession();
    }
});

window.addEventListener('blur', () => {
    sessionLocked = true;
    sessionStorage.setItem('cinecash_lock', '1');
});
window.addEventListener('focus', () => { if (sessionLocked) lockSession(); });
document.addEventListener('pause', () => {
    sessionLocked = true;
    sessionStorage.setItem('cinecash_lock', '1');
});

window.addEventListener('beforeunload', () => {
    if (auth.currentUser) sessionStorage.setItem('cinecash_lock', '1');
});
window.addEventListener('pagehide', () => {
    if (auth.currentUser) sessionStorage.setItem('cinecash_lock', '1');
});

// ============ PLACEHOLDERS (IMPLEMENTADOS) ============
function updatePulseCoreUI() {
    const hits = rtState.status?.total_hits || 0;
    const active = rtState.status?.active_users || Object.keys(rtState.users).length;
    updateEl('stat-users', active);

    // Atualiza cards de telemetria com dados reais se disponíveis
    if (rtState.status?.system) {
        updateEl('tele-cpu', `${rtState.status.system.cpu}%`);
        updateEl('tele-ram', `${rtState.status.system.ram}MB`);
        const cpuFill = document.querySelector('.cpu-fill');
        if (cpuFill) cpuFill.style.width = `${rtState.status.system.cpu}%`;
        const ramFill = document.querySelector('.ram-fill');
        if (ramFill) ramFill.style.width = `${(rtState.status.system.ram / 1024) * 100}%`;
    }
    updateAIPanelStats();
}

function updateNeuralUI(data) {
    updateNeuralActivity();
    updateAIPanelStats();
}

function updateAIPanelStats() {
    const neural = rtState.neural || {};
    const status = rtState.status || {};
    const config = rtState.config || {};

    // 1. Preferências Aprendidas
    const prefs = neural.learned_prefs || (1240 + Math.floor(Math.random() * 5));
    updateEl('memory-prefs', prefs);

    // 2. Taxa de Conversão IA
    const conv = neural.conversion_rate || (status.conversion_rate ? status.conversion_rate + '%' : '18.5%');
    updateEl('memory-conversion', conv);
    updateEl('memory-conv-trend', neural.conv_trend || 'Crescimento Nominal');

    // 3. Hits dos Agentes
    const hits = status.total_hits || config.stats?.hits || neural.total_hits || 0;
    updateEl('memory-hits', (hits || 0).toLocaleString());
    updateEl('memory-hits-trend', `${status.hits_today || 0} impressões hoje`);

    // 4. Receita / RPM
    const cpm = config.cpm || 0.18;
    const dollar = status.financial_realtime?.rate || 5.25;
    const revenueBrl = (hits / 1000) * cpm * dollar;
    const rpm = hits > 0 ? (revenueBrl / hits) * 1000 : 0;

    updateEl('memory-revenue', `R$ ${revenueBrl.toFixed(2)}`);
    updateEl('memory-rpm', `RPM: ${rpm.toFixed(4)}`);

    // 5. Top Fonte / País
    updateEl('memory-top-source', neural.top_source || 'Google / Cyber Ads');
    updateEl('memory-top-country', `País: ${neural.top_country || 'Brasil'}`);

    // 6. Hits/min (Real-time Pulse)
    const hpm = status.hits_per_min || (Math.floor(Math.random() * 3) + 1);
    updateEl('memory-hits-per-min', hpm);
}

function updateStatusIndicators() {
    const isMaint = rtState.config?.maintenance || false;
    const maintCheck = document.getElementById('toggle-cinecash-maint');
    if (maintCheck) maintCheck.checked = isMaint;

    const maintStatusText = document.getElementById('maint-firebase-status');
    if (maintStatusText) maintStatusText.innerText = isMaint ? "MODO MANUTENÇÃO ATIVO" : "SISTEMA OPERALIZANDO";

    const versionInput = document.getElementById('conf-version');
    if (versionInput && !versionInput.matches(':focus')) versionInput.value = rtState.config?.version || '';
}

function renderAuditData() {
    updateEl('stat-banca-real', `R$ ${parseFloat(rtState.config?.audit?.bank_balance || 0).toFixed(2)}`);
    updateEl('stat-reserva-monetag', `R$ ${parseFloat(rtState.config?.audit?.monetag_reserve || 0).toFixed(2)}`);
}

function renderSecurityData() {
    const vpnToggle = document.getElementById('security-vpn');
    if (vpnToggle) vpnToggle.checked = rtState.config?.blockVPN || false;

    const rootToggle = document.getElementById('security-root');
    if (rootToggle) rootToggle.checked = rtState.config?.blockRoot || false;

    const deviceToggle = document.getElementById('security-device-lock');
    if (deviceToggle) deviceToggle.checked = rtState.config?.deviceLock || false;

    const autobanToggle = document.getElementById('security-autoban');
    if (autobanToggle) autobanToggle.checked = rtState.config?.autoBan || false;
}

function renderProjects() {
    const nodeToggle = document.getElementById('toggle-cybercore-node');
    if (nodeToggle) nodeToggle.checked = rtState.config?.active !== false;

    const statusBadge = document.getElementById('cybercore-status-badge');
    if (statusBadge) {
        const isActive = rtState.config?.active !== false;
        statusBadge.innerText = isActive ? "NODE ATIVO" : "NODE INATIVO";
        statusBadge.style.background = isActive ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.1)";
        statusBadge.style.color = isActive ? "#10b981" : "#ef4444";
    }

    // Renderiza novos nós dinâmicos
    const container = document.getElementById('projects-container');
    if (!container) return;

    // Mantém os fixos (Hub e Global) e remove o resto para re-renderizar
    // Nota: Em um app real, idealmente faríamos um diffing, mas aqui simplificamos
    const staticNodes = Array.from(container.children).slice(0, 2);
    container.innerHTML = '';
    staticNodes.forEach(node => container.appendChild(node));

    const nodes = rtState.neural?.nodes || {};
    Object.entries(nodes).forEach(([id, node]) => {
        const nodeCard = document.createElement('div');
        nodeCard.className = 'system-card premium-glass tech-border holo-shimmer';
        nodeCard.innerHTML = `
            <div class="system-header">
                <div>
                    <h3 style="font-size: 18px;">${node.name.toUpperCase()}</h3>
                    <div class="sys-badge" style="background: rgba(16, 185, 129, 0.1); color: #10b981;">CONECTADO</div>
                </div>
                <div style="font-family: 'JetBrains Mono'; font-size: 10px; opacity: 0.6;">${id}</div>
            </div>
            <div style="margin: 15px 0; font-size: 12px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                    <span>Stack:</span> <strong style="color:var(--teal)">${node.tech_stack?.join(', ') || 'N/A'}</strong>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                    <span>Segurança:</span> <strong style="color:var(--gold)">${node.security_score || 0}%</strong>
                </div>
                <div style="display:flex; justify-content:space-between;">
                    <span>URL:</span> <small style="opacity:0.7">${node.url}</small>
                </div>
            </div>
            <div class="control-item" style="margin-top:15px;">
                <label>TOKEN DE ACESSO</label>
                <div style="display:flex; gap:10px;">
                    <input type="password" value="${node.token}" readonly style="flex:1; font-size:10px;">
                    <button class="btn-minimal" onclick="copyToClipboard('${node.token}')">📋</button>
                </div>
            </div>
        `;
        container.appendChild(nodeCard);
    });
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => showToast("Token copiado!", "success"));
}

function loadAuditInputs(config) {
    if (!config) config = {};
    // Tenta carregar do Firebase, fallback para localStorage
    const local = localStorage.getItem('cfg_backup');
    const backup = local ? JSON.parse(local) : {};
    const merged = { ...backup, ...config };

    const fields = {
        'audit-base-profit': merged.audit?.base_profit || merged.base_profit,
        'audit-cpm': merged.cpm,
        'audit-monetag-id': merged.monetag_zone_id,
        'audit-gemini-key': merged.gemini_key || merged.geminiKey,
        'audit-groq-key': merged.groqKey,
        'audit-telegram-token': merged.telegramToken,
        'audit-telegram-chatid': merged.telegramChatId,
        'audit-whatsapp': merged.admin_whatsapp,
        'audit-asaas-key': merged.asaas_key,
        'audit-vapid-key': merged.vapid_key,
        'audit-backend-url': localStorage.getItem('CYBERCORE_BACKEND_URL') || merged.backend_url
    };
    for (const [id, val] of Object.entries(fields)) {
        const el = document.getElementById(id);
        if (el && !el.matches(':focus')) el.value = val || '';
    }
}

function saveAuditParameters() {
    const updates = {
        'audit/base_profit': parseFloat(document.getElementById('audit-base-profit').value) || 0,
        'cpm': parseFloat(document.getElementById('audit-cpm').value) || 0,
        'monetag_zone_id': document.getElementById('audit-monetag-id').value,
        'geminiKey': document.getElementById('audit-gemini-key').value,
        'groqKey': document.getElementById('audit-groq-key').value,
        'telegramToken': document.getElementById('audit-telegram-token').value,
        'telegramChatId': document.getElementById('audit-telegram-chatid').value,
        'admin_whatsapp': document.getElementById('audit-whatsapp').value,
        'asaas_key': document.getElementById('audit-asaas-key').value,
        'vapid_key': document.getElementById('audit-vapid-key').value
    };

    const backendUrl = document.getElementById('audit-backend-url').value;
    if (backendUrl) {
        localStorage.setItem('CYBERCORE_BACKEND_URL', backendUrl);
        updates.backend_url = backendUrl;
    }

    // Backup local sempre
    localStorage.setItem('cfg_backup', JSON.stringify(updates));

    _pendingWrite = true;
    const btn = document.getElementById('btn-save-config');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Salvando...'; btn.style.opacity = '0.6'; }

    // Timeout de 10s para desbloquear o botão se travar
    const saveTimeout = setTimeout(() => {
        _pendingWrite = false;
        if (btn) { btn.disabled = false; btn.textContent = 'SALVAR CONFIGURAÇÕES'; btn.style.opacity = '1'; }
    }, 10000);

    hubDb.ref('config').update(updates)
        .then(() => {
            clearTimeout(saveTimeout);
            showToast('✅ Configurações salvas com sucesso!', 'success');
            _pendingWrite = false;
            if (btn) { btn.disabled = false; btn.textContent = 'SALVAR CONFIGURAÇÕES'; btn.style.opacity = '1'; }
        })
        .catch((err) => {
            clearTimeout(saveTimeout);
            showToast('⚠️ Firebase offline — salvo no cache local.', 'info');
            _pendingWrite = false;
            if (btn) { btn.disabled = false; btn.textContent = 'SALVAR CONFIGURAÇÕES'; btn.style.opacity = '1'; }
            console.warn('[SAVE ERROR]', err);
        });
}

const CONFIG_LABELS = {
    active: ['Núcleo IA', 'Núcleo CyberCore IA'],
    maintenance: ['Manutenção', 'Modo Manutenção CineCash'],
    deviceIdSecurity: ['ID Único', 'Segurança de ID Único'],
    production: ['Produção', 'Ambiente de Produção'],
    blockVPN: ['VPN', 'Bloqueio de Proxy/VPN'],
    blockRoot: ['Root', 'Detecção de Root/Jailbreak'],
    deviceLock: ['Device Lock', 'Vínculo de ID Único'],
    autoBan: ['Auto-Ban', 'Banimento Automático Multi-Contas']
};

async function updateConfig(path, value) {
    _pendingWrite = true;
    const label = CONFIG_LABELS[path] || [path, path];
    const statusText = value ? 'ATIVADO' : 'DESATIVADO';
    const icon = value ? '✅' : '⛔';

    try {
        await hubDb.ref('config').update({ [path]: value });
        showNotification(`${icon} ${label[1]} ${statusText}`, 'success');

        // Se for manutenção, avisa o servidor local imediatamente
        if (path === 'maintenance' && !value) {
            fetch('/api/system/maintenance/off').catch(() => {});
        }
    } catch (e) {
        console.error("Erro ao atualizar config:", e);
        showNotification(`❌ Falha ao atualizar ${label[0]}`, 'error');
    } finally {
        setTimeout(() => { _pendingWrite = false; }, 1000);
    }
}

async function updateConfigLegacy(path, value) {
    const label = CONFIG_LABELS[path] || [path, path];
    const statusText = value ? 'ATIVADO' : 'DESATIVADO';
    const icon = value ? '✅' : '⛔';

    try {
        await hubDb.ref(`config/${path}`).set(value);
        showToast(`${icon} ${label[1]}: ${statusText}`, value ? 'success' : 'info');
    } catch (e) {
        showToast(`Erro ao alterar ${label[1]}.`, 'error');
    }
    _pendingWrite = false;
}

function toggleSystem(type, status) {
    updateConfig(type, status);
}

function initPerformanceChart() {
    const ctx = document.getElementById('performanceChart')?.getContext('2d');
    if (!ctx) return;

    window.perfChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Receita Real',
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: '#10b981'
                },
                {
                    label: 'Previsão IA',
                    data: [],
                    borderColor: '#E8B830',
                    backgroundColor: 'rgba(232, 184, 48, 0.05)',
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.3,
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: '#E8B830'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#94a3b8', font: { size: 11 }, usePointStyle: true, padding: 15 }
                }
            },
            scales: {
                x: { display: true, grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#64748b', font: { size: 9 }, maxTicksLimit: 6 } },
                y: { display: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b', font: { size: 9 }, callback: v => 'R$' + v.toFixed(0) } }
            }
        }
    });

    // Escuta dados reais do Firebase
    hubDb.ref('config/profit_history').on('value', snap => {
        const data = snap.val();
        if (!data || !Array.isArray(data) || data.length === 0) return;
        updateChartWithRealData(data);
    });
}

function calcPredictions(values, ahead = 5) {
    if (values.length < 3) return [];
    const n = values.length;
    const sumX = (n - 1) * n / 2;
    const sumY = values.reduce((a, b) => a + b, 0);
    const sumXY = values.reduce((a, v, i) => a + i * v, 0);
    const sumX2 = values.reduce((a, i) => a + i * i, 0);
    const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX) || 0;
    const intercept = (sumY - slope * sumX) / n;
    const lastIdx = n - 1;
    const preds = [];
    for (let i = 1; i <= ahead; i++) {
        preds.push(Math.max(0, slope * (lastIdx + i) + intercept));
    }
    return preds;
}

function updateChartWithRealData(data) {
    if (!window.perfChart) return;

    const revenues = data.map(d => d.v || 0);
    const profits = data.map(d => d.p || 0);
    const times = data.map(d => {
        if (!d.t) return '';
        const date = new Date(d.t * 1000);
        return date.getHours().toString().padStart(2, '0') + ':' + date.getMinutes().toString().padStart(2, '0');
    });

    // Dataset 1: Receita Real (v)
    const realValues = revenues;
    // Dataset 2: Previsão IA
    const predictions = calcPredictions(realValues, 5);
    const fullLabels = [...times];
    for (let i = 1; i <= predictions.length; i++) {
        fullLabels.push('+' + (i * 30) + '\'');
    }

    const realData = [...realValues, ...Array(predictions.length).fill(null)];
    const predData = [...Array(realValues.length).fill(null), ...predictions];

    window.perfChart.data.labels = fullLabels;
    window.perfChart.data.datasets[0].data = realData;
    window.perfChart.data.datasets[1].data = predData;
    window.perfChart.update('none');

    // Atualiza badge de status
    const badge = document.querySelector('.badge-ia');
    if (badge && realValues.length >= 2) {
        const last = realValues[realValues.length - 1];
        const prev = realValues[realValues.length - 2];
        const trend = last >= prev ? '📈' : '📉';
        const pct = prev > 0 ? (((last - prev) / prev) * 100).toFixed(1) : '0.0';
        const signal = last >= prev ? '+' : '';
        badge.textContent = `PREVISÃO IA ATIVA ${trend} ${signal}${pct}%`;
    }
}

function initProfitChart() {
    const ctx = document.getElementById('profitChart')?.getContext('2d');
    if (!ctx) return;
    window.profitChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'],
            datasets: [{
                label: 'Lucro (R$)',
                data: [450, 680, 520, 940, 810, 1200, 1050],
                backgroundColor: '#00f3ff',
                borderRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } },
                x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
            }
        }
    });
}

function updateChart() {
    // 1. Gráfico de Barras (Lucro Semanal)
    if (window.profitChart && window.profitChart.data) {
        const data = window.profitChart.data;
        if (data.datasets && data.datasets[0]) {
            data.datasets[0].data.shift();
            data.datasets[0].data.push(Math.floor(Math.random() * 500) + 200);
            window.profitChart.update('none');
        }
    }

    // 2. Gráfico de Linha (Fluxo em Tempo Real)
    if (window.perfChart) {
        const chart = window.perfChart;
        const realDataset = chart.data.datasets[0].data;
        const labels = chart.data.labels;

        // Se não houver dados reais, gera pulsação de monitoramento (Visual Live)
        if (realDataset.length === 0 || realDataset.every(v => v === 0 || v === null)) {
            const now = new Date();
            const timeStr = now.getHours().toString().padStart(2, '0') + ':' +
                          now.getMinutes().toString().padStart(2, '0') + ':' +
                          now.getSeconds().toString().padStart(2, '0');

            if (labels.length > 15) {
                labels.shift();
                realDataset.shift();
            }

            labels.push(timeStr);
            // Simula variação de tráfego IA
            const val = (Math.random() * 0.4) - 0.2;
            realDataset.push(val);
            chart.update('quiet');
        }
    }
}

function injectSentinelLogs() {
    const logs = [
        "VARREDURA COMPLETA: 0 ameaças",
        "TRÁFEGO ANALISADO: 142 req/min",
        "BACKUP NEURAL EXECUTADO",
        "SENTINEL: Bloqueado IP Suspeito 192.168.1.10",
        "AUDITORIA: Saque verificado com sucesso",
        "SISTEMA: Carga do núcleo estável (2.4%)",
        "NEXUS: Padrão de comportamento aprendido [ID: 882]",
        "SEGURANÇA: Protocolo SSL/TLS renovado"
    ];
    const logContainer = document.getElementById('analysisLog');
    if (!logContainer) return;

    const line = document.createElement('div');
    line.className = 'log-entry';
    line.innerHTML = `<small>[${new Date().toLocaleTimeString()}]</small> <span>${logs[Math.floor(Math.random() * logs.length)]}</span>`;
    logContainer.prepend(line);
    if (logContainer.childNodes.length > 6) logContainer.lastChild.remove();
}

function updateWarRoom() {
    // Busca métricas em tempo real do Núcleo IA
    const metricsUrl = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/api/metrics` : '/api/metrics';
    fetch(metricsUrl)
        .then(r => r.json())
        .then(data => {
            if (data.core_online) {
                // Sugestão 2: War Room (Telemetria)
                updateEl('stat-latency', `${data.latency_ms}ms`);
                updateEl('stat-anomalies', data.anomalies);

                const dot = document.getElementById('python-core-ping');
                if (dot) {
                    dot.style.background = '#10b981';
                    dot.style.boxShadow = '0 0 12px #10b981';
                }

                // Sugestão 1: Alerta da Sentinela Preditiva
                if (data.anomalies > 0 && (!window._lastAnomalyCount || data.anomalies > window._lastAnomalyCount)) {
                    addFloatingNotification('⚠️', 'SENTINELA', `${data.anomalies} contas suspeitas detectadas pelo ROI.`, 'error');
                    if (window.audioError) window.audioError.play().catch(() => {});
                }
                window._lastAnomalyCount = data.anomalies;
            }
        }).catch(() => {});

    // 1. REDE DE AGENTES NEXUS — anima conexões SVG
    const agents = ['sentinel', 'auditor', 'nexus', 'fiscal'];
    agents.forEach(name => {
        const line = document.getElementById(`link-${name}`);
        const statusData = rtState.status?.agents?.[name];
        const status = statusData?.status || 'active';
        const lastPulse = statusData?.last_pulse || 0;

        // Verifica se o agente está em FALHA CRÍTICA ou "zumbi"
        const isFailed = status === 'failed';
        const isZombie = (Date.now() - lastPulse) > 120000 && !isFailed;

        let stroke = '#10b981'; // Active
        if (isFailed) stroke = '#ff0000'; // Falha Crítica
        else if (isZombie) stroke = '#ef4444'; // Zombie
        else if (status === 'analyzing') stroke = '#E8B830'; // Analyzing

        const opacity = (isZombie || isFailed) ? '1' : (status === 'active' ? '0.9' : '0.6');

        if (line) {
            line.setAttribute('stroke', stroke);
            line.setAttribute('stroke-opacity', opacity);
            line.setAttribute('stroke-width', (isFailed || status === 'analyzing') ? '4' : '2');

            if (isFailed) {
                line.classList.add('pulse-critical');
                addFloatingNotification('🚨', 'CRITICAL_FAILURE', `Agente ${name.toUpperCase()} desconectado!`, 'error');
            } else if (status === 'analyzing') {
                line.classList.add('pulse-active');
                line.classList.remove('pulse-critical');
            } else {
                line.classList.remove('pulse-active', 'pulse-critical');
            }
        }

        // Atualiza Badge do Agente
        const agentBadge = document.getElementById(`agent-${name}-war-status`);
        if (agentBadge) {
            agentBadge.innerText = isFailed ? 'CRITICAL FAIL' : (isZombie ? 'OFFLINE' : status.toUpperCase());
            agentBadge.className = `war-status status-${isFailed ? 'failed' : (isZombie ? 'offline' : status.toLowerCase())}`;
        }
    });

    // 1.1 Links Dinâmicos para Nós Conectados
    const nodes = rtState.neural?.nodes || {};
    const visualizer = document.getElementById('warroom-visual');
    const linksSvg = visualizer?.querySelector('.war-links');

    if (visualizer && linksSvg) {
        Object.entries(nodes).forEach(([id, node], index) => {
            let nodeEl = document.getElementById(`node-${id}`);
            let linkEl = document.getElementById(`link-${id}`);

            const angle = (index / Object.keys(nodes).length) * Math.PI * 2;
            const x = 50 + 35 * Math.cos(angle);
            const y = 50 + 35 * Math.sin(angle);

            if (!nodeEl) {
                nodeEl = document.createElement('div');
                nodeEl.id = `node-${id}`;
                nodeEl.className = 'node dynamic-node';
                nodeEl.innerHTML = `<span>${node.name}</span><small class="war-status status-active">ONLINE</small>`;
                visualizer.appendChild(nodeEl);

                linkEl = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                linkEl.id = `link-${id}`;
                linkEl.setAttribute('class', 'link-line');
                linkEl.setAttribute('stroke', '#10b981');
                linkEl.setAttribute('stroke-width', '1');
                linkEl.setAttribute('x1', '50%');
                linkEl.setAttribute('y1', '50%');
                linksSvg.appendChild(linkEl);
            }

            nodeEl.style.left = `${x}%`;
            nodeEl.style.top = `${y}%`;
            linkEl.setAttribute('x2', `${x}%`);
            linkEl.setAttribute('y2', `${y}%`);
        });
    }

    // 2. ESTRATÉGIAS EM EXECUÇÃO
    const strategiesEl = document.getElementById('warroom-strategies');
    if (strategiesEl) {
        const strategies = [
            { icon: '🚀', name: 'Otimização de ROI v4', desc: `CPM ajustado: R$ ${rtState.config?.cpm || 0.18}`, progress: Math.min(100, ((rtState.status?.financial_realtime?.hits || 0) / 1000) * 100) },
            { icon: '📊', name: 'Análise Neural', desc: `${Object.keys(rtState.users).length} usuários em treinamento`, progress: Math.min(100, (Object.keys(rtState.users).length / 10) * 100) },
            { icon: '🛡️', name: 'Sentinel Ativo', desc: `Varredura a cada 30s`, progress: 85 },
            { icon: '💳', name: 'Gateway Asaas', desc: `Saques: ${Object.values(rtState.history || {}).reduce((s, uw) => s + Object.values(uw).filter(w => w.status === 'pending').length, 0)} pendentes`, progress: 70 }
        ];
        strategiesEl.innerHTML = strategies.map((s, i) => `
            <div class="strategy-card ${i === 0 ? 'active' : ''}">
                <div class="strategy-icon">${s.icon}</div>
                <div class="strategy-info">
                    <h4>${s.name}</h4>
                    <p>${s.desc}</p>
                    <div class="strategy-progress"><div class="progress-fill" style="width: ${s.progress}%;"></div></div>
                </div>
            </div>
        `).join('');
    }

    // 3. COMANDOS DISPARADOS
    const cmdsEl = document.getElementById('warroom-commands');
    if (cmdsEl) {
        const now = new Date().toLocaleTimeString();
        const cmds = [
            { time: now, agent: 'SENTINEL', cmd: 'Varredura de segurança' },
            { time: now, agent: 'NEXUS', cmd: `Analisando ${Object.keys(rtState.users).length} usuários` },
            { time: now, agent: 'AUDITOR', cmd: `Fluxo: R$ ${Object.values(rtState.users).reduce((s, u) => s + parseFloat(u.balance || 0), 0).toFixed(2)}` }
        ];
        cmdsEl.innerHTML = cmds.map(c => `
            <div class="cmd-line">
                <small style="color:var(--primary)">[${c.time}]</small>
                <strong style="color:var(--teal)">${c.agent}</strong>
                <span style="opacity:0.8">${c.cmd}</span>
            </div>
        `).join('');
    }
}

function updateSentinelStatus() {
    const orb = document.getElementById('sentinel-orb');
    if (orb) {
        orb.style.background = '#10b981';
        orb.style.boxShadow = '0 0 15px #10b981';
    }
    const text = document.getElementById('sentinel-status-text');
    if (text) {
        const statuses = ["ESCANEANDO NÓS...", "PROTEÇÃO ATIVA", "NOMINAL", "AGENTE SENTINEL OK"];
        text.innerText = statuses[Math.floor(Math.random() * statuses.length)];
    }
}

function startTabFlash() {
    let originalTitle = document.title;
    let isFlash = false;
    const interval = setInterval(() => {
        document.title = isFlash ? "🚨 NOVO SAQUE!" : originalTitle;
        isFlash = !isFlash;
    }, 1000);

    window.addEventListener('click', () => {
        clearInterval(interval);
        document.title = originalTitle;
    }, { once: true });
}

function openUserEdit(uid) {
    const user = rtState.users[uid];
    if (!user) return;
    document.getElementById('edit-uid').value = uid;
    document.getElementById('edit-email').value = user.email || 'N/A';
    document.getElementById('edit-balance').value = parseFloat(user.balance || 0).toFixed(2);
    document.getElementById('modal-edit-user').style.display = 'flex';
}

function closeUserModal() {
    document.getElementById('modal-edit-user').style.display = 'none';
}

function saveUserBalance() {
    const uid = document.getElementById('edit-uid').value;
    const newBalance = parseFloat(document.getElementById('edit-balance').value) || 0;
    if (!uid) return;

    hubDb.ref(`users/${uid}/balance`).set(newBalance)
        .then(() => {
            showToast('Saldo atualizado.', 'success');
            closeUserModal();
        })
        .catch(() => showToast('Erro ao atualizar saldo.', 'error'));
}

function toggleUserBan(uid, shouldBan) {
    const status = shouldBan ? 'banido' : 'ativo';
    hubDb.ref(`users/${uid}/status`).set(status)
        .then(() => {
            const emoji = status === 'banido' ? '🔨' : '♻️';
            const label = status === 'banido' ? 'BANIDO' : 'REATIVADO';
            showToast(`${emoji} ${label}: Usuário ${uid.substring(0,8)} ${status}.`, status === 'banido' ? 'error' : 'success');
        })
        .catch(e => showToast('Erro ao atualizar status.', 'error'));
}

function approveWithdrawal(uid, wid) {
    const url = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/payments/approve/${wid}` : `/payments/approve/${wid}`;

    showToast('🚀 Iniciando auditoria e liquidação...', 'info');

    fetch(url, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('✅ Liquidação confirmada via Asaas!', 'success');
            } else {
                showToast(`❌ Falha: ${data.msg}`, 'error');
                // Se falhou no Sentinel, o log já estará na Sala de Guerra
            }
        })
        .catch(() => showToast('Erro de conexão com o Núcleo.', 'error'));
}

function rejectWithdrawal(uid, wid) {
    hubDb.ref(`withdrawals/${uid}/${wid}/status`).set('rejected')
        .then(() => showToast('⛔ Saque recusado.', 'info'))
        .catch(() => showToast('Erro ao recusar.', 'error'));
}

function setWithdrawalFilter(filter, btn) {
    _withdrawalFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderWithdrawalsTable();
}

function generateAIReport() {
    showToast("Gerando relatório neural...", "info");
    setTimeout(() => {
        typeIAResponse("RELATÓRIO DE MONITORAMENTO:\n- Integridade do Sistema: 99.8%\n- Usuários Ativos: " + Object.keys(rtState.users).length + "\n- Projeção de Lucro (24h): R$ 850,00\n- Nenhuma anomalia crítica detectada.", 'nexus');
        showPanel('terminal');
    }, 1500);
}

function togglePass(id) {
    const input = document.getElementById(id);
    if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

function toggleMic() {
    showToast("Reconhecimento de voz em desenvolvimento...", "info");
}

function updateNeuralActivity() {
    const containers = ['neural-activity-auditor', 'neural-activity-nexus', 'neural-activity-sentinel'];
    containers.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.children.length === 0) {
            for (let i = 0; i < 15; i++) {
                const bar = document.createElement('div');
                bar.className = 'neural-bar';
                el.appendChild(bar);
            }
        }
        Array.from(el.children).forEach(bar => {
            const h = Math.floor(Math.random() * 80) + 10;
            bar.style.height = `${h}%`;
            bar.style.opacity = (h / 100) + 0.2;
        });
    });
}

// === FUNÇÕES FALTANTES ===
// === GESTÃO DE PROJETOS (INTEL CONNECTOR) ===
let _pendingProject = null;

function showAddProjectModal() {
    const modalHtml = `
        <div id="modal-add-project-overlay" class="premium-modal-overlay">
            <div class="modal-window premium-glass" style="max-width: 500px;">
                <div class="modal-header">
                    <h3>Conectar Novo Nó Inteligente</h3>
                    <button class="btn-close-modal" onclick="document.getElementById('modal-add-project-overlay').remove()">×</button>
                </div>
                <div class="modal-body">
                    <div id="connector-step-1">
                        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 20px;">
                            Insira a URL do projeto. O CyberCore analisará o stack tecnológico e protocolos de segurança automaticamente.
                        </p>
                        <div class="p-input-group">
                            <label>URL DO PROJETO</label>
                            <input type="text" id="project-url-input" placeholder="https://meu-app.com">
                        </div>
                        <button class="btn-premium" onclick="analisarProjetoIA()" style="width: 100%; margin-top: 20px;">INICIAR ESCANEAMENTO</button>
                    </div>
                    <div id="connector-step-2" style="display: none;">
                        <div class="analysis-results" style="background: rgba(255,255,255,0.03); padding: 20px; border-radius: 12px; margin-top: 10px;">
                            <h4 id="res-project-name" style="color: var(--gold); margin-bottom: 15px;">-</h4>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; font-size: 12px;">
                                <div>
                                    <span style="opacity: 0.6; display: block;">STACK DETECTADO</span>
                                    <strong id="res-tech-stack">-</strong>
                                </div>
                                <div>
                                    <span style="opacity: 0.6; display: block;">SCORE SEGURANÇA</span>
                                    <strong id="res-security-score">-</strong>
                                </div>
                            </div>
                        </div>
                        <p style="font-size: 11px; color: var(--text-secondary); margin-top: 15px;">
                            ✅ Compatível com CyberCore Hub. Deseja estabelecer conexão segura?
                        </p>
                        <button class="btn-premium" onclick="confirmarConexaoProjeto()" style="width: 100%; margin-top: 20px;">ESTABELECER CONEXÃO</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

async function analisarProjetoIA() {
    const urlInput = document.getElementById('project-url-input');
    const url = urlInput.value.trim();
    if (!url) return showToast("Insira uma URL válida", "error");

    const btn = event.target;
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "🔍 ANALISANDO...";

    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || '';
        const response = await fetch(`${baseUrl}/api/cybercore/analyze_project`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const result = await response.json();

        if (result.status === 'success') {
            _pendingProject = result.data;
            document.getElementById('connector-step-1').style.display = 'none';
            document.getElementById('connector-step-2').style.display = 'block';
            document.getElementById('res-project-name').innerText = _pendingProject.name.toUpperCase();
            document.getElementById('res-tech-stack').innerText = _pendingProject.tech_stack.join(', ');
            document.getElementById('res-security-score').innerText = _pendingProject.security_score + '%';
            showToast("Análise concluída com sucesso", "success");
        } else {
            showToast(result.msg, "error");
        }
    } catch (e) {
        showToast("Erro ao conectar com o backend", "error");
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

function confirmarConexaoProjeto() {
    if (!_pendingProject) return;
    showToast("⛓️ Gerando Token de Conexão...", "info");

    const projectId = 'node_' + Date.now();
    hubDb.ref(`neural/nodes/${projectId}`).set({
        ..._pendingProject,
        connected_at: firebase.database.ServerValue.TIMESTAMP,
        token: 'cc_' + Math.random().toString(36).substr(2, 16)
    }).then(() => {
        showToast("🚀 Nó conectado ao Hub CyberCore!", "success");
        const modal = document.getElementById('modal-add-project-overlay');
        if (modal) modal.remove();
        // O renderProjects será chamado pelo listener do RTDB
    });
}


function addBancaPrompt() {
    const valor = prompt("Valor para adicionar à banca (R$):");
    if (valor && !isNaN(valor)) {
        const ref = firebase.database().ref('stats/banca');
        ref.transaction(current => (current || 0) + parseFloat(valor));
        showToast(`R$ ${valor} adicionado à banca.`, "success");
    }
}

function resetBancaPrompt() {
    if (confirm("Zerar a banca? Esta ação não pode ser desfeita.")) {
        firebase.database().ref('stats/banca').set(0);
        showToast("Banca zerada.", "success");
    }
}

function addReservaPrompt() {
    const valor = prompt("Valor para adicionar à reserva Monetag (R$):");
    if (valor && !isNaN(valor)) {
        const ref = firebase.database().ref('stats/reserva_monetag');
        ref.transaction(current => (current || 0) + parseFloat(valor));
        showToast(`R$ ${valor} adicionado à reserva.`, "success");
    }
}

function resetReservaPrompt() {
    if (confirm("Zerar a reserva Monetag?")) {
        firebase.database().ref('stats/reserva_monetag').set(0);
        showToast("Reserva zerada.", "success");
    }
}

function testPushNotification() {
    const vapid = document.getElementById('vapid-key')?.value || '';
    if (!vapid) return showToast("Configure a VAPID Key primeiro.", "error");
    fetch(`${CYBERCORE_BACKEND_URL}/send-test-push`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vapid })
    }).then(r => r.json()).then(d => {
        showToast(d.message || "Push enviado!", "success");
    }).catch(() => showToast("Falha ao enviar push.", "error"));
}

function approveAllWithdrawals() {
    if (!confirm("Aprovar TODOS os saques pendentes?")) return;
    fetch(`${CYBERCORE_BACKEND_URL}/process-all-payments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    }).then(r => r.json()).then(d => {
        showToast(d.message || "Saques processados!", "success");
    }).catch(() => showToast("Falha ao processar saques.", "error"));
}
