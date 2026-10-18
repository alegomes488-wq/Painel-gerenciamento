function renderUsersTable() {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;

    tbody.innerHTML = Object.entries(rtState.users).map(([uid, u]) => `
        <tr>
            <td><code style="font-size:10px;">${escapeHtml(uid)}</code></td>
            <td><strong>${escapeHtml(u.email || 'N/A')}</strong></td>
            <td><span class="status-tag online">● Ativo</span></td>
            <td>R$ ${parseFloat(u.balance || 0).toFixed(2)}</td>
            <td>
                <button class="btn-table-action" onclick="toggleUserBan('${uid}', ${u.status !== 'banido'})">BANIR</button>
            </td>
        </tr>
    `).join('');
}

// TAREFA 2.2 (f): passou a chamar o endpoint backend /api/admin/ban em vez de
// escrever direto no RTDB. Assim o backend revoga claim/tokens e loga auditoria.
async function toggleUserBan(uid, shouldBan) {
    const action = shouldBan ? 'ban' : 'unban';
    try {
        if (!auth?.currentUser) throw new Error('Não autenticado');
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/admin/ban`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${idToken}`
            },
            body: JSON.stringify({ uid, action, reason: 'Painel admin' })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            throw new Error(data.detail || `HTTP ${resp.status}`);
        }
        showToast(`Usuário ${action === 'ban' ? 'banido' : 'reativado'}.`, 'info');
    } catch (e) {
        showToast('Erro ao atualizar status: ' + (e.message || e), 'error');
    }
}
