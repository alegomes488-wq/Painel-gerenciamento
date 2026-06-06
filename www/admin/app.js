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
const LOCAL_BACKEND = 'http://localhost:7860';
// Prioriza o que está no localStorage ou o LOCAL_BACKEND
let CYBERCORE_BACKEND_URL = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;

// Desativa qualquer ponte com Hugging Face ou portas antigas
localStorage.setItem('CYBERCORE_BACKEND_URL', CYBERCORE_BACKEND_URL);

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

// --- HEALTH CHECK REAL (STATUS DOS AGENTES) ---
let backendOnline = false;

async function checkBackendHealth() {
    try {
        const url = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/health` : '/health';
        const resp = await fetch(url);
        backendOnline = resp.ok;
    } catch (e) {
        backendOnline = false;
    }
    updateAgentStatus();
}

function updateAgentStatus() {
    const agents = ['BUILDER','DESIGNER','FULLSTACK','PYTHON','JAVA','SOFTWARE'];
    const tagClass = backendOnline ? 'online' : 'offline';
    const tagText = backendOnline ? '● ATIVO' : '● OFFLINE';
    agents.forEach(a => {
        const el = document.getElementById(`studio-status-${a}`);
        if (el) {
            el.className = `status-tag ${tagClass}`;
            el.textContent = tagText;
        }
        // Also update overview cards
        const ov = document.getElementById(`ov-status-${a}`);
        if (ov) {
            ov.className = `status-tag ${tagClass}`;
            ov.textContent = tagText;
        }
    });
}

checkBackendHealth();
setInterval(checkBackendHealth, 30000);

// ===== PROJECT MANAGER (CHAT) =====
let pmSessionId = 'pm_' + Date.now();
let pmChatOpen = false;

async function sendPM() {
    const input = document.getElementById('pm-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    addPMMessage(msg, 'user');
    const container = document.getElementById('pm-messages');
    container.innerHTML += '<div style="text-align:center;padding:8px;color:var(--text-secondary);font-size:10px;">🤔 Processando...</div>';
    container.scrollTop = container.scrollHeight;
    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/project-manager/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: pmSessionId, message: msg })
        });
        const data = await resp.json();
        // Remove "processing" indicator
        const processing = container.querySelector('div:last-child');
        if (processing && processing.textContent.includes('Processando')) processing.remove();
        if (data.status === 'success') {
            addPMMessage(data.answer, 'assistant', data.engine);
            // Update project info bar
            if (data.project) {
                updatePMProjectBar(data.project);
            }
            // Update engine badge
            const badge = document.getElementById('pm-engine-badge');
            if (badge && data.engine) {
                badge.style.display = 'inline-block';
                badge.textContent = data.engine === 'groq' ? '⚡ Groq' : '🖥️ Ollama';
            }
        } else {
            container.innerHTML += `<div style="color:#ef4444;font-size:11px;padding:8px;">[ERRO] ${data.msg || 'Falha na comunicação'}</div>`;
        }
    } catch (e) {
        const processing = container.querySelector('div:last-child');
        if (processing && processing.textContent.includes('Processando')) processing.remove();
        container.innerHTML += `<div style="color:#ef4444;font-size:11px;padding:8px;">[ERRO] Falha ao conectar com o backend.</div>`;
    }
    container.scrollTop = container.scrollHeight;
}

function addPMMessage(text, role, engine) {
    const container = document.getElementById('pm-messages');
    const isUser = role === 'user';
    const icon = isUser ? '👤' : '🤖';
    const bgColor = isUser ? 'rgba(0,243,255,0.05)' : 'rgba(232,184,48,0.05)';
    const borderColor = isUser ? 'rgba(0,243,255,0.1)' : 'rgba(232,184,48,0.1)';
    const engineTag = engine ? `<span style="font-size:8px;color:var(--text-muted);margin-left:8px;">[${engine === 'groq' ? '⚡Groq' : '🖥️Ollama'}]</span>` : '';
    container.innerHTML += `
        <div style="display:flex;gap:10px;align-items:flex-start;">
            <span style="font-size:16px;">${icon}</span>
            <div style="flex:1;background:${bgColor};border:1px solid ${borderColor};border-radius:12px;padding:10px 14px;color:${isUser ? '#fff' : 'var(--text-secondary)'};line-height:1.5;font-size:12px;white-space:pre-wrap;">${text}${engineTag}</div>
        </div>
    `;
}

function updatePMProjectBar(project) {
    const bar = document.getElementById('pm-project-bar');
    const nameEl = document.getElementById('pm-project-name-display');
    const typeEl = document.getElementById('pm-project-type-display');
    const pathEl = document.getElementById('pm-project-path-display');
    if (!bar || !nameEl) return;
    if (project.name) {
        bar.style.display = 'flex';
        nameEl.textContent = project.name;
        typeEl.textContent = project.type ? `(${project.type})` : '';
        pathEl.textContent = project.path || '';
    }
}

function togglePMChat() {
    pmChatOpen = !pmChatOpen;
    const body = document.getElementById('pm-chat-body');
    const icon = document.getElementById('pm-toggle-icon');
    if (body) body.style.display = pmChatOpen ? 'block' : 'none';
    if (icon) icon.textContent = pmChatOpen ? '▲' : '▼';
}

function pmQuickAction(action) {
    const input = document.getElementById('pm-input');
    if (!input) return;
    input.value = action;
    sendPM();
}

// ===== CREDIT SYSTEM =====
async function loadCredits() {
    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/credits`);
        const data = await resp.json();
        if (data.status !== 'success') return;
        const credits = data.credits;
        // Update credit badges on each agent card
        const agents = ['BUILDER','DESIGNER','FULLSTACK','PYTHON','JAVA','SOFTWARE'];
        agents.forEach(a => {
            const c = credits[a] || { limit: 50, used: 0 };
            const el = document.getElementById(`credit-${a}`);
            if (el) {
                const remaining = c.limit - c.used;
                const color = remaining <= 5 ? '#ef4444' : remaining <= 15 ? '#fbbf24' : '#10b981';
                el.innerHTML = `<span style="color:${color};">●</span> ${remaining}/${c.limit}`;
            }
        });
        // Update header credits display
        const display = document.getElementById('studio-credits-display');
        if (display) {
            const total = agents.reduce((s, a) => s + (credits[a]?.limit || 50), 0);
            const used = agents.reduce((s, a) => s + (credits[a]?.used || 0), 0);
            display.innerHTML = `<span style="font-size:10px;color:var(--text-secondary);font-weight:700;">💳 ${used}/${total}</span>`;
        }
    } catch (e) {
        console.warn("Credits offline");
    }
}

