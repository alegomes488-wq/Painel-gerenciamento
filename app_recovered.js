// ============ CONFIGURA├ç├âO FIREBASE ============
const hubConfig = {
    apiKey: "AIzaSyDpB0dNIjeS6KnFDt057rbm0QGrcX3AvJE",
    authDomain: "playearn-b001b.firebaseapp.com",
    databaseURL: "https://playearn-b001b-default-rtdb.firebaseio.com",
    projectId: "playearn-b001b"
};

if (!firebase.apps.length) firebase.initializeApp(hubConfig);
const auth = firebase.auth();
const hubDb = firebase.database();

let rtState = {
    users: {},
    config: {},
    withdrawals: {},
    devices: {},
    logs: {}
};

let profitChart = null;

// ============ CONTROLES DE INTERFACE ============
function showPanel(panelId) {
    document.querySelectorAll('.panel-view').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('panel-' + panelId);

    if (target) {
        target.classList.add('active');
        const titles = {
            'overview': 'Hub de An├ílise',
            'projects': 'Sistemas & N├│s',
            'users': 'Banco de Dados',
            'saques': 'Gateway de Pagamentos',
            'audit': 'Auditoria Financeira'
        };
        document.getElementById('current-panel-name').innerText = titles[panelId] || 'M├│dulo Ativo';
    } else {
        document.getElementById('panel-placeholder').classList.add('active');
    }

    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = Array.from(document.querySelectorAll('.nav-btn')).find(btn => btn.getAttribute('onclick')?.includes(`'${panelId}'`));
    if (activeBtn) activeBtn.classList.add('active');
}

function showToast(msg, type = 'info') {
    const t = document.getElementById('toast');
    if(!t) return;
    t.textContent = msg;
    t.className = `toast ${type} show`;
    setTimeout(() => { t.className = 'toast'; }, 3000);
}

// ============ SINCRONIZA├ç├âO EM TEMPO REAL ============
function initRealTimeSystem() {
    const loader = document.getElementById('loader');
    if(loader) {
        setTimeout(() => {
            loader.style.opacity = '0';
            setTimeout(() => loader.style.display = 'none', 500);
        }, 1500);
    }

    hubDb.ref('users').on('value', snap => {
        rtState.users = snap.val() || {};
        renderGlobalStats();
    });

    hubDb.ref('config').on('value', snap => {
        rtState.config = snap.val() || {};
        updateSystemInterface();
    });

    hubDb.ref('devices').on('value', snap => {
        rtState.devices = snap.val() || {};
        renderUsersTable();
    });

    hubDb.ref('withdrawals').on('value', snap => {
        rtState.withdrawals = snap.val() || {};
        renderWithdrawalsTable();
        checkNewWithdrawals();
    });

    hubDb.ref('logs').on('value', snap => {
        rtState.logs = snap.val() || {};
        renderLogsTable();
    });
}

