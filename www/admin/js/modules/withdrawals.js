/**
 * =========================================================
 *  Módulo: Saques PIX — Painel Admin
 *  Integrado com SecOps Sentinel AI para análise de risco
 * =========================================================
 */

// ─────────────────────────────────────────────
//  Renderiza a tabela de saques pendentes com scores de risco
// ─────────────────────────────────────────────
function renderWithdrawalsTable() {
    const tbody = document.getElementById('withdrawals-table-body');
    if (!tbody) return;

    const pendentes = rtState.pending_withdrawals || {};
    const entries = Object.entries(pendentes);

    if (entries.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align:center;padding:40px;color:var(--text-secondary);">
                    <div style="font-size:24px;margin-bottom:8px;">✅</div>
                    Nenhum saque pendente no momento.
                </td>
            </tr>`;
        const totalEl = document.getElementById('total-pendente-display');
        if (totalEl) totalEl.textContent = 'R$ 0,00';
        return;
    }

    // Renderiza a tabela inicialmente com badges "analisando..."
    tbody.innerHTML = entries.map(([wid, w]) => {
        const platform = escapeHtml(w.platform || '🌐 SITE');
        return `
            <tr id="wd-row-${wid}">
                <td>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <div style="width:32px;height:32px;border-radius:8px;background:rgba(59,130,246,0.1);
                                    display:flex;align-items:center;justify-content:center;font-size:14px;">
                            ${_getInitialAvatar(w.fullname)}
                        </div>
                        <div>
                            <strong>${escapeHtml(w.fullname || 'Usuário')}</strong>
                            <div style="font-size:10px;color:var(--text-secondary);margin-top:1px">${escapeHtml(w.pixType || '')}</div>
                        </div>
                    </div>
                </td>
                <td><span class="type-tag local">${platform}</span></td>
                <td>
                    <code style="font-size:11px;max-width:140px;display:inline-block;overflow:hidden;
                                 text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(w.pixKey)}">
                        ${escapeHtml(w.pixKey || '—')}
                    </code>
                </td>
                <td>
                    <strong style="color:var(--primary);font-family:var(--font-mono)">
                        R$ ${parseFloat(w.amount || 0).toFixed(2)}
                    </strong>
                </td>
                <td id="risk-cell-${wid}">
                    ${buildRiskBadgeHTML(null)}
                </td>
                <td>
                    <div style="display:flex;gap:6px;align-items:center;">
                        <button class="btn-table-action btn-secops-detail"
                            onclick="showRiskDetail('${wid}')"
                            title="Ver análise de risco detalhada">
                            🛡️
                        </button>
                        <button class="btn-table-action"
                            id="btn-approve-${wid}"
                            onclick="approveWithdrawal('${wid}')"
                            title="Pagar via PIX">
                            PAGAR
                        </button>
                    </div>
                </td>
            </tr>`;
    }).join('');

    // Total acumulado
    const total = entries.reduce((s, [, w]) => s + parseFloat(w.amount || 0), 0);
    const totalEl = document.getElementById('total-pendente-display');
    if (totalEl) totalEl.textContent = `R$ ${total.toFixed(2)}`;

    // Busca análise de risco assincronamente para cada saque
    entries.forEach(([wid, w]) => {
        fetchRiskAnalysis(wid).then(analysis => {
            const cell = document.getElementById(`risk-cell-${wid}`);
            if (cell) {
                cell.innerHTML = buildRiskBadgeHTML(analysis);
            }

            // Destaca a linha se for crítico
            if (analysis?.risk_level === 'CRITICAL') {
                const row = document.getElementById(`wd-row-${wid}`);
                if (row) {
                    row.style.background = 'rgba(239,68,68,0.05)';
                    row.style.borderLeft = '2px solid #ef4444';
                }
            }

            // Desabilita o botão de aprovar se recomendação for bloqueio
            if (analysis?.recommendation === 'HIGH_RISK_BLOCK') {
                const btn = document.getElementById(`btn-approve-${wid}`);
                if (btn) {
                    btn.disabled = true;
                    btn.title = 'Bloqueado pelo SecOps Sentinel — alto risco';
                    btn.style.opacity = '0.4';
                    btn.style.cursor = 'not-allowed';
                    btn.textContent = '🚫';
                }
            }
        });
    });
}

// ─────────────────────────────────────────────
//  Aprovação de saque com confirmação de risco
// ─────────────────────────────────────────────
async function approveWithdrawal(wid) {
    // Verifica score de risco antes de confirmar
    const analysis = _secopsCache.get(wid);
    if (analysis && analysis.risk_level === 'CRITICAL') {
        const proceed = confirm(
            `⚠️ ALERTA DE SEGURANÇA — SecOps Sentinel\n\n` +
            `Trust Score: ${analysis.trust_score}/100 (CRÍTICO)\n` +
            `${(analysis.reasons || []).join('\n')}\n\n` +
            `Tem CERTEZA que deseja pagar mesmo assim?`
        );
        if (!proceed) return;
    } else if (!confirm("Confirmar pagamento via Asaas PIX?")) {
        return;
    }

    const btn = document.getElementById(`btn-approve-${wid}`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳';
    }

    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/payments/approve/${wid}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        const data = await resp.json();
        // FIX 1.3: backend retorna { status: "approved" } e erros vêm em "detail".
        // Antes usava "success"/"message", que nunca eram enviados -> "Erro: undefined".
        const isApproved = data.status === 'approved';
        showToast(
            isApproved ? `✅ Pagamento aprovado!` : `❌ Erro: ${data.detail || data.message || 'Falha na aprovação'}`,
            isApproved ? 'success' : 'error'
        );

        if (isApproved) {
            // Limpa cache e remove linha da tabela
            _secopsCache.delete(wid);
            const row = document.getElementById(`wd-row-${wid}`);
            if (row) {
                row.style.transition = 'opacity 0.4s';
                row.style.opacity = '0';
                setTimeout(() => row.remove(), 400);
            }
        }
    } catch (e) {
        showToast("Erro de conexão ao aprovar saque.", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'PAGAR';
        }
    }
}

// ─────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────
function _getInitialAvatar(name) {
    if (!name) return '👤';
    const initials = escapeHtml(name.trim().split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase());
    return `<span style="font-size:11px;font-weight:700;color:var(--primary)">${initials}</span>`;
}