// Load credits on startup and every 30s
loadCredits();
setInterval(loadCredits, 30000);

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

    // Sincronização de Nós (Projetos) — monitoramento em tempo real
    hubDb.ref('neural/nodes').on('value', snap => {
        if (!rtState.neural) rtState.neural = {};
        const nodes = snap.val() || {};
        rtState.neural.nodes = nodes;
        // Sincroniza o array connectedProjects com os dados do Firebase
        connectedProjects = Object.keys(nodes).map(k => ({ id: k, ...nodes[k] }));
        renderProjects();
        updateWarRoom();
        if (typeof renderWatchProjects === 'function') renderWatchProjects();
        if (typeof renderCmdProjectsTable === 'function') renderCmdProjectsTable();
        // Migra projetos do localStorage para Firebase se existirem
        migrateLocalProjectsToFirebase();
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

    initProfitChart();
    console.log("[NEXUS] Telemetria de Gráficos Iniciada");
}

// ============ UI & DASHBOARD ============

let currentWatchFilter = null;
let currentCmdFilter = 'website';

function filterWatchProjects(type) {
    currentWatchFilter = type;
    renderWatchProjects();
}

function showPanel(id, filterType = null) {
    // 1. Gerenciamento Visual do Menu Lateral (Nav Groups)
    document.querySelectorAll('.nav-group').forEach(group => {
        const btn = group.querySelector('.nav-link');
        // Identifica se este grupo deve estar expandido
        const isWatchGroup = btn && btn.id === 'btn-nav-watch' && (id === 'watch' || ['saques', 'users', 'security', 'terminal'].includes(id));
        const isStudioGroup = btn && btn.id === 'btn-nav-studio' && (id === 'studio' || ['orchestrator', 'bridge', 'memory'].includes(id));

        if (isWatchGroup || isStudioGroup || (btn && btn.id === `btn-nav-${id}`)) {
            group.classList.add('expanded');
        } else {
            group.classList.remove('expanded');
        }
    });

    document.querySelectorAll('.panel-view').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(b => b.classList.remove('active-watch'));
    document.querySelectorAll('.sub-link').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sub-link').forEach(b => b.classList.remove('active-watch'));
    document.querySelectorAll('.sub-link').forEach(b => b.classList.remove('active-studio'));

    const target = document.getElementById('panel-' + id);
    if (target) {
        target.classList.add('active');
        
        // Find corresponding sidebar nav-link
        const navBtn = document.getElementById('btn-nav-' + id) ||
                       (['saques', 'users', 'security', 'terminal'].includes(id) ? document.getElementById('btn-nav-watch') : null) ||
                       (['orchestrator', 'bridge', 'memory'].includes(id) ? document.getElementById('btn-nav-studio') : null);

        if (navBtn) {
            if (navBtn.id === 'btn-nav-watch') {
                navBtn.classList.add('active-watch');
            } else {
                navBtn.classList.add('active');
            }
        }
        
        // Handle sub-links active states
        if (filterType || ['saques', 'users', 'security', 'terminal', 'orchestrator', 'bridge', 'memory'].includes(id)) {
            const subLinks = document.querySelectorAll(`.sub-nav .sub-link`);
            subLinks.forEach(link => {
                const text = link.textContent.toLowerCase();
                if (filterType && text.includes(filterType)) {
                     link.classList.add('active', 'active-watch');
                } else if (id === 'saques' && text.includes('saques')) {
                     link.classList.add('active', 'active-watch');
                } else if (id === 'users' && text.includes('usuários')) {
                     link.classList.add('active', 'active-watch');
                } else if (id === 'security' && text.includes('alertas')) {
                     link.classList.add('active', 'active-watch');
                } else if (id === 'terminal' && text.includes('logs')) {
                     link.classList.add('active', 'active-watch');
                } else if (['orchestrator', 'bridge', 'memory'].includes(id) && text.includes(id)) {
                     link.classList.add('active', 'active-studio');
                }
            });
        }

        if (id === 'watch') {
            filterWatchProjects(filterType);
        }

        if (id === 'studio') listStudioFiles();
        if (id === 'orchestrator') document.getElementById('orch-input')?.focus();
        if (id === 'memory') loadMemoryExplorer();

        const titleMap = {
            overview: '[SYS_DASHBOARD] // COMMAND CENTER',
            analytics: '[SYS_ANALYTICS] // ANALYTICS & TELEMETRIA',
            projects: '[SYS_CONNECTOR] // INTEL CONNECTOR',
            watch: '[SYS_WATCH] // CYBERCORE WATCH',
            studio: '[SYS_STUDIO] // CYBERCORE STUDIO',
            users: '[SYS_DATABASE] // USUÁRIOS',
            memory: '[SYS_NEURAL] // MEMÓRIA',
            security: '[SYS_SENTINEL] // SEGURANÇA',
            settings: '[SYS_CONFIG] // CONFIGURAÇÕES',
            saques: '[SYS_FINANCE] // SAQUES PIX',
            terminal: '[SYS_TERMINAL] // LOGS',
            audit: '[SYS_AUDIT] // AUDITORIA NEXUS'
        };
        const titleEl = document.getElementById('current-panel-name');
        if (titleEl) titleEl.textContent = titleMap[id] || '[SYS_TERMINAL]';

        if (id === 'watch') renderWatchProjects();
        if (id === 'studio') listStudioFiles();
        if (id === 'overview') renderCmdProjectsTable();
        if (id === 'audit') {
            // Garante que os logs do Nexus apareçam no painel de Auditoria
            const auditLog = document.getElementById('logs-nexus');
            if (auditLog && auditLog.children.length === 0) {
                 initNexusAgent();
            }
        }
    }
}

function selectAgentFromNav(agent) {
    showPanel('studio');
    selectAgent(agent);
    
    // Set active sub-link
    document.querySelectorAll('.sub-nav span').forEach(link => {
        if (link.textContent.toUpperCase().includes(agent)) {
            link.classList.add('active');
            link.classList.add('active-studio');
        }
    });
}

function filterCmdProjects(type, el) {
    currentCmdFilter = type;
    document.querySelectorAll('.filter-btn').forEach(b => {
        b.classList.remove('active');
        b.style.borderColor = 'transparent';
        b.style.background = 'transparent';
        b.style.color = 'var(--text-secondary)';
    });
    if (el) {
        el.classList.add('active');
        el.style.borderColor = 'rgba(0, 243, 255, 0.2)';
        el.style.background = 'rgba(0, 243, 255, 0.1)';
        el.style.color = '#fff';
    }
    renderCmdProjectsTable();
}

function renderCmdProjectsTable() {
    const tbody = document.getElementById('cmd-projects-table-body');
    if (!tbody) return;

    const filtered = connectedProjects.filter(p => p.type === currentCmdFilter);

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 25px; opacity: 0.4;">Nenhum projeto deste tipo conectado.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(p => {
        const health = p.health || {};
        const isOnline = health.status === 'online';
        const isDegraded = health.status === 'degraded';
        const color = isOnline ? '#10b981' : (isDegraded ? '#fbbf24' : '#ef4444');
        const statusLabel = isOnline ? 'Online' : (isDegraded ? 'Degradado' : 'Offline');
        const latency = health.latency_ms ? health.latency_ms + 'ms' : '--';
        const lastCheck = health.last_checked 
            ? new Date(health.last_checked).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
            : 'Pendente';
            
        return `
            <tr style="border-bottom: 1px solid var(--border-glass);">
                <td style="padding: 10px 12px; font-weight: 700; color: #fff;">${p.name || p.identifier}</td>
                <td style="padding: 10px 12px; opacity: 0.7;">${p.type.toUpperCase()}</td>
                <td style="padding: 10px 12px; color: ${color}; font-weight: 800;">● ${statusLabel}</td>
                <td style="padding: 10px 12px;">${health.uptime || '99.98%'}</td>
                <td style="padding: 10px 12px; color: #10b981; font-weight: 800;">${health.latency_ms ? (health.latency_ms < 100 ? '99' : (health.latency_ms < 500 ? '92' : '78')) : '96'}</td>
                <td style="padding: 10px 12px; opacity: 0.6;">${lastCheck}</td>
            </tr>
        `;
    }).join('');
}