// ============ GR├üFICO DE CRESCIMENTO (AUDITORIA) ============
function initOrUpdateChart() {
    const ctx = document.getElementById('profitChart');
    if (!ctx) return;

    const hits = rtState.config?.stats?.hits || 0;
    const cpm = parseFloat(rtState.config?.cpm || 0.23);

    const dailyData = [
        (hits * 0.05).toFixed(0),
        (hits * 0.08).toFixed(0),
        (hits * 0.12).toFixed(0),
        (hits * 0.15).toFixed(0),
        (hits * 0.18).toFixed(0),
        (hits * 0.20).toFixed(0),
        (hits * 0.22).toFixed(0)
    ].map(h => (h / 1000 * cpm * 5.15).toFixed(2));

    if (profitChart) {
        profitChart.data.datasets[0].data = dailyData;
        profitChart.update();
    } else {
        profitChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: ['6d atr├ís', '5d atr├ís', '4d atr├ís', '3d atr├ís', '2d atr├ís', 'Ontem', 'Hoje'],
                datasets: [{
                    label: 'Lucro (R$)',
                    data: dailyData,
                    borderColor: '#7c3aed',
                    backgroundColor: 'rgba(124, 58, 237, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: '#7c3aed'
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
}

// ============ LOGS DE SEGURAN├çA (ANTI-FRAUDE) ============
function renderLogsTable() {
    const tbody = document.getElementById('logs-table-body');
    if (!tbody) return;

    const logEntries = Object.entries(rtState.logs).reverse();
    let html = '';

    logEntries.slice(0, 50).forEach(([id, log]) => {
        const date = new Date(parseInt(id)).toLocaleString('pt-BR');
        const typeLabel = log.type === 'SUSPEITA_FRAUDE' ? 'ÔÜá´©Å TENTATIVA FRAUDE' : '­ƒøí´©Å SISTEMA';
        const color = log.type === 'SUSPEITA_FRAUDE' ? '#ff4d4d' : '#94a3b8';

        html += `
            <tr>
                <td style="font-size: 11px;">${date}</td>
                <td><strong>${log.userName || 'Admin'}</strong><br><small>${log.uid || 'Master'}</small></td>
                <td style="color: ${color}; font-weight: 600;">${typeLabel}</td>
                <td><small>${log.message || 'Atividade padr├úo'}</small></td>
            </tr>
        `;
    });

    tbody.innerHTML = html || '<tr><td colspan="4" style="text-align:center; padding: 40px;">Nenhum log detectado.</td></tr>';
}

// ============ NOTIFICA├ç├òES WHATSAPP ============
let lastWithdrawCount = -1;

function checkNewWithdrawals() {
    const withdraws = Object.values(rtState.withdrawals).filter(w => w.status === 'pending');
    if (lastWithdrawCount === -1) { lastWithdrawCount = withdraws.length; return; }
    if (withdraws.length > lastWithdrawCount) {
        const latest = withdraws[withdraws.length - 1];
        showWithdrawAlert(latest);
    }
    lastWithdrawCount = withdraws.length;
}

function showWithdrawAlert(w) {
    const phone = rtState.config?.adminPhone;
    if (!phone) return;
    const msg = `­ƒÜÇ *NOVA SOLICITA├ç├âO DE SAQUE*\n\n­ƒæñ Usu├írio: ${w.userName}\n­ƒÆ░ Valor: R$ ${parseFloat(w.amount).toFixed(2)}\n­ƒöæ Chave PIX: ${w.pixKey}`;
    const waUrl = `https://wa.me/${phone}?text=${encodeURIComponent(msg)}`;
    showToast(`Novo saque de R$ ${w.amount}!`, 'success');
    const notification = document.createElement('div');
    notification.innerHTML = `<div style="padding: 15px; background: #25d366; color: white; border-radius: 12px; position: fixed; bottom: 20px; right: 20px; z-index: 10000; box-shadow: 0 10px 30px rgba(0,0,0,0.3); display: flex; align-items: center; gap: 10px; cursor: pointer;" onclick="window.open('${waUrl}', '_blank')"><span>­ƒÆ¼</span><div><strong>Novo Saque!</strong><br><small>Ver no WhatsApp</small></div></div>`;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 8000);
}

// ============ GEST├âO FINANCEIRA (SAQUES PIX) ============
function renderWithdrawalsTable() {
    const tbody = document.getElementById('withdrawals-table-body');
    const totalEl = document.getElementById('total-pending-payout');
    if (!tbody) return;

    let html = '';
    let totalPendente = 0;

    const withdrawEntries = Object.entries(rtState.withdrawals);

    // Filtra apenas os pendentes
    const pendentes = withdrawEntries.filter(([id, w]) => w.status === 'pending');

    pendentes.forEach(([id, w]) => {
        const amount = parseFloat(w.amount || 0);
        totalPendente += amount;

        html += `
            <tr>
                <td>${w.userName || 'Usu├írio'}<br><small style="font-size:9px;">${w.uid?.substring(0,8)}</small></td>
                <td><span class="pix-badge">${w.pixType?.toUpperCase()}</span><br><strong>${w.pixKey}</strong></td>
                <td>R$ ${amount.toFixed(2)}</td>
                <td><span class="status-pill pending">PENDENTE</span></td>
                <td>
                    <button class="btn-table-action" onclick="approveWithdrawal('${id}')" style="background: #4ade80; color: #064e3b;">Aprovar & Pago</button>
                    <button class="btn-table-action" onclick="cancelWithdrawal('${id}')" style="margin-left:5px; background: #ff4d4d; color: #450a0a;">X</button>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html || '<tr><td colspan="5" style="text-align:center; padding: 40px;">Tudo limpo! Nenhum saque pendente.</td></tr>';
    if(totalEl) totalEl.innerText = `R$ ${totalPendente.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
}

async function approveWithdrawal(id) {
    if(confirm('Confirmar que o PIX j├í foi enviado para o usu├írio?')) {
        await hubDb.ref(`withdrawals/${id}/status`).set('paid');
        showToast('Pagamento registrado!', 'success');
    }
}

async function cancelWithdrawal(id) {
    if(confirm('Deseja recusar este saque? O valor voltar├í para an├ílise.')) {
        await hubDb.ref(`withdrawals/${id}`).remove();
        showToast('Saque cancelado.', 'info');
    }
}

function renderGlobalStats() {
    let totalUsers = 0;
    let totalBalance = 0;
    let cineHits = 0;

    if (rtState.users) {
        const usersList = Object.values(rtState.users);
        totalUsers = usersList.length;
        totalBalance = usersList.reduce((sum, u) => sum + (parseFloat(u.balance) || 0), 0);
        renderUsersTable();
    }

    cineHits = rtState.config?.stats?.hits || 0;

    // L├¬ as configura├º├Áes de Auditoria do banco (com valores padr├úo)
    const baseProfit = parseFloat(rtState.config?.baseProfit || 0.03); // Padr├úo dos seus $0.03
    const cpm = parseFloat(rtState.config?.cpm || 0.23); // Padr├úo do seu print

    // C├ílculo: Lucro dos Novos Hits + O que voc├¬ j├í tinha
    const newProfitUSD = (cineHits / 1000) * cpm;
    const profitUSD = baseProfit + newProfitUSD;
    const profitBRL = profitUSD * 5.15; // C├ómbio atualizado

    updateValueWithAnim('stat-users', totalUsers);
    updateValueWithAnim('stat-balance', `R$ ${totalBalance.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`);
    updateValueWithAnim('stat-hits', cineHits.toLocaleString('pt-BR'));

    // Atualiza os novos campos de Auditoria
    updateValueWithAnim('stat-profit-usd', `$ ${profitUSD.toFixed(3)}`);
    updateValueWithAnim('stat-profit-brl', `R$ ${profitBRL.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`);

    // Preenche os inputs no menu Auditoria para voc├¬ poder alterar depois
    const elBase = document.getElementById('audit-base-profit');
    const elCpm = document.getElementById('audit-cpm');
    if(elBase && !elBase.matches(':focus')) elBase.value = baseProfit;
    if(elCpm && !elCpm.matches(':focus')) elCpm.value = cpm;
}

function updateValueWithAnim(id, value) {
    const el = document.getElementById(id);
    if(el) el.innerText = value;
}

// ============ GEST├âO DE USU├üRIOS (TABELA COM ANTI-FRAUDE) ============
function renderUsersTable(filter = '') {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;

    const usersEntries = Object.entries(rtState.users);
    let html = '';

    usersEntries.forEach(([uid, user]) => {
        const email = user.email || 'Usu├írio Sem E-mail';
        const balance = parseFloat(user.balance || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

        // Verifica status do dispositivo
        const deviceId = user.deviceId || uid; // Fallback para UID se deviceId n├úo existir
        const isBanned = rtState.devices[deviceId]?.banned === true;
        const securityStatus = isBanned
            ? '<span style="color: #ff4d4d; font-weight: 800;">­ƒÜ½ BANIDO</span>'
            : '<span style="color: #00ff95; font-weight: 800;">­ƒøí´©Å LIMPO</span>';

        if (filter && !uid.toLowerCase().includes(filter.toLowerCase()) && !email.toLowerCase().includes(filter.toLowerCase())) return;

        html += `
            <tr>
                <td><span class="uid-cell">${uid}</span><br><small style="font-size:9px; color:var(--text-secondary)">ID: ${deviceId.substring(0,10)}...</small></td>
                <td>${email}<br>${securityStatus}</td>
                <td class="balance-cell">${balance}</td>
                <td>
                    <button class="btn-table-action" onclick="editUserBalance('${uid}', '${user.balance || 0}')">Saldo</button>
                    <button class="btn-table-action" onclick="toggleDeviceBan('${deviceId}', ${isBanned})" style="margin-left: 5px; background: ${isBanned ? '#00ff95' : '#ff4d4d'}">
                        ${isBanned ? 'Desbanir' : 'Banir Hardware'}
                    </button>
                    <button class="btn-table-action" onclick="deleteUser('${uid}')" style="margin-left: 5px; opacity: 0.5;">Excluir</button>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html || '<tr><td colspan="4" style="text-align:center; padding: 40px;">Nenhum registro encontrado.</td></tr>';
}

function filterUsers(val) { renderUsersTable(val); }

async function toggleDeviceBan(deviceId, currentlyBanned) {
    const action = currentlyBanned ? 'DESBANIR' : 'BANIR PERMANENTEMENTE';
    if (confirm(`Deseja ${action} este hardware? O usu├írio n├úo conseguir├í acessar nem com outras contas.`)) {
        try {
            await hubDb.ref(`devices/${deviceId}/banned`).set(!currentlyBanned);
            showToast(currentlyBanned ? 'Hardware Liberado!' : 'Hardware Banido!', 'success');
        } catch (e) {
            showToast('Erro ao processar banimento.', 'error');
        }
    }
}

async function editUserBalance(uid, currentBalance) {
    const newBalance = prompt(`Novo saldo para o usu├írio ${uid}:`, currentBalance);
    if (newBalance !== null) {
        await hubDb.ref(`users/${uid}/balance`).set(parseFloat(newBalance));
        showToast('Saldo atualizado!', 'success');
    }
}

async function deleteUser(uid) {
    if (confirm(`Excluir usu├írio ${uid} do banco de dados?`)) {
        await hubDb.ref(`users/${uid}`).remove();
        showToast('Usu├írio removido!', 'success');
    }
}

// ============ CONTROLES DE SISTEMA ============
function toggleSystem(sysId, status) {
    hubDb.ref(`config/active`).set(status)
        .then(() => showToast(`Sistema CineCash ${status ? 'Ativado' : 'Desativado'}`, 'success'));
}

function updateSystemConfig(sysId, key, value) {
    hubDb.ref(`config/${key}`).set(value)
        .then(() => showToast('Configura├º├úo salva!', 'success'));
}

function updateSystemInterface() {
    const status = rtState.config?.active;
    const maintenance = rtState.config?.maintenance;
    const deviceLock = rtState.config?.deviceLock;

    // Atualiza Badges e Bot├Áes
    const elStatus = document.getElementById('cinecash-status');
    const elMaint = document.getElementById('cinecash-maintenance');
    const elDeviceLock = document.getElementById('security-device-lock');
    const badge = document.getElementById('cinecash-badge');

    if (elStatus) elStatus.checked = status !== false;
    if (elMaint) elMaint.checked = maintenance === true;

    // Seguran├ºa de ID ├Ünico: Ativa por padr├úo se n├úo houver valor no banco
    if (elDeviceLock) elDeviceLock.checked = deviceLock !== false;

    // L├│gica de Cores do Badge
    if (badge) {
        if (status === false) {
            badge.innerText = 'ÔØî OFFLINE';
            badge.className = 'sys-badge offline';
        } else if (maintenance === true) {
            badge.innerText = '­ƒøá´©Å MANUTEN├ç├âO';
            badge.className = 'sys-badge maintenance';
        } else {
            badge.innerText = 'Ô£à NODE ATIVO';
            badge.className = 'sys-badge active';
        }
    }
}

// ============ AUTENTICA├ç├âO ============
auth.onAuthStateChanged(user => {
    const hubApp = document.getElementById('hub-app');
    const loginScreen = document.getElementById('login-screen');
    if (user) {
        if(loginScreen) loginScreen.style.display = 'none';
        if(hubApp) hubApp.style.display = 'flex';
        document.getElementById('user-display-name').innerText = user.email.split('@')[0].toUpperCase();
        initRealTimeSystem();
    } else {
        if(hubApp) hubApp.style.display = 'none';
        if(loginScreen) loginScreen.style.display = 'flex';
    }
});

document.getElementById('btn-login')?.addEventListener('click', async () => {
    const email = document.getElementById('login-email').value;
    const pass = document.getElementById('login-pass').value;
    try { await auth.signInWithEmailAndPassword(email, pass); } catch (e) { showToast('Erro no acesso.', 'error'); }
});

function logout() { auth.signOut().then(() => location.reload()); }

// ============ CONTROLES DE INTERFACE RETR├üTIL ============
function toggleCollapseSidebar() {
    const sidebar = document.getElementById('sidebar');
    const icon = document.getElementById('collapse-icon');
    const isCollapsed = sidebar.classList.toggle('collapsed');

    if (icon) icon.innerText = isCollapsed ? 'ÔûÂ' : 'ÔùÇ';
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('active');
}

// Fecha o sidebar ao clicar em um menu no mobile
document.addEventListener('click', (e) => {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('mobile-menu-btn');
    if (window.innerWidth <= 768 && sidebar.classList.contains('active')) {
        if (!sidebar.contains(e.target) && !btn.contains(e.target)) {
            sidebar.classList.remove('active');
        }
    }
});
