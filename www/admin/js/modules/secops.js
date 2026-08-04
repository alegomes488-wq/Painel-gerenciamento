/**
 * ============================================================
 *  SecOps Sentinel AI — Módulo de Interface do Painel Admin
 *  v1.0 — Agente de Cibersegurança em Tempo Real
 * ============================================================
 */

// ── Cache de análises para evitar re-requisições desnecessárias ──
const _secopsCache = new Map();
let _secopsAuditInterval = null;

// ── Mapa de cores e ícones por nível de risco ──
const RISK_CONFIG = {
    LOW:      { color: '#10b981', icon: '🟢', label: 'BAIXO',    badge: 'online',   bar: '#10b981' },
    MEDIUM:   { color: '#f59e0b', icon: '🟡', label: 'MÉDIO',    badge: 'degraded', bar: '#f59e0b' },
    HIGH:     { color: '#f97316', icon: '🟠', label: 'ALTO',     badge: 'warn',     bar: '#f97316' },
    CRITICAL: { color: '#ef4444', icon: '🔴', label: 'CRÍTICO',  badge: 'offline',  bar: '#ef4444' },
};

const REC_CONFIG = {
    AUTO_APPROVE:   { label: 'AUTO-APROVAÇÃO', color: '#10b981' },
    MANUAL_REVIEW:  { label: 'REVISÃO MANUAL', color: '#f59e0b' },
    HIGH_RISK_BLOCK:{ label: 'BLOQUEAR',       color: '#ef4444' },
};

// ─────────────────────────────────────────────
//  FUNÇÃO PÚBLICA: Busca análise de risco de um saque
// ─────────────────────────────────────────────
async function fetchRiskAnalysis(wid) {
    if (_secopsCache.has(wid)) return _secopsCache.get(wid);

    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/secops/risk-analysis/${wid}`, {
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        if (!resp.ok) return null;
        const data = await resp.json();
        const analysis = data?.analysis || null;
        if (analysis) {
            _secopsCache.set(wid, analysis);
            // Expira cache em 60s
            setTimeout(() => _secopsCache.delete(wid), 60_000);
        }
        return analysis;
    } catch (e) {
        console.warn('[SecOps] Erro ao buscar análise:', e);
        return null;
    }
}

// ─────────────────────────────────────────────
//  Gera o HTML do badge de risco para a tabela de saques
// ─────────────────────────────────────────────
function buildRiskBadgeHTML(analysis) {
    if (!analysis) {
        return `<span class="secops-badge loading" title="Analisando...">
                    <span class="secops-pulse"></span> ANALISANDO
                </span>`;
    }
    const cfg = RISK_CONFIG[analysis.risk_level] || RISK_CONFIG.MEDIUM;
    const rec = REC_CONFIG[analysis.recommendation] || {};
    const score = analysis.trust_score ?? '—';

    return `
        <div class="secops-risk-cell" title="${(analysis.reasons || []).join(' | ')}">
            <div class="secops-score-ring" style="--ring-color:${cfg.color}">
                <span class="secops-score-value">${score}</span>
            </div>
            <div class="secops-risk-labels">
                <span class="secops-level-badge" style="color:${cfg.color};border-color:${cfg.color}30;background:${cfg.color}12">
                    ${cfg.icon} ${cfg.label}
                </span>
                <span class="secops-rec-label" style="color:${rec.color ?? '#9ca3af'};font-size:9px;">
                    ${rec.label ?? '—'}
                </span>
            </div>
        </div>`;
}

// ─────────────────────────────────────────────
//  PAINEL SECOPS — Renderiza o resumo de saques e auditoria
// ─────────────────────────────────────────────
async function renderSecOpsPanel() {
    const container = document.getElementById('secops-panel-container');
    if (!container) return;

    container.innerHTML = `
        <div class="secops-loading-state">
            <div class="secops-spinner"></div>
            <p>SecOps Sentinel analisando infraestrutura...</p>
        </div>`;

    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/secops/summary`, {
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _renderSecOpsDashboard(data, container);
    } catch (e) {
        container.innerHTML = `
            <div class="secops-error-state">
                <span style="font-size:32px;">⚠️</span>
                <p>Não foi possível conectar ao agente SecOps.</p>
                <small style="color:var(--text-secondary)">${e.message}</small>
                <button class="btn-premium" onclick="renderSecOpsPanel()" style="margin-top:15px;padding:8px 20px;font-size:11px;">
                    Tentar novamente
                </button>
            </div>`;
    }
}