function cmdGerarEquipe() {
    const name = document.getElementById('cmd-project-name').value.trim();
    const type = document.getElementById('cmd-project-type').value;
    const desc = document.getElementById('cmd-project-desc').value.trim();
    
    if (!name || !desc) {
        return showToast("Preencha o nome e o objetivo do projeto.", "error");
    }
    
    showToast(`🤖 Gerando equipe para o projeto: ${name}...`, "info");
    
    const list = document.getElementById('cmd-suggested-team-list');
    list.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.02); border-radius: 6px; border: 1px solid var(--border-glass);">
            <span style="display: flex; align-items: center; gap: 8px;"><span style="color:#a855f7">●</span> Builder</span>
            <span style="color:#10b981">✓</span>
        </div>
    `;
    
    if (type === 'android') {
        list.innerHTML += `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.02); border-radius: 6px; border: 1px solid var(--border-glass);">
                <span style="display: flex; align-items: center; gap: 8px;"><span style="color:#84cc16">●</span> Java Core</span>
                <span style="color:#10b981">✓</span>
            </div>
        `;
    } else if (type === 'website' || type === 'api') {
        list.innerHTML += `
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.02); border-radius: 6px; border: 1px solid var(--border-glass);">
                <span style="display: flex; align-items: center; gap: 8px;"><span style="color:#3b82f6">●</span> FullStack</span>
                <span style="color:#10b981">✓</span>
            </div>
        `;
    }
    
    list.innerHTML += `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.02); border-radius: 6px; border: 1px solid var(--border-glass);">
            <span style="display: flex; align-items: center; gap: 8px;"><span style="color:#ec4899">●</span> Designer</span>
            <span style="color:#10b981">✓</span>
        </div>
    `;
    
    const projectId = 'PRJ' + Date.now().toString(36).toUpperCase();
    const projectData = {
        id: projectId,
        name: name,
        type: type,
        identifier: type === 'website' ? `https://${name.toLowerCase().replace(/\s+/g, '')}.com` : `com.empresa.${name.toLowerCase().replace(/\s+/g, '')}`,
        framework: type === 'website' ? 'React' : type === 'android' ? 'Android SDK / Kotlin' : 'REST API / Node.js',
        addedAt: new Date().toISOString()
    };
    
    fetch(`${CYBERCORE_BACKEND_URL}/api/project/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: projectId, data: projectData })
    })
    .then(r => r.json())
    .then(resp => {
        if (resp.status === 'success') {
            showToast(`Projeto '${name}' criado e adicionado ao painel!`, "success");

            // Invoca o Studio para gerar os arquivos base
            showPanel('studio');
            document.getElementById('studio-prompt').value = `Scaffold inicial para o projeto ${name} (${type}): ${desc}`;
            selectAgent(type === 'android' ? 'JAVA' : (type === 'python' ? 'PYTHON' : 'BUILDER'));
            setTimeout(generateTeam, 1000);

            document.getElementById('cmd-project-name').value = '';
            document.getElementById('cmd-project-desc').value = '';
        }
    });
}

function sendCmdOrchestratorCommand() {
    const cmd = document.getElementById('cmd-orchestrator-input').value.trim();
    if (!cmd) return showToast("Digite um comando para o Orchestrator", "error");
    
    showToast("🔮 Orchestrator processando diretiva...", "info");
    
    fetch(`${CYBERCORE_BACKEND_URL}/api/ai/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            prompt: cmd,
            agent: 'ORCHESTRATOR',
            uid: currentUser?.uid || "admin_master"
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.answer) {
            showPanel('terminal');
            typeIAResponse(data.answer, 'cmo');
            document.getElementById('cmd-orchestrator-input').value = '';
        }
    })
    .catch(() => {
        showToast("Erro ao contatar o Orchestrator.", "error");
    });
}

function useCmdExample(text) {
    document.getElementById('cmd-orchestrator-input').value = text;
}

let selectedAgent = 'BUILDER'; // Default agent

function selectAgent(agent) {
    selectedAgent = agent;
    showToast(`Agente ${agent} selecionado no Studio.`, "info");

    // Mostra/Esconde ações específicas de Java
    const javaActions = document.getElementById('java-build-actions');
    if (javaActions) {
        javaActions.style.display = agent === 'JAVA' ? 'flex' : 'none';
    }

    const terminal = document.getElementById('studio-output');
    const body = document.getElementById('studio-terminal-body');
    if (terminal) terminal.style.display = 'block';
    if (body) {
        body.innerHTML += `<div style="color: var(--gold); margin-bottom: 15px; font-family: 'JetBrains Mono'; font-size: 12px; border-bottom: 1px solid rgba(232,184,48,0.1); padding-bottom: 5px;">> Agente ${agent} inicializado e aguardando diretrizes...</div>`;
        body.scrollTop = body.scrollHeight;
    }
}

async function generateTeam() {
    const prompt = document.getElementById('studio-prompt').value;
    if (!prompt) return showToast("Descreva o objetivo primeiro.", "error");

    const terminal = document.getElementById('studio-output');
    const body = document.getElementById('studio-terminal-body');
    if (terminal) terminal.style.display = 'block';

    const gptmakerAgentId = localStorage.getItem('gptmakerAgentId');

    if (body) {
        const source = gptmakerAgentId ? 'GPT Maker' : selectedAgent;
        body.innerHTML += `<div style="color: #fff; margin-top: 15px; font-family: 'JetBrains Mono'; font-size: 12px;">[SISTEMA] Convocando ${source} para: "${prompt}"</div>`;
        body.scrollTop = body.scrollHeight;

        try {
            const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
            let answer = '';

            if (gptmakerAgentId) {
                // Use GPT Maker API
                const resp = await fetch(`${baseUrl}/api/ai/gptmaker/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agent_id: gptmakerAgentId,
                        prompt: `Com base no objetivo: "${prompt}", gere uma estrutura de arquivos JSON simplificada onde a chave é o nome do arquivo e o valor é o código. Exemplo: {"index.html": "...", "script.js": "..."}. IMPORTANTE: Responda APENAS o JSON bruto, sem textos extras ou blocos de código Markdown.`,
                        context_id: 'cybercore_studio'
                    })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    answer = data.message || '';
                } else {
                    body.innerHTML += `<div style="color: #ef4444; font-family: 'JetBrains Mono'; font-size: 12px;">[GPT MAKER ERRO] ${data.msg || 'Falha na comunicação'}</div>`;
                    body.scrollTop = body.scrollHeight;
                    return;
                }
            } else {
                // Use CyberCore native agents
                const resp = await fetch(`${baseUrl}/api/ai/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agent: selectedAgent,
                        prompt: `Com base no objetivo: "${prompt}", gere uma estrutura de arquivos JSON simplificada onde a chave é o nome do arquivo e o valor é o código. Exemplo: {"index.html": "...", "script.js": "..."}. IMPORTANTE: Responda APENAS o JSON bruto, sem textos extras ou blocos de código Markdown.`,
                        uid: 'admin_studio'
                    })
                });
                const data = await resp.json();
                answer = data.answer || "";
            }

            // Tenta extrair JSON
            let files = {};
            try {
                const jsonStr = answer.includes('{') ? answer.substring(answer.indexOf('{'), answer.lastIndexOf('}') + 1) : answer;
                files = JSON.parse(jsonStr);
            } catch(e) {
                console.warn("IA não retornou JSON puro, tentando processar como texto.");
            }

            if (Object.keys(files).length > 0) {
                body.innerHTML += `<div style="color: var(--cyan); font-family: 'JetBrains Mono'; font-size: 12px;">[IA] Equipe gerou ${Object.keys(files).length} arquivos.</div>`;
                for (const [filename, content] of Object.entries(files)) {
                    await fetch(`${baseUrl}/api/studio/save-file`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ filename, content })
                    });
                    body.innerHTML += `<div style="color: #64748b; font-family: 'JetBrains Mono'; font-size: 11px;">  └─ [CRIADO] ${filename}</div>`;
                }
                listStudioFiles();
                showToast("Estrutura do projeto gerada com sucesso!", "success");
            } else {
                body.innerHTML += `<div style="color: var(--cyan); font-family: 'JetBrains Mono'; font-size: 12px;">[IA] Resposta do Núcleo:</div>`;
                body.innerHTML += `<div style="color: #94a3b8; font-family: 'JetBrains Mono'; font-size: 11px; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 4px; margin-top: 5px;">${renderMarkdown(answer)}</div>`;
            }
        } catch (e) {
            body.innerHTML += `<div style="color: #ef4444; font-family: 'JetBrains Mono'; font-size: 12px;">[ERRO] Falha crítica na comunicação com o backend Studio.</div>`;
        }
        body.scrollTop = body.scrollHeight;
    }
}

// --- GPT MAKER STUDIO INTEGRATION ---
async function loadGptmakerWorkspaces() {
    const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
    const select = document.getElementById('gptmaker-workspace-select');
    if (!select) return;
    select.innerHTML = '<option>Carregando...</option>';
    try {
        const resp = await fetch(`${baseUrl}/api/ai/gptmaker/workspaces`);
        const data = await resp.json();
        if (data.status === 'success' && data.workspaces && data.workspaces.length > 0) {
            select.innerHTML = '<option value="">Selecione um workspace</option>';
            data.workspaces.forEach(ws => {
                const id = ws.id || ws._id || ws.workspaceId || '';
                const name = ws.name || ws.title || id;
                select.innerHTML += `<option value="${id}">${name}</option>`;
            });
            if (data.workspaces.length === 1) {
                select.value = data.workspaces[0].id || data.workspaces[0]._id || '';
                loadGptmakerAgents(select.value);
            }
        } else {
            select.innerHTML = '<option value="">Nenhum workspace encontrado</option>';
        }
    } catch (e) {
        select.innerHTML = '<option value="">Erro ao carregar</option>';
    }
}

