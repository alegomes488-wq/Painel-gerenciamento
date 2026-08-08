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

function toggleUserBan(uid, shouldBan) {
    const status = shouldBan ? 'banido' : 'ativo';
    hubDb.ref(`users/${uid}/status`).set(status)
        .then(() => showToast(`Usuário ${status}.`, 'info'))
        .catch(() => showToast('Erro ao atualizar status.', 'error'));
}