function _renderSecOpsDashboard(data, container) {
    const rc = data.risk_counts || {};
    const total = data.total_pending || 0;
    const secure = data.system_secure !== false;
    const items = data.pending_items || [];

    // ── KPIs de Risco ──
    const kpiHtml = `
        <div class="secops-kpi-grid">
            <div class="secops-kpi" style="--kpi-color:#10b981">
                <span class="secops-kpi-icon">🟢</span>
                <div>
                    <div class="secops-kpi-value">${rc.low ?? 0}</div>
                    <div class="secops-kpi-label">Baixo Risco</div>
                </div>
            </div>
            <div class="secops-kpi" style="--kpi-color:#f59e0b">
                <span class="secops-kpi-icon">🟡</span>
                <div>
                    <div class="secops-kpi-value">${rc.medium ?? 0}</div>
                    <div class="secops-kpi-label">Risco Médio</div>
                </div>
            </div>
            <div class="secops-kpi" style="--kpi-color:#f97316">
                <span class="secops-kpi-icon">🟠</span>
                <div>
                    <div class="secops-kpi-value">${rc.high ?? 0}</div>
                    <div class="secops-kpi-label">Alto Risco</div>
                </div>
            </div>
            <div class="secops-kpi" style="--kpi-color:#ef4444">
                <span class="secops-kpi-icon">🔴</span>
                <div>
                    <div class="secops-kpi-value">${rc.critical ?? 0}</div>
                    <div class="secops-kpi-label">CRÍTICO</div>
                </div>
            </div>
        </div>`;

    // ── Barra de distribuição de risco ──
    const barHtml = total > 0 ? (() => {
        const pct = (n) => Math.round(((n ?? 0) / total) * 100);
        const pLow = pct(rc.low), pMed = pct(rc.medium), pHigh = pct(rc.high), pCrit = pct(rc.critical);
        return `
            <div class="secops-risk-bar-container">
                <div class="secops-risk-bar-label">Distribuição de Risco (${total} saques pendentes)</div>
                <div class="secops-risk-bar">
                    ${pLow > 0  ? `<div class="secops-risk-segment" style="width:${pLow}%;background:#10b981" title="Baixo: ${pLow}%"></div>` : ''}
                    ${pMed > 0  ? `<div class="secops-risk-segment" style="width:${pMed}%;background:#f59e0b" title="Médio: ${pMed}%"></div>` : ''}
                    ${pHigh > 0 ? `<div class="secops-risk-segment" style="width:${pHigh}%;background:#f97316" title="Alto: ${pHigh}%"></div>` : ''}
                    ${pCrit > 0 ? `<div class="secops-risk-segment" style="width:${pCrit}%;background:#ef4444" title="Crítico: ${pCrit}%"></div>` : ''}
                </div>
            </div>`;
    })() : '';

    // ── Auditoria de Infraestrutura ──
    const auditHtml = `
        <div class="secops-section-title">🔐 AUDITORIA DE INFRAESTRUTURA</div>
        <div id="secops-health-audit-container">
            <button class="btn-secops-audit" onclick="runHealthAudit()">
                🔍 Executar Auditoria Completa
            </button>
        </div>`;

    // ── Lista de saques com scores ──
    const tableHtml = items.length > 0 ? `
        <div class="secops-section-title">📋 SAQUES EM FILA — SCORES DE RISCO</div>
        <div class="secops-withdraw-table">
            <div class="secops-table-header">
                <span>Usuário</span>
                <span>Valor</span>
                <span>Score</span>
                <span>Risco</span>
                <span>Recomendação</span>
            </div>
            ${items.map(item => {
                const cfg = RISK_CONFIG[item.risk_level] || RISK_CONFIG.MEDIUM;
                const rec = REC_CONFIG[item.recommendation] || {};
                return `
                <div class="secops-table-row" onclick="showRiskDetail('${item.wid}')" title="Clique para detalhes">
                    <span class="secops-table-user">${item.fullname || 'Usuário'}</span>
                    <span class="secops-table-amount">R$ ${parseFloat(item.amount || 0).toFixed(2)}</span>
                    <span class="secops-score-mini" style="color:${cfg.color}">${item.trust_score ?? '—'}</span>
                    <span class="secops-level-badge-sm" style="color:${cfg.color}">${cfg.icon} ${cfg.label}</span>
                    <span class="secops-rec-sm" style="color:${rec.color ?? '#9ca3af'}">${rec.label ?? '—'}</span>
                </div>`;
            }).join('')}
        </div>` : `
        <div class="secops-empty-state">
            <span style="font-size:28px">✅</span>
            <p>Nenhum saque pendente em análise.</p>
        </div>`;

    // ── Status geral do sistema ──
    const statusBanner = `
        <div class="secops-system-banner" style="--banner-color:${secure ? '#10b981' : '#ef4444'}">
            <span>${secure ? '🛡️' : '⚠️'}</span>
            <div>
                <strong>${secure ? 'SISTEMA SEGURO' : 'ATENÇÃO — FALHA DE SEGURANÇA DETECTADA'}</strong>
                <small>SecOps Sentinel AI v1.0 — ${new Date().toLocaleTimeString('pt-BR')}</small>
            </div>
            <button class="btn-secops-refresh" onclick="renderSecOpsPanel()" title="Atualizar">↺</button>
        </div>`;

    container.innerHTML = statusBanner + kpiHtml + barHtml + auditHtml + tableHtml;
}