async function loadGptmakerAgents(workspaceId) {
    if (!workspaceId) return;
    const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
    const select = document.getElementById('gptmaker-agent-select');
    if (!select) return;
    select.innerHTML = '<option>Carregando...</option>';
    try {
        const resp = await fetch(`${baseUrl}/api/ai/gptmaker/agents/${workspaceId}`);
        const data = await resp.json();
        if (data.status === 'success' && data.agents && data.agents.length > 0) {
            select.innerHTML = '<option value="">Selecione um agente</option>';
            data.agents.forEach(agent => {
                const id = agent.id || agent._id || agent.agentId || '';
                const name = agent.name || agent.title || id;
                select.innerHTML += `<option value="${id}">${name}</option>`;
            });
        } else {
            select.innerHTML = '<option value="">Nenhum agente encontrado</option>';
        }
    } catch (e) {
        select.innerHTML = '<option value="">Erro ao carregar</option>';
    }
}

function selectGptmakerAgent() {
    const agentId = document.getElementById('gptmaker-agent-select')?.value;
    if (agentId) {
        localStorage.setItem('gptmakerAgentId', agentId);
        const badge = document.getElementById('gptmaker-agent-badge');
        if (badge) {
            badge.textContent = `🤖 GPT Maker Agent: ${agentId}`;
            badge.style.display = 'inline-flex';
        }
        showToast(`GPT Maker agent ID ${agentId} vinculado ao Studio!`, "success");
    } else {
        localStorage.removeItem('gptmakerAgentId');
        const badge = document.getElementById('gptmaker-agent-badge');
        if (badge) badge.style.display = 'none';
    }
}

// ============ CYBERCORE STUDIO WORKSPACE ============

async function listStudioFiles() {
    const list = document.getElementById('studio-file-list');
    if (!list) return;

    list.innerHTML = '<div style="opacity: 0.5; text-align: center; padding: 20px;">Lendo workspace...</div>';

    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/files`);
        const data = await resp.json();

        if (data.status === 'success') {
            if (data.files.length === 0) {
                list.innerHTML = '<div style="opacity: 0.3; text-align: center; padding: 20px;">Workspace vazio.</div>';
                return;
            }

            list.innerHTML = data.files.map(f => {
                const icon = getFileIcon(f.ext);
                return `
                    <div class="file-item" onclick="openStudioFile('${f.name}')" style="display: flex; align-items: center; gap: 10px; padding: 8px; cursor: pointer; border-radius: 4px; transition: background 0.2s; margin-bottom: 2px;">
                        <span style="font-size: 14px;">${icon}</span>
                        <div style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #e4e4e7; font-size: 11px;">${f.name}</div>
                        <div style="font-size: 9px; opacity: 0.4; color: var(--text-secondary);">${(f.size / 1024).toFixed(1)}KB</div>
                        <button onclick="event.stopPropagation(); deleteStudioFile('${f.name}')" style="background: transparent; border: none; color: #ef4444; cursor: pointer; opacity: 0.5; font-size: 10px; padding: 4px;">🗑️</button>
                    </div>
                `;
            }).join('');
        } else {
            list.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 20px; font-size: 10px;">Erro: ${data.msg}</div>`;
        }
    } catch (e) {
        list.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px; font-size: 10px;">Studio Offline</div>';
    }
}

function getFileIcon(ext) {
    const icons = {
        'py': '🐍', 'js': '📜', 'html': '🌐', 'css': '🎨', 'json': '📦', 'txt': '📄', 'md': '📝', 'png': '🖼️', 'jpg': '🖼️'
    };
    return icons[ext] || '📄';
}

async function openStudioFile(filename) {
    const editor = document.getElementById('studio-editor');
    const nameEl = document.getElementById('current-file-name');
    const iconEl = document.getElementById('current-file-icon');
    if (!editor || !nameEl) return;

    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/read-file/${filename}`);
        const data = await resp.json();

        if (data.status === 'success') {
            editor.value = data.content;
            nameEl.textContent = filename;
            const ext = filename.split('.').pop();
            iconEl.textContent = getFileIcon(ext);
            showToast(`Arquivo ${filename} aberto.`, "success");
        } else {
            showToast(`Erro ao abrir: ${data.msg}`, "error");
        }
    } catch (e) {
        showToast("Falha ao ler arquivo do backend.", "error");
    }
}

async function saveCurrentFile() {
    const filename = document.getElementById('current-file-name').textContent;
    const content = document.getElementById('studio-editor').value;
    if (filename === 'nenhum arquivo aberto') return showToast("Selecione um arquivo primeiro.", "error");

    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/save-file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, content })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast("Alterações salvas no workspace.", "success");
            listStudioFiles();
        } else {
            showToast(data.msg, "error");
        }
    } catch (e) {
        showToast("Erro de conexão ao salvar.", "error");
    }
}

async function createNewFile() {
    const name = prompt("Nome do novo arquivo (ex: script.js):", "novo_modulo.py");
    if (!name) return;
    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/save-file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: name, content: "// Inicializado pelo CyberCore Studio" })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(`Arquivo ${name} criado.`, "success");
            listStudioFiles();
            openStudioFile(name);
        }
    } catch (e) {
        showToast("Falha ao criar arquivo.", "error");
    }
}

async function deleteStudioFile(filename) {
    if (!confirm(`Deseja remover ${filename} permanentemente?`)) return;
    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        const resp = await fetch(`${baseUrl}/api/studio/delete-file/${filename}`, { method: 'DELETE' });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.msg, "success");
            if (document.getElementById('current-file-name').textContent === filename) closeEditor();
            listStudioFiles();
        }
    } catch (e) {
        showToast("Falha ao deletar.", "error");
    }
}

function closeEditor() {
    document.getElementById('studio-editor').value = "";
    document.getElementById('current-file-name').textContent = "nenhum arquivo aberto";
    document.getElementById('current-file-icon').textContent = "📄";
}

async function buildJavaProject(type) {
    const terminal = document.getElementById('studio-output');
    const body = document.getElementById('studio-terminal-body');
    if (terminal) terminal.style.display = 'block';

    // Obtém contexto do projeto atual se disponível
    const currentProjectName = document.getElementById('pm-project-name-display')?.textContent || "";
    const currentProjectPath = document.getElementById('pm-project-path-display')?.textContent || "";

    const msg = type === 'apk' ? 'Iniciando build de APK assinado...' : 'Iniciando compilação de JAR...';
    if (body) {
        body.innerHTML += `<div style="color: var(--cyan); margin-top: 15px; font-family: 'JetBrains Mono'; font-size: 12px;">[SYSTEM] ${msg}</div>`;
        if (currentProjectName) {
            body.innerHTML += `<div style="color: var(--text-secondary); font-size: 10px; margin-bottom: 10px;">Contexto: Projeto ${currentProjectName} em ${currentProjectPath}</div>`;
        }
        body.scrollTop = body.scrollHeight;
    }

    try {
        const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
        let prompt = type === 'apk' ? "Build and sign APK" : "Compile project to JAR";

        if (currentProjectName) {
            prompt += ` for project "${currentProjectName}" located at "${currentProjectPath}"`;
        }

        const resp = await fetch(`${baseUrl}/api/ai/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent: 'JAVA',
                prompt: prompt,
                uid: 'admin_studio'
            })
        });

        const data = await resp.json();
        if (body) {
            body.innerHTML += `<div style="color: #fff; margin-top: 5px; font-family: 'JetBrains Mono'; font-size: 11px; white-space: pre-wrap;">${data.answer || 'Sem resposta do agente.'}</div>`;
            body.scrollTop = body.scrollHeight;
        }
    } catch (e) {
        showToast("Erro ao solicitar build.", "error");
    }
}

function renderWatchProjects() {
    const container = document.getElementById('watch-projects-list');
    if (!container) return;

    if (connectedProjects.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-secondary); font-size: 12px;">Nenhum projeto sendo monitorado pelo Watch.</div>`;
        return;
    }

    container.innerHTML = connectedProjects.map(p => {
        const health = p.health || {};
        const isOnline = health.status === 'online';
        const isDegraded = health.status === 'degraded';
        const statusClass = isOnline ? 'online' : (isDegraded ? 'degraded' : 'offline');

        // Dados de telemetria estendidos
        const cpu = health.cpu !== undefined ? health.cpu + '%' : '--';
        const ram = health.ram !== undefined ? health.ram + '%' : '--';
        const latency = health.latency_ms ? health.latency_ms + 'ms' : '--';

        const color = isOnline ? '#10b981' : (isDegraded ? '#fbbf24' : '#ef4444');
        const tech = p.tech_stack ? p.tech_stack.join(', ') : (p.framework || 'N/A');

        return `
            <div class="project-watch-card ${statusClass}" style="border-left-color: ${color}; position: relative; overflow: hidden;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <div style="font-weight: 800; font-size: 13px; color: white;">${p.name || p.identifier}</div>
                        <div style="font-size: 9px; color: var(--text-secondary); margin-top: 4px; text-transform: uppercase;">
                            TYPE: ${p.type.toUpperCase()} | STACK: ${tech}
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
                     <button onclick="showPanel('studio'); document.getElementById('studio-prompt').value='Analisar logs do nó ${p.id}'" class="btn-minimal" style="font-size: 8px; padding: 2px 6px;">DEBUG</button>
                     <button onclick="copyToClipboard('${p.token || ''}')" class="btn-minimal" style="font-size: 8px; padding: 2px 6px;">TOKEN</button>
                </div>

                ${isOnline ? '<div class="pulse-ring"></div>' : ''}
            </div>
        `;
    }).join('');
}