// ─────────────────────────────────────────────
//  Auditoria de saúde da infraestrutura
// ─────────────────────────────────────────────
async function runHealthAudit() {
    const container = document.getElementById('secops-health-audit-container');
    if (!container) return;

    container.innerHTML = `<div class="secops-audit-running">
        <div class="secops-spinner" style="width:16px;height:16px;"></div>
        Auditando chaves API e infraestrutura...
    </div>`;

    try {
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/secops/health-audit`, {
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const audit = await resp.json();
        _renderHealthAuditResult(audit, container);
    } catch(e) {
        container.innerHTML = `<div class="secops-audit-error">⚠️ Falha na auditoria: ${e.message}</div>`;
    }
}

function _renderHealthAuditResult(audit, container) {
    const statusMap = {
        OK:   { color: '#10b981', icon: '✅' },
        WARN: { color: '#f59e0b', icon: '⚠️' },
        INFO: { color: '#3b82f6', icon: 'ℹ️' },
        FAIL: { color: '#ef4444', icon: '❌' },
    };

    const checksHtml = (audit.audit_results || []).map(c => {
        const s = statusMap[c.status] || statusMap.INFO;
        return `
            <div class="secops-audit-item">
                <span class="secops-audit-status" style="color:${s.color}">${s.icon}</span>
                <div>
                    <div class="secops-audit-item-name">${c.item}</div>
                    <div class="secops-audit-item-detail" style="color:${s.color}">${c.detail}</div>
                </div>
            </div>`;
    }).join('');

    container.innerHTML = `
        <div class="secops-audit-result">
            <div class="secops-audit-meta">
                <span>${audit.total_checks ?? 0} verificações realizadas</span>
                <span style="color:${audit.system_secure ? '#10b981' : '#ef4444'}">
                    ${audit.system_secure ? '🛡️ Sistema Seguro' : '⚠️ Falhas Detectadas'}
                </span>
            </div>
            <div class="secops-audit-checks">${checksHtml}</div>
            <button class="btn-secops-audit" onclick="runHealthAudit()" style="margin-top:12px">
                🔄 Re-Auditar
            </button>
        </div>`;
}

// ─────────────────────────────────────────────
//  Modal de detalhe de risco de um saque
// ─────────────────────────────────────────────
async function showRiskDetail(wid) {
    const analysis = await fetchRiskAnalysis(wid);
    if (!analysis) {
        showToast('Não foi possível carregar análise de risco.', 'error');
        return;
    }

    const cfg = RISK_CONFIG[analysis.risk_level] || RISK_CONFIG.MEDIUM;
    const rec = REC_CONFIG[analysis.recommendation] || {};

    const overlay = document.createElement('div');
    overlay.className = 'secops-modal-overlay';
    overlay.id = 'secops-detail-modal';
    overlay.innerHTML = `
        <div class="secops-modal-box">
            <div class="secops-modal-header" style="border-color:${cfg.color}40">
                <div>
                    <div class="secops-modal-title">🛡️ Análise de Risco — SecOps Sentinel</div>
                    <div class="secops-modal-sub">${analysis.fullname || 'Usuário'} • R$ ${parseFloat(analysis.amount || 0).toFixed(2)}</div>
                </div>
                <button class="secops-modal-close" onclick="document.getElementById('secops-detail-modal').remove()">✕</button>
            </div>

            <div class="secops-modal-score-section">
                <div class="secops-score-donut" style="--score:${analysis.trust_score ?? 0};--color:${cfg.color}">
                    <div class="secops-donut-inner">
                        <span class="secops-donut-number" style="color:${cfg.color}">${analysis.trust_score ?? '—'}</span>
                        <span class="secops-donut-label">Trust Score</span>
                    </div>
                </div>
                <div class="secops-modal-verdict">
                    <div class="secops-level-badge" style="color:${cfg.color};border-color:${cfg.color}40;background:${cfg.color}15;font-size:14px;padding:8px 16px">
                        ${cfg.icon} RISCO ${cfg.label}
                    </div>
                    <div class="secops-rec-tag" style="background:${rec.color ?? '#9ca3af'}20;color:${rec.color ?? '#9ca3af'};border:1px solid ${rec.color ?? '#9ca3af'}40">
                        📋 ${rec.label ?? '—'}
                    </div>
                </div>
            </div>

            <div class="secops-modal-section-title">🔍 Motivos da Análise</div>
            <div class="secops-reasons-list">
                ${(analysis.reasons || []).map(r =>
                    `<div class="secops-reason-item">
                        <span class="secops-reason-dot" style="background:${cfg.color}"></span>
                        ${r}
                    </div>`
                ).join('')}
            </div>

            <div class="secops-modal-section-title">📊 Dados do Saque</div>
            <div class="secops-modal-data-grid">
                <div class="secops-data-item"><span>Tipo PIX</span><strong>${analysis.pixType || '—'}</strong></div>
                <div class="secops-data-item"><span>Chave PIX</span><strong class="secops-pix-key">${analysis.pixKey || '—'}</strong></div>
                <div class="secops-data-item"><span>UID</span><strong class="secops-uid">${analysis.uid || '—'}</strong></div>
                <div class="secops-data-item"><span>Avaliado em</span><strong>${analysis.evaluated_at ? new Date(analysis.evaluated_at).toLocaleString('pt-BR') : '—'}</strong></div>
            </div>

            <div class="secops-modal-footer">
                <button class="btn-secops-block" onclick="document.getElementById('secops-detail-modal').remove()">
                    Fechar
                </button>
                ${analysis.recommendation !== 'HIGH_RISK_BLOCK' ? `
                <button class="btn-secops-approve" onclick="approveWithdrawal('${wid}');document.getElementById('secops-detail-modal').remove()">
                    ✅ Aprovar mesmo assim
                </button>` : ''}
            </div>
        </div>`;

    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('active'));
}

// ─────────────────────────────────────────────
//  Inicia polling de atualização automática do painel SecOps
// ─────────────────────────────────────────────
function startSecOpsAutoRefresh(intervalMs = 120_000) {
    if (_secopsAuditInterval) clearInterval(_secopsAuditInterval);
    _secopsAuditInterval = setInterval(() => {
        const panel = document.getElementById('panel-secops');
        if (panel && panel.classList.contains('active')) {
            renderSecOpsPanel();
        }
    }, intervalMs);
}

function stopSecOpsAutoRefresh() {
    if (_secopsAuditInterval) {
        clearInterval(_secopsAuditInterval);
        _secopsAuditInterval = null;
    }
}