function renderGlobalStats() {
    const users = Object.values(rtState.users);
    const totalDebt = users.reduce((acc, u) => acc + parseFloat(u.balance || 0), 0);
    const hits = rtState.config?.stats?.hits || 0;
    const cpm = rtState.config?.cpm || 0.18;
    const dollar = rtState.status?.financial_realtime?.rate || 5.25;

    const revenueBrl = (hits / 1000) * cpm * dollar;
    const netProfit = revenueBrl - totalDebt;
    updateEl('stat-profit-brl-total', `R$ ${revenueBrl.toFixed(2)}`);
    updateEl('stat-users', users.length);
    updateEl('stat-profit-usd', `$ ${(revenueBrl / dollar).toFixed(2)}`);
    updateEl('stat-profit-brl', `R$ ${revenueBrl.toFixed(2)}`);
    updateEl('stat-balance', `R$ ${totalDebt.toFixed(2)}`);
    updateEl('stat-net-profit', `R$ ${netProfit.toFixed(2)}`);
    const netEl = document.getElementById('stat-net-profit');
    if (netEl) netEl.style.color = netProfit >= 0 ? '#10b981' : '#f43f5e';

    // Variação semanal de usuários (compara com criação de conta)
    const weekAgo = Date.now() - 7 * 86400000;
    const weekStart = users.filter(u => (u.createdAt || u.created_at || 0) < weekAgo).length;
    const weekChange = weekStart > 0 ? ((users.length - weekStart) / weekStart) * 100 : 0;
    const weekEl = document.getElementById('stat-users-week');
    if (weekEl) {
        weekEl.textContent = weekChange >= 0 ? `+${weekChange.toFixed(0)}% esta semana` : `${weekChange.toFixed(0)}% esta semana`;
        weekEl.style.color = weekChange >= 0 ? '#10b981' : '#ef4444';
    }
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

    // Suporte para comando direto de script: studio://filename|content
    if (rawCmd.startsWith('studio://')) {
        const parts = rawCmd.replace('studio://', '').split('|');
        if (parts.length >= 2) {
            const filename = parts[0].trim();
            const content = parts.slice(1).join('|').trim();
            userBubble.innerHTML = `<strong>OPERADOR:</strong> [COMANDO STUDIO] Salvar ${filename}<span class="msg-ts">${timeStr}</span>`;
            termList.appendChild(userBubble);

            const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
            try {
                const resp = await fetch(`${baseUrl}/api/studio/save-file`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename, content })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    typeIAResponse(`Arquivo **${filename}** injetado no workspace com sucesso.`, 'nexus');
                    listStudioFiles();
                } else {
                    typeIAResponse(`Erro ao injetar arquivo: ${data.msg}`, 'nexus');
                }
            } catch (e) {
                typeIAResponse("Falha na ponte Studio-Terminal.", 'nexus');
            }
            termList.scrollTop = termList.scrollHeight;
            return;
        }
    }

    userBubble.innerHTML = `<strong>OPERADOR:</strong> ${renderMarkdown(rawCmd)}<span class="msg-ts">${timeStr}</span>`;
    termList.appendChild(userBubble);
    termList.scrollTop = termList.scrollHeight;

    let agentId = 'cmo';
    let backendAgent = 'ORCHESTRATOR';
    if (cmd.includes('saque') || cmd.includes('financeiro')) {
        agentId = 'cfo';
        backendAgent = 'AUDITOR';
    }
    if (cmd.includes('segurança') || cmd.includes('varredura')) {
        agentId = 'coo';
        backendAgent = 'SECURITY';
    }

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
                    agent: backendAgent,
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
                const resp = await fetch(`${CYBERCORE_BACKEND_URL}/api/ai/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prompt: rawCmd,
                        agent: backendAgent,
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

    // Smart Link: Detecta blocos de código e adiciona botão de exportação para Studio
    const codeBlockMatch = text.match(/```(\w*)\n?([\s\S]*?)```/);
    if (codeBlockMatch) {
        const lang = codeBlockMatch[1] || 'txt';
        const code = codeBlockMatch[2].trim();
        const exportBtnId = `export-${Date.now()}`;

        bubble.innerHTML += `
            <div style="margin-top:10px; padding:10px; background: rgba(0,255,194,0.05); border: 1px dashed var(--cyan); border-radius: 4px;">
                <p style="font-size:10px; color: var(--cyan); margin-bottom: 5px;">[SMART LINK] Código detectado. Deseja enviar para o Studio?</p>
                <button id="${exportBtnId}" class="btn-cyber-primary" style="font-size:9px; padding:4px 10px;">[ EXPORTAR PARA WORKSPACE ]</button>
            </div>
        `;

        setTimeout(() => {
            const btn = document.getElementById(exportBtnId);
            if (btn) btn.onclick = async () => {
                const filename = prompt("Nome do arquivo (ex: script.js):", `generated_${Date.now()}.${lang}`);
                if (filename) {
                    const baseUrl = localStorage.getItem('CYBERCORE_BACKEND_URL') || LOCAL_BACKEND;
                    try {
                        const resp = await fetch(`${baseUrl}/api/studio/save-file`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ filename, content: code })
                        });
                        const data = await resp.json();
                        if (data.status === 'success') {
                            showToast(`Exportado: ${filename}`, "success");
                            listStudioFiles();
                        }
                    } catch (e) {
                        showToast("Erro na exportação.", "error");
                    }
                }
            };
        }, 100);
    }

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
    // Apenas atualiza UI neural, não sobrescreve ping real (feito pelo updateWarRoom)
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

    // Monitor de Auditoria em tempo real para Logs do Nexus
    hubDb.ref('agent_data/incoming').limitToLast(5).on('child_added', snap => {
        const data = snap.val();
        if (!data || data.type !== 'telemetry') return;

        // Se estivermos no painel de Auditoria ou Studio, injetar log visual
        const auditLog = document.getElementById('logs-nexus');
        if (auditLog && data.payload) {
            const line = document.createElement('div');
            line.className = 'log-line';
            line.style.borderLeft = '2px solid var(--teal)';
            const time = new Date(data.received_at).toLocaleTimeString();
            line.innerHTML = `<span>[${time}]</span> <strong style="color:var(--teal)">AUDIT:</strong> ${data.payload.uid} sync detectado.`;
            auditLog.appendChild(line);
            if (auditLog.children.length > 20) auditLog.removeChild(auditLog.firstChild);
            auditLog.scrollTop = auditLog.scrollHeight;
        }
    });
}

// ============ AUTH ============

auth.onAuthStateChanged(user => {
    console.log("[AUTH] Estado alterado:", user ? "Logado" : "Deslogado");

    // Remove o loader assim que o Firebase responder
    const loader = document.getElementById('loader');
    if (loader) {
        loader.style.opacity = '0';
        setTimeout(() => loader.remove(), 500);
    }

    if (user) {
        // Se estiver logado, garante que a tela de login suma e o app apareça
        document.getElementById('login-screen').style.display = 'none';
        const app = document.getElementById('hub-app');
        if (app) app.style.display = 'grid';

        // Inicializa sistemas apenas se ainda não foram iniciados
        if (Object.keys(rtState.users).length === 0) {
            initRealTimeSystem();
        }
    } else {
        // Se deslogado, mostra login e esconde app
        document.getElementById('login-screen').style.display = 'flex';
        const app = document.getElementById('hub-app');
        if (app) app.style.display = 'none';
    }
});

let loginInProgress = false;

async function login() {
    const email = document.getElementById('login-email').value.trim();
    const pass = document.getElementById('login-pass').value;
    if (!email || !pass) return showToast('Preencha e-mail e senha.', 'error');

    loginInProgress = true;
    try {
        await auth.signInWithEmailAndPassword(email, pass);
        loginInProgress = false;
        showToast('Acesso Master concedido!', 'success');
    } catch (e) {
        loginInProgress = false;
        console.error('[Admin Login]', e.code, e.message);
        showToast('Erro: Verifique suas credenciais.', 'error');
    }
}

// MODO DE EMERGÊNCIA: Pular Login no Localhost
function bypassLogin() {
    console.log("[DEV] Ativando Bypass de Segurança...");
    document.getElementById('login-screen').style.display = 'none';
    const app = document.getElementById('hub-app');
    if (app) app.style.display = 'grid';
    initRealTimeSystem();
    showToast('MODO DESENVOLVEDOR: Acesso Liberado ⚡', 'info');
}

function logout() { auth.signOut().then(() => location.reload()); }

// ============ SEGURANÇA DE SESSÃO (RELAXADA) ============
// Removido auto-logout por perda de foco para facilitar o desenvolvimento.
window.addEventListener('pagehide', () => {
    if (auth.currentUser) sessionStorage.setItem('cybercore_lock', '1');
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
    const maintCheck = document.getElementById('toggle-maintenance') || document.getElementById('toggle-cinecash-maint');
    if (maintCheck) maintCheck.checked = isMaint;

    const maintStatusText = document.getElementById('maint-firebase-status');
    if (maintStatusText) maintStatusText.innerText = isMaint ? "MODO MANUTENÇÃO ATIVO" : "SISTEMA OPERACIONAL";

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

    const adsToggle = document.getElementById('config-adsEnabled');
    if (adsToggle) adsToggle.checked = rtState.config?.adsEnabled !== false;
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
        'audit-gptmaker-key': merged.gptmakerKey,
        'audit-telegram-token': merged.telegramToken,
        'audit-telegram-chatid': merged.telegramChatId,
        'audit-whatsapp': merged.admin_whatsapp,
        'audit-asaas-key': merged.asaas_key,
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
        'gptmakerKey': document.getElementById('audit-gptmaker-key').value,
        'telegramToken': document.getElementById('audit-telegram-token').value,
        'telegramChatId': document.getElementById('audit-telegram-chatid').value,
        'admin_whatsapp': document.getElementById('audit-whatsapp').value,
        'asaas_key': document.getElementById('audit-asaas-key').value
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
    maintenance: ['Manutenção', 'Modo Manutenção do Sistema'],
    deviceIdSecurity: ['ID Único', 'Segurança de ID Único'],
    production: ['Produção', 'Ambiente de Produção'],
    blockVPN: ['VPN', 'Bloqueio de Proxy/VPN'],
    blockRoot: ['Root', 'Detecção de Root/Jailbreak'],
    deviceLock: ['Device Lock', 'Vínculo de ID Único'],
    autoBan: ['Auto-Ban', 'Banimento Automático Multi-Contas'],
    adsEnabled: ['Anúncios', 'Anúncios no Site']
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

function initProfitChart() {
    const ctx = document.getElementById('profitChart')?.getContext('2d');
    if (!ctx) return;

    const dayNames = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
    const today = new Date().getDay();
    const labels = [];
    for (let i = 6; i >= 0; i--) {
        labels.push(dayNames[(today - i + 7) % 7]);
    }

    window.profitChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Lucro (R$)',
                data: [0, 0, 0, 0, 0, 0, 0],
                backgroundColor: [],
                borderRadius: 6,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `R$ ${parseFloat(ctx.raw || 0).toFixed(2)}`
                    }
                }
            },
            scales: {
                y: {
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#94a3b8', callback: v => 'R$' + v.toFixed(0) }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });

    // Escuta dados reais de lucro dos últimos 7 dias
    hubDb.ref('config/profit_history').on('value', snap => {
        const data = snap.val();
        if (!data || !Array.isArray(data)) return;
        updateProfitChartWithRealData(data);
    });
}

function updateProfitChartWithRealData(data) {
    if (!window.profitChart) return;

    // Agrupa por dia nos últimos 7 dias
    const now = Date.now() / 1000;
    const sevenDaysAgo = now - 7 * 86400;
    const dayBuckets = {};

    for (let i = 0; i < 7; i++) {
        const d = new Date((sevenDaysAgo + i * 86400) * 1000);
        const key = d.toISOString().split('T')[0];
        dayBuckets[key] = 0;
    }

    data.forEach(d => {
        if (!d.t) return;
        const ts = typeof d.t === 'number' ? d.t : d.t;
        if (ts < sevenDaysAgo) return;
        const key = new Date(ts * 1000).toISOString().split('T')[0];
        if (dayBuckets[key] !== undefined) {
            dayBuckets[key] += d.v || 0;
        }
    });

    const values = Object.values(dayBuckets);
    const maxVal = Math.max(...values, 1);

    const colors = values.map(v => {
        const pct = v / maxVal;
        if (pct > 0.7) return '#10b981';
        if (pct > 0.4) return '#22c55e';
        if (pct > 0.1) return '#34d399';
        return '#6ee7b7';
    });

    window.profitChart.data.datasets[0].data = values;
    window.profitChart.data.datasets[0].backgroundColor = colors;
    window.profitChart.update('none');
}

function updateWarRoom() {
    // Atualiza ambos: monitor no painel de projetos + war room legacy
    const strategiesEl = document.getElementById('monitor-strategies') || document.getElementById('warroom-strategies');
    const cmdsEl = document.getElementById('monitor-commands') || document.getElementById('warroom-commands');

    const metricsUrl = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/api/metrics` : '/api/metrics';
    fetch(metricsUrl)
        .then(r => r.json())
        .then(data => {
            // Atualiza Overview Dashboard
            updateEl('tele-ping', `${data.ping || 0}ms`);
            updateEl('tele-cpu', `${data.cpu || 0}%`);
            updateEl('tele-ram', data.ram || '0MB');

            // Atualiza barras de progresso (opcional)
            const pingFill = document.querySelector('.ping-fill');
            if (pingFill) pingFill.style.width = `${Math.min((data.ping / 200) * 100, 100)}%`;
            const cpuFill = document.querySelector('.cpu-fill');
            if (cpuFill) cpuFill.style.width = `${data.cpu || 0}%`;
            const ramFill = document.querySelector('.ram-fill');
            if (ramFill) ramFill.style.width = `${Math.min(parseFloat(data.ram || '0') / 10, 100)}%`;

            if (data.status === 'online') {
                const dot = document.getElementById('python-core-ping');
                if (dot) {
                    dot.style.background = '#10b981';
                    dot.style.boxShadow = '0 0 12px #10b981';
                }
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
    const history = rtState.history || {};
    const userWs = history[uid] || {};
    const w = userWs[wid] || {};
    const user = rtState.users[uid] || {};
    const pixKey = w.pixKey || '';
    const pixType = w.pixType || 'EVP';
    const fullname = w.fullname || user.fullname || user.email || 'Usuário';
    const amount = parseFloat(w.amount || 0);

    document.getElementById('pix-modal-uid').value = uid;
    document.getElementById('pix-modal-wid').value = wid;
    document.getElementById('pix-modal-user').textContent = fullname;
    document.getElementById('pix-modal-amount').textContent = `R$ ${amount.toFixed(2)}`;
    document.getElementById('pix-modal-type').value = pixType;
    document.getElementById('pix-modal-key').value = pixKey;
    document.getElementById('btn-pix-confirmar').disabled = true;
    document.getElementById('btn-pix-confirmar').style.opacity = '0.4';
    document.getElementById('btn-pix-confirmar').style.pointerEvents = 'none';
    document.getElementById('pix-modal-validacao').innerHTML = '';

    document.getElementById('modal-validar-pix').style.display = 'flex';
    validatePixKey();
}

function closePixModal() {
    document.getElementById('modal-validar-pix').style.display = 'none';
}

function getPixValidation(key, type) {
    const cleaned = key.replace(/\s/g, '');
    switch (type) {
        case 'CPF': {
            const digits = cleaned.replace(/\D/g, '');
            if (digits.length === 11) return { valid: true, formatted: digits };
            return { valid: false, msg: `CPF deve ter 11 dígitos (tem ${digits.length})` };
        }
        case 'CNPJ': {
            const digits = cleaned.replace(/\D/g, '');
            if (digits.length === 14) return { valid: true, formatted: digits };
            return { valid: false, msg: `CNPJ deve ter 14 dígitos (tem ${digits.length})` };
        }
        case 'EMAIL': {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (emailRegex.test(cleaned)) return { valid: true, formatted: cleaned };
            return { valid: false, msg: 'E-mail inválido' };
        }
        case 'PHONE': {
            const digits = cleaned.replace(/\D/g, '');
            if (digits.length >= 10 && digits.length <= 13) return { valid: true, formatted: digits };
            return { valid: false, msg: `Telefone deve ter 10 a 13 dígitos (tem ${digits.length})` };
        }
        case 'EVP': {
            const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
            const base64Regex = /^[A-Za-z0-9+/=]{32,}$/;
            if (uuidRegex.test(cleaned) || base64Regex.test(cleaned)) return { valid: true, formatted: cleaned };
            return { valid: false, msg: 'Chave aleatória inválida (formato UUID ou base64)' };
        }
        default:
            return { valid: false, msg: 'Tipo de chave desconhecido' };
    }
}

function validatePixKey() {
    const key = document.getElementById('pix-modal-key').value.trim();
    const type = document.getElementById('pix-modal-type').value;
    const result = getPixValidation(key, type);
    const el = document.getElementById('pix-modal-validacao');
    const btn = document.getElementById('btn-pix-confirmar');

    if (!key) {
        el.innerHTML = '<span style="color:var(--text-muted);">Digite a chave PIX</span>';
        btn.disabled = true;
        btn.style.opacity = '0.4';
        btn.style.pointerEvents = 'none';
        return;
    }

    if (result.valid) {
        el.innerHTML = `<span style="color:#10b981;">✅ Chave ${type} válida</span>`;
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
    } else {
        el.innerHTML = `<span style="color:#ef4444;">❌ ${result.msg}</span>`;
        btn.disabled = true;
        btn.style.opacity = '0.4';
        btn.style.pointerEvents = 'none';
    }
}

function confirmarTransferencia() {
    const uid = document.getElementById('pix-modal-uid').value;
    const wid = document.getElementById('pix-modal-wid').value;
    const key = document.getElementById('pix-modal-key').value.trim();
    const type = document.getElementById('pix-modal-type').value;

    const result = getPixValidation(key, type);
    if (!result.valid) {
        showToast('❌ Chave PIX inválida para o tipo selecionado.', 'error');
        return;
    }

    const url = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/payments/approve/${wid}` : `/payments/approve/${wid}`;

    closePixModal();
    showToast('🚀 Iniciando auditoria e liquidação...', 'info');

    fetch(url, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('✅ Liquidação confirmada via Asaas!', 'success');
            } else {
                showToast(`❌ Falha: ${data.msg}`, 'error');
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

async function generateAIReport() {
    showToast("Gerando relatório neural...", "info");

    const metricsUrl = CYBERCORE_BACKEND_URL ? `${CYBERCORE_BACKEND_URL}/api/metrics` : '/api/metrics';
    let metrics = {};
    try {
        const r = await fetch(metricsUrl);
        metrics = await r.json();
    } catch {}

    const users = rtState.users || {};
    const history = rtState.history || {};
    const config = rtState.config || {};
    const neural = rtState.neural || {};
    const totalUsers = Object.keys(users).length;
    const activeUsers = Object.values(users).filter(u => u.status === 'active' || !u.status).length;
    const pendingWithdrawals = Object.values(history).reduce((s, ws) =>
        s + Object.values(ws).filter(w => w.status === 'pending').length, 0);
    const totalBalance = Object.values(users).reduce((s, u) => s + (parseFloat(u.balance) || 0), 0);
    const totalAds = Object.values(users).reduce((s, u) => s + (parseInt(u.videosWatched) || 0), 0);
    const cpm = config.cpm || 0.18;
    const dollar = neural.dollar_rate || 5.0;
    const hits = config.stats?.hits || neural.total_hits || 0;
    const revenue = ((hits / 1000) * cpm * dollar).toFixed(2);

    const lines = [
        "RELATÓRIO DE MONITORAMENTO CYBERCORE IA:",
        `📡 Ping: ${metrics.ping || 0}ms | CPU: ${metrics.cpu || 0}% | RAM: ${metrics.ram || '0MB'}`,
        `👥 Usuários: ${totalUsers} total | ${activeUsers} ativos`,
        `💰 Saldo total: R$ ${totalBalance.toFixed(2)}`,
        `📊 Anúncios processados: ${totalAds.toLocaleString()}`,
        `🔄 Saques pendentes: ${pendingWithdrawals}`,
        `📈 Receita projetada: R$ ${revenue}`,
        `📉 Dívida total: R$ ${metrics.total_debt || 0}`,
        `✅ Status: Operacional | Integridade: 99.8%`,
        `🕒 ${new Date().toLocaleString('pt-BR')}`
    ];

    typeIAResponse(lines.join('\n'), 'nexus');
    showPanel('terminal');
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

function approveAllWithdrawals() {
    if (!confirm("Aprovar TODOS os saques pendentes?")) return;
    fetch(`${CYBERCORE_BACKEND_URL}/process-all-payments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    }).then(r => r.json()).then(d => {
        showToast(d.message || "Saques processados!", "success");
    }).catch(() => showToast("Falha ao processar saques.", "error"));
}

// ============ INTELIGÊNCIA DE PROJETO ============
let currentProjectType = 'website';
let lastAnalysisResult = null;
let connectedProjects = [];

function selectType(el) {
    document.querySelectorAll('.type-card').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    currentProjectType = el.dataset.type;

    // Atualiza o label do input se necessário
    const labels = {
        website: 'URL DO SITE',
        android: 'PACOTE OU NOME DO APP',
        api: 'URL DA API',
        local: 'IDENTIFICADOR LOCAL'
    };
    const labelEl = document.querySelector('.intel-col:nth-child(2) label');
    if (labelEl) labelEl.textContent = labels[currentProjectType];

    // Oculta output de análise anterior
    document.getElementById('ai-analysis-output').style.display = 'none';
    lastAnalysisResult = null;
}

async function analisarProjetoAI() {
    const identifier = document.getElementById('ai-project-url').value.trim();
    if (!identifier) return showToast("Informe a URL ou identificador do projeto.", "error");

    const btn = document.querySelector('.btn-analyze-ai');
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span> ANALISANDO...';

    try {
        const resp = await fetch(`${CYBERCORE_BACKEND_URL}/api/project/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: currentProjectType, identifier })
        });
        const res = await resp.json();

        if (res.status === 'success' || res.status === 'partial') {
            const data = res.data;
            lastAnalysisResult = {
                type: currentProjectType,
                identifier,
                data: data,
                name: document.getElementById('ai-project-name').value.trim() || identifier.split('//').pop().split('/')[0]
            };

            // Atualiza UI de resultados
            document.getElementById('res-framework').textContent = data.framework || '—';
            document.getElementById('res-tech').textContent = currentProjectType.toUpperCase();

            document.getElementById('ai-analysis-output').style.display = 'block';
            showToast("Análise concluída!", "success");

            // Se for sistema local, mostra o comando de instalação
            if (currentProjectType === 'local') {
                showLocalInstallCommand();
            }

            // Adiciona automaticamente o botão para conectar após análise
            const output = document.getElementById('ai-analysis-output');
            if (output && !document.getElementById('btn-connect-now')) {
                const connBtn = document.createElement('button');
                connBtn.id = 'btn-connect-now';
                connBtn.className = 'btn-premium holo-shimmer';
                connBtn.style = 'margin-top: 20px; width: 100%; padding: 15px; border-radius: 12px; font-weight: 800;';
                connBtn.textContent = 'CONECTAR AO HUB AGORA';
                connBtn.onclick = addCurrentProject;
                output.appendChild(connBtn);
            }
        }
    } catch (e) {
        showToast("Erro ao conectar com o motor de análise.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

async function showLocalInstallCommand() {
    try {
        const resp = await fetch(`${CYBERCORE_BACKEND_URL}/api/local/install-command`);
        const data = await resp.json();
        if (data.status === 'success') {
            typeIAResponse(`Para conectar seu **Sistema Local**, execute este comando no terminal do servidor alvo:\n\n \`\`\`bash\n${data.command}\n\`\`\``, 'nexus');
        }
    } catch (e) {}
}

function renderProjects() {
    const tbody = document.getElementById('projects-table-body');
    if (!tbody) return;

    if (!connectedProjects || connectedProjects.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; opacity:0.3; padding:40px;">Nenhum projeto conectado.</td></tr>';
        return;
    }

    tbody.innerHTML = connectedProjects.map(p => `
        <tr>
            <td>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div class="proj-icon-circle">${p.type === 'website' ? '🌐' : p.type === 'android' ? '🤖' : p.type === 'api' ? '☁️' : '🖥️'}</div>
                    <div>
                        <div style="font-weight: 800; color: #fff;">${p.name || p.identifier}</div>
                        <small style="opacity: 0.5;">${p.identifier}</small>
                    </div>
                </div>
            </td>
            <td><span class="type-tag ${p.type}">${p.type.toUpperCase()}</span></td>
            <td>
                <span class="status-tag ${p.health?.status || 'offline'}">
                    ● ${p.health?.status === 'online' ? 'Online' : p.health?.status === 'degraded' ? 'Degradado' : 'Offline'}
                </span>
            </td>
            <td>${p.health?.latency_ms ? p.health.latency_ms + 'ms' : '--'}</td>
            <td>
                <div style="display:flex; align-items:center; gap:8px;">
                    <div style="flex:1; height:4px; background:rgba(255,255,255,0.1); border-radius:2px;">
                        <div style="width: ${p.health?.status === 'online' ? '98%' : '0%'}; height:100%; background:var(--success); border-radius:2px;"></div>
                    </div>
                    <small>${p.health?.status === 'online' ? '98%' : '0%'}</small>
                </div>
            </td>
            <td><small>${p.health?.last_checked ? new Date(p.health.last_checked).toLocaleTimeString() : 'Pendente'}</small></td>
            <td>
                <button class="btn-table-action" onclick="removeProject('${p.id}')">REMOVER</button>
            </td>
        </tr>
    `).join('');
}

function removeProject(id) {
    if (!confirm("Remover este projeto do monitoramento?")) return;
    fetch(`${CYBERCORE_BACKEND_URL}/api/project/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    }).then(() => showToast("Projeto removido.", "info"));
}

function addCurrentProject() {
    if (!lastAnalysisResult) return showToast("Analise um projeto primeiro.", "error");

    const exists = connectedProjects.find(p =>
        p.identifier === lastAnalysisResult.identifier && p.type === lastAnalysisResult.type
    );
    if (exists) return showToast("Este projeto já está conectado.", "error");

    const projectId = 'PRJ' + Date.now().toString(36).toUpperCase();
    const projectData = {
        id: projectId,
        name: lastAnalysisResult.name,
        type: lastAnalysisResult.type,
        identifier: lastAnalysisResult.identifier,
        framework: lastAnalysisResult.data?.framework || '—',
        addedAt: new Date().toISOString()
    };

    fetch(`${CYBERCORE_BACKEND_URL}/api/project/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: projectId, data: projectData })
    })
    .then(r => r.json())
    .then(resp => {
        if (resp.status === 'success') {
            showToast("Projeto conectado com sucesso!", "success");
            document.getElementById('ai-analysis-output').style.display = 'none';
        } else {
            showToast("Erro ao salvar projeto.", "error");
        }
    });
}

function renderProjects() {
    const container = document.getElementById('projects-list');
    const badge = document.getElementById('projects-count-badge');
    if (!container) return;

    if (connectedProjects.length === 0) {
        container.innerHTML = `<div style="text-align: center; padding: 40px 20px; color: var(--text-secondary); font-size: 13px;">Nenhum projeto conectado. Use o conector acima para adicionar.</div>`;
        if (badge) badge.textContent = '0 ATIVOS';
        return;
    }

    const onlineCount = connectedProjects.filter(p => p.health?.status === 'online').length;
    if (badge) badge.textContent = onlineCount + '/' + connectedProjects.length + ' ONLINE';

    container.innerHTML = connectedProjects.map(p => {
        const icons = { website: '🌐', android: '📱', api: '⚡', local: '💻' };
        const icon = icons[p.type] || '📦';
        const typeClass = p.type || 'website';
        const health = p.health || {};
        const isOnline = health.status === 'online';
        const isDegraded = health.status === 'degraded';
        const dotColor = isOnline ? '#10b981' : isDegraded ? '#fbbf24' : '#ef4444';
        const statusLabel = isOnline ? 'Online' : isDegraded ? 'Degradado' : 'Offline';
        const latency = health.latency_ms ? health.latency_ms + 'ms' : '';
        const httpStatus = health.http_status || '';
        const lastCheck = health.last_checked
            ? new Date(health.last_checked).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
            : '';
        return `
            <div class="project-card-mini">
                <div style="display: flex; align-items: center; gap: 14px; flex: 1; min-width: 0;">
                    <div class="proj-icon ${typeClass}">${icon}</div>
                    <div style="min-width: 0; flex: 1;">
                        <div style="font-weight: 700; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${p.identifier}</div>
                        <div style="display: flex; gap: 8px; margin-top: 4px; font-size: 0.65rem; color: var(--text-secondary); flex-wrap: wrap;">
                            <span>${p.framework || '—'}</span>
                            <span class="data-dot" style="background: ${dotColor};"></span>
                            <span style="color: ${dotColor};">${statusLabel}</span>
                            ${latency ? `<span>⏱ ${latency}</span>` : ''}
                            ${httpStatus ? `<span>HTTP ${httpStatus}</span>` : ''}
                            ${lastCheck ? `<span>🕐 ${lastCheck}</span>` : ''}
                        </div>
                    </div>
                </div>
                <button class="btn-minimal" onclick="removeProject('${p.id}')" style="border-color: rgba(239,68,68,0.3); color: #ef4444; padding: 6px 12px; font-size: 0.7rem; flex-shrink: 0;">REMOVER</button>
            </div>
        `;
    }).join('');
}

function removeProject(id) {
    if (!confirm("Remover este projeto do painel?")) return;
    connectedProjects = connectedProjects.filter(p => p.id !== id);
    renderProjects();
    fetch(`${CYBERCORE_BACKEND_URL}/api/project/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    })
    .then(r => r.json())
    .then(resp => {
        showToast(resp.status === 'success' ? "Projeto removido." : "Erro ao remover.", resp.status === 'success' ? "info" : "error");
    })
    .catch(() => showToast("Erro de conexão.", "error"));
}

function migrateLocalProjectsToFirebase() {
    if (Object.keys(rtState.neural.nodes || {}).length > 0) return;
    try {
        const saved = localStorage.getItem('cybercore_projects');
        if (!saved) return;
        const local = JSON.parse(saved);
        if (!local.length) return;
        let migrated = 0;
        local.forEach(p => {
            const id = p.id || Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
            const data = {
                type: p.type || 'website',
                identifier: p.identifier,
                framework: p.framework || '—',
                ambiente: p.ambiente || '—',
                addedAt: p.addedAt || new Date().toISOString()
            };
            fetch(`${CYBERCORE_BACKEND_URL}/api/project/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, data })
            }).catch(() => {});
            migrated++;
        });
        localStorage.removeItem('cybercore_projects');
        console.log('[PROJETOS] Migrados do localStorage para Firebase:', migrated);
    } catch (e) { /* ignore */ }
}

function handleApkUpload(input) {
    const file = input.files[0];
    if (!file) return;
    showToast("APK recebido: " + file.name + " (" + (file.size / 1024 / 1024).toFixed(1) + " MB)", "info");
    document.getElementById('project-package').value = file.name.replace('.apk', '');
}
