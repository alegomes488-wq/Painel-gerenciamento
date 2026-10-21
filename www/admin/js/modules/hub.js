/**
 * ============================================================
 *  Painel HUB — Módulo de Operação Integrada (Cyber Core IA)
 *  Pilares: Desempenho | Acompanhamento | Segurança
 *  v1.0 — consolida /api/hub/* com hierarquia de criticidade
 * ============================================================
 */

const HUB_SEVERITY = {
    critical: { color: '#ef4444', label: 'CRÍTICO', icon: '🔴', rank: 0 },
    high:     { color: '#f97316', label: 'ALTO',    icon: '🟠', rank: 1 },
    medium:   { color: '#f59e0b', label: 'MÉDIO',   icon: '🟡', rank: 2 },
    low:      { color: '#3b82f6', label: 'BAIXO',   icon: '🔵', rank: 3 },
};

const HUB_PILLAR_LABELS = {
    performance: 'Desempenho',
    tracking: 'Acompanhamento',
    security: 'Segurança',
};

const HUB_HEALTH_LEVELS = {
    ESTAVEL:          { color: '#10b981', label: 'ESTÁVEL' },
    ATENCAO:          { color: '#f59e0b', label: 'ATENÇÃO' },
    CRITICO:          { color: '#f97316', label: 'CRÍTICO' },
    RISCO_DE_OUTAGE:  { color: '#ef4444', label: 'RISCO DE OUTAGE' },
};

let _hubCharts = {};
let _hubRefreshInterval = null;
let _hubPendingFocus = null;
let _hubWidgetTimer = null;

// ── Helpers ────────────────────────────────────────────────

function _hubFmt(value, digits = 1) {
    const n = parseFloat(value);
    if (isNaN(n)) return '—';
    return n.toLocaleString('pt-BR', { maximumFractionDigits: digits });
}

function _hubInt(value) {
    const n = parseInt(value, 10);
    return isNaN(n) ? 0 : n;
}

function _hubKpi(label, value, color = 'var(--text-primary)', sub = '') {
    return `
        <div class="hub-kpi" style="--hub-kpi-color:${color}">
            <div class="hub-kpi-value" style="color:${color}">${value}</div>
            <div class="hub-kpi-label">${escapeHtml(label)}</div>
            ${sub ? `<small>${escapeHtml(sub)}</small>` : ''}
        </div>`;
}

function _hubDestroyChart(key) {
    if (_hubCharts[key]) {
        try { _hubCharts[key].destroy(); } catch (e) { /* noop */ }
        delete _hubCharts[key];
    }
}

function _hubNoData(msg = 'Sem dados recebidos. Os agentes enviarão métricas em breve.') {
    return `<div class="hub-empty">${escapeHtml(msg)}</div>`;
}

async function _hubFetch(path, options = {}) {
    const idToken = await auth.currentUser.getIdToken();
    const resp = await fetch(`${BRASILHEXA_BACKEND_URL}${path}`, {
        ...options,
        headers: { 'Authorization': `Bearer ${idToken}`, ...(options.headers || {}) },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

// ── Render principal ───────────────────────────────────────

async function renderHubPanel() {
    const banner = document.getElementById('hub-criticality-banner');
    try {
        const overview = await _hubFetch('/api/hub/overview');
        _hubRenderBanner(banner, overview);
        _hubRenderCopilot(overview.correlations || []);
        _hubRenderScores(overview.health || {});
        _hubRenderPerformance((overview.pillars || {}).performance || {});
        _hubRenderTracking((overview.pillars || {}).tracking || {});
        _hubRenderSecurity((overview.pillars || {}).security || {}, overview.quarantined_ips);
        _hubRenderCorrelations(overview.correlations || []);
        const refreshEl = document.getElementById('hub-last-refresh');
        if (refreshEl) refreshEl.textContent = 'Atualizado em: ' + new Date().toLocaleTimeString('pt-BR');
        await _hubLoadActions();
        _hubApplyFocus();
    } catch (e) {
        if (banner) {
            banner.innerHTML = `
                <div class="hub-banner hub-sev-high">
                    <span>⚠️</span>
                    <div><strong>Não foi possível carregar o painel HUB</strong>
                    <small>${escapeHtml(e.message)}</small></div>
                    <button class="btn-premium" onclick="renderHubPanel()" style="padding:6px 14px;font-size:10px;">Tentar novamente</button>
                </div>`;
        }
    }
}

async function _hubLoadActions() {
    try {
        const data = await _hubFetch('/api/hub/actions?limit=15');
        _hubRenderActions(data.actions || []);
    } catch (e) {
        const el = document.querySelector('#hub-actions .hub-card-body');
        if (el) el.innerHTML = _hubNoData('Não foi possível carregar o log de ações.');
    }
}

// ── Banner de criticidade (hierarquia visual) ──────────────

function _hubRenderBanner(el, overview) {
    if (!el) return;
    const worst = overview.worst_severity;
    const criticalCount = overview.critical_count || 0;
    if (!worst) {
        el.innerHTML = `
            <div class="hub-banner hub-sev-low">
                <span>🟢</span>
                <div><strong>SISTEMA ESTÁVEL — NENHUMA CORRELAÇÃO CRÍTICA</strong>
                <small>Cyber Core IA monitorando os três pilares em tempo real</small></div>
            </div>`;
        return;
    }
    const cfg = HUB_SEVERITY[worst] || HUB_SEVERITY.medium;
    el.innerHTML = `
        <div class="hub-banner hub-sev-${worst}" style="--hub-sev:${cfg.color}">
            <span>${cfg.icon}</span>
            <div>
                <strong>${criticalCount > 0 ? `${criticalCount} EVENTO(S) CRÍTICO(S) — ` : ''}${cfg.label}</strong>
                <small>Cyber Core IA correlacionou sinais entre os pilares. Revise as correlações abaixo.</small>
            </div>
        </div>`;
}

// ── Copilot do agente de suporte ───────────────────────────

function _hubRenderCopilot(correlations) {
    const el = document.getElementById('hub-copilot-card');
    if (!el) return;
    const lookupHtml = `
        <div class="hub-copilot-lookup">
            <input id="hub-copilot-query" type="text" placeholder="UID ou e-mail do usuário para análise contextual…"
                onkeydown="if(event.key==='Enter')hubCopilotLookup()" autocomplete="off">
            <button class="btn-premium" onclick="hubCopilotLookup()">Analisar</button>
        </div>
        <div id="hub-copilot-result"></div>`;
    if (!correlations.length) {
        el.innerHTML = `
            <div class="hub-copilot">
                <div class="hub-copilot-head">🤖 COPILOT DA CYBER CORE IA <small>Resumo contextual para o agente de suporte</small></div>
                <p class="hub-copilot-msg">Nenhuma anomalia correlacionada no momento. Ao atender um usuário, digite o UID ou e-mail abaixo para gerar o resumo contextual (dispositivo, Root, versão do app, rede e bloqueios).</p>
                ${lookupHtml}
            </div>`;
        return;
    }
    const top = correlations[0];
    const cfg = HUB_SEVERITY[top.severity] || HUB_SEVERITY.medium;
    el.innerHTML = `
        <div class="hub-copilot" style="border-left-color:${cfg.color}">
            <div class="hub-copilot-head">🤖 COPILOT DA CYBER CORE IA <small>Resumo contextual para o agente de suporte</small></div>
            <p class="hub-copilot-msg" style="color:${cfg.color}">${escapeHtml(top.message || '')}</p>
            ${(top.evidence || []).length ? `<div class="hub-copilot-evidence">${top.evidence.map(ev => `<span>${escapeHtml(ev)}</span>`).join('')}</div>` : ''}
            ${lookupHtml}
        </div>`;
}

// ── Copilot: brief contextual por usuário (uid ou e-mail) ────

async function hubCopilotLookup() {
    const input = document.getElementById('hub-copilot-query');
    const out = document.getElementById('hub-copilot-result');
    if (!input || !out) return;
    const query = input.value.trim();
    if (!query) { showToast('Informe o UID ou e-mail do usuário.', 'warning'); return; }
    out.innerHTML = '<div class="hub-loading"><div class="secops-spinner"></div><p>Gerando brief contextual…</p></div>';
    try {
        const brief = await _hubFetch(`/api/hub/copilot?query=${encodeURIComponent(query)}`);
        out.innerHTML = _hubBriefHtml(brief);
    } catch (e) {
        out.innerHTML = `<div class="hub-empty" style="color:#f97316">${escapeHtml(e.message === 'HTTP 404' ? 'Usuário não encontrado (verifique UID ou e-mail).' : e.message)}</div>`;
    }
}

function _hubBriefHtml(brief) {
    const flagColors = {
        ACCESS_REVOKED: '#ef4444', ROOT_DEVICE: '#f97316', JAILBREAK_DEVICE: '#f97316',
        PAYMENT_BLOCKED_BY_SECURITY: '#f59e0b', PENDING_WITHDRAWAL: '#8b5cf6',
        NO_DEVICE_CONTEXT: '#71717a',
    };
    const flagsHtml = (brief.flags || []).length
        ? `<div class="hub-copilot-evidence">${brief.flags.map(f =>
            `<span style="border-color:${flagColors[f] || '#3b82f6'};color:${flagColors[f] || '#3b82f6'}">${escapeHtml(f)}</span>`).join('')}</div>`
        : '';
    const ctx = brief.context || {};
    const ctxBits = [
        ctx.platform ? `Plataforma: ${escapeHtml(ctx.platform)}` : null,
        ctx.app_version ? `App: ${escapeHtml(ctx.app_version)}` : null,
        ctx.network_type ? `Rede: ${escapeHtml(ctx.network_type)}` : null,
        ctx.last_screen ? `Última tela: ${escapeHtml(ctx.last_screen)}` : null,
    ].filter(Boolean).join(' · ');
    return `
        <div class="hub-copilot" style="margin-top:10px;border-left-color:#22d3ee">
            <div class="hub-copilot-head">BRIEF DO ATENDIMENTO <small>${escapeHtml(brief.uid || '')}</small></div>
            <p class="hub-copilot-msg">${escapeHtml(brief.summary || '')}</p>
            ${ctxBits ? `<p class="hub-copilot-msg" style="font-size:11px">${ctxBits}</p>` : ''}
            ${flagsHtml}
        </div>`;
}

// ── Scores dos pilares ─────────────────────────────────────

function _hubRenderScores(health) {
    const el = document.getElementById('hub-pillar-scores');
    if (!el) return;
    const per = health.per_pillar || {};
    const level = HUB_HEALTH_LEVELS[health.level] || HUB_HEALTH_LEVELS.ATENCAO;
    const cards = ['performance', 'tracking', 'security'].map(pillar => {
        const score = (per[pillar] !== undefined) ? per[pillar] : null;
        const color = score === null ? '#52525b' : (score >= 90 ? '#10b981' : score >= 70 ? '#f59e0b' : score >= 40 ? '#f97316' : '#ef4444');
        return `
            <div class="hub-score-card" style="--score-color:${color}">
                <div class="hub-score-ring" style="--ring-color:${color}"><span>${score === null ? '—' : score}</span></div>
                <div class="hub-score-info">
                    <strong>${HUB_PILLAR_LABELS[pillar]}</strong>
                    <small>Score do pilar</small>
                </div>
            </div>`;
    }).join('');
    el.innerHTML = `
        <div class="hub-score-card hub-score-global" style="--score-color:${level.color}">
            <div class="hub-score-ring" style="--ring-color:${level.color}"><span>${health.score ?? '—'}</span></div>
            <div class="hub-score-info"><strong>SAÚDE GLOBAL</strong><small style="color:${level.color}">${level.label}</small></div>
        </div>
        ${cards}`;
}

// ── Pilar 1: Desempenho ────────────────────────────────────

function _hubRenderPerformance(perf) {
    const el = document.getElementById('hub-performance');
    if (!el) return;
    const web = perf.web || {};
    const app = perf.app || {};
    const api = perf.api || {};
    const blockedRollouts = Object.entries(perf.blocked_rollouts || {})
        .filter(([, v]) => v && v.active)
        .map(([version]) => version);
    const rolloutWarning = blockedRollouts.length
        ? `<div class="hub-banner hub-sev-high" style="padding:8px 12px;font-size:11px;">
            <span>⛔</span><div><strong>ROLLOUT BLOQUEADO: v${blockedRollouts.map(escapeHtml).join(', v')}</strong>
            <small>A Cyber Core IA segurou a promoção destas versões do APK (regressão detectada).</small></div>
           </div>`
        : '';

    const webKpis = `
        <div class="hub-kpi-row">
            ${_hubKpi('LCP', web.lcp_ms !== undefined ? `${_hubFmt(web.lcp_ms, 0)}ms` : '—', _hubVitalColor(web.lcp_ms, [2500, 4000], true))}
            ${_hubKpi('INP', web.inp_ms !== undefined ? `${_hubFmt(web.inp_ms, 0)}ms` : '—', _hubVitalColor(web.inp_ms, [200, 500], true))}
            ${_hubKpi('CLS', web.cls !== undefined ? _hubFmt(web.cls, 3) : '—', _hubVitalColor(web.cls, [0.1, 0.25], true))}
            ${_hubKpi('TTFB', web.ttfb_ms !== undefined ? `${_hubFmt(web.ttfb_ms, 0)}ms` : '—', _hubVitalColor(web.ttfb_ms, [800, 1800], true))}
            ${_hubKpi('Erros 5xx', web.error_rate_5xx !== undefined ? `${_hubFmt(web.error_rate_5xx, 2)}%` : '—', _hubVitalColor(web.error_rate_5xx, [1, 2]))}
        </div>`;

    const appKpis = `
        <div class="hub-kpi-row">
            ${_hubKpi('Crash Rate', app.crash_rate !== undefined ? `${_hubFmt(app.crash_rate, 2)}%` : '—', _hubVitalColor(app.crash_rate, [1, 1.5]))}
            ${_hubKpi('ANR', app.anr_rate !== undefined ? `${_hubFmt(app.anr_rate, 2)}%` : '—', _hubVitalColor(app.anr_rate, [0.3, 0.5]))}
            ${_hubKpi('Launch Time', app.launch_time_ms !== undefined ? `${_hubFmt(app.launch_time_ms, 0)}ms` : '—', _hubVitalColor(app.launch_time_ms, [2000, 5000], true))}
            ${_hubKpi('Frozen Frames', app.frozen_frames_rate !== undefined ? `${_hubFmt(app.frozen_frames_rate, 2)}%` : '—', _hubVitalColor(app.frozen_frames_rate, [1, 3]))}
            ${_hubKpi('Versão ativa', app.apk_version || '—', 'var(--text-secondary)')}
        </div>`;

    const apiKpis = `
        <div class="hub-kpi-row">
            ${_hubKpi('Latência p95', api.latency_p95_ms !== undefined ? `${_hubFmt(api.latency_p95_ms, 0)}ms` : '—', _hubVitalColor(api.latency_p95_ms, [500, 1500], true))}
            ${_hubKpi('Throughput', api.rps !== undefined ? `${_hubFmt(api.rps, 1)} req/s` : '—', 'var(--cyan-400)')}
            ${_hubKpi('Erros API', api.error_rate !== undefined ? `${_hubFmt(api.error_rate, 2)}%` : '—', _hubVitalColor(api.error_rate, [1, 3]))}
        </div>`;

    el.querySelector('.hub-card-body').innerHTML = `
        ${rolloutWarning}
        <div class="hub-subsection" id="hub-sec-web">WEB — CORE WEB VITALS (site)</div>
        ${webKpis}
        <div class="hub-subsection" id="hub-sec-app">APP / APK — ESTABILIDADE E HARDWARE</div>
        ${appKpis}
        <div class="hub-chart-wrap"><canvas id="hub-chart-crash-version" height="140"></canvas></div>
        <div class="hub-subsection" id="hub-sec-api">API / BACK-END</div>
        ${apiKpis}
        <div class="hub-chart-wrap"><canvas id="hub-chart-api-latency" height="120"></canvas></div>`;

    _hubChartCrashByVersion(app.by_version || {});
    _hubChartApiLatency((perf.history || {}).api || []);
}

function _hubVitalColor(value, thresholds, lowerIsBetter = false) {
    if (value === undefined || value === null) return 'var(--text-secondary)';
    const v = parseFloat(value);
    if (isNaN(v)) return 'var(--text-secondary)';
    const bad = lowerIsBetter ? v > thresholds[1] : v < thresholds[0];
    const warn = lowerIsBetter ? v > thresholds[0] : v < thresholds[1];
    if (bad) return '#ef4444';
    if (warn) return '#f59e0b';
    return '#10b981';
}

function _hubChartCrashByVersion(byVersion) {
    const canvas = document.getElementById('hub-chart-crash-version');
    if (!canvas || typeof Chart === 'undefined') return;
    _hubDestroyChart('crashVersion');
    const labels = Object.keys(byVersion || {});
    if (!labels.length) return;
    const values = labels.map(l => parseFloat((byVersion[l] || {}).crash_rate) || 0);
    const prev = labels.map(l => parseFloat((byVersion[l] || {}).previous_crash_rate) || 0);
    _hubCharts.crashVersion = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                { label: 'Crash Rate atual (%)', data: values, backgroundColor: 'rgba(239,68,68,0.55)', borderColor: '#ef4444', borderWidth: 1 },
                { label: 'Anterior (%)', data: prev, backgroundColor: 'rgba(148,163,184,0.25)', borderColor: '#94a3b8', borderWidth: 1 },
            ],
        },
        options: _hubChartOpts('Crash Rate por versão do app (%)'),
    });
}

function _hubChartApiLatency(history) {
    const canvas = document.getElementById('hub-chart-api-latency');
    if (!canvas || typeof Chart === 'undefined') return;
    _hubDestroyChart('apiLatency');
    if (!Array.isArray(history) || !history.length) return;
    const points = history.slice(-30);
    _hubCharts.apiLatency = new Chart(canvas, {
        type: 'line',
        data: {
            labels: points.map(p => (p.t || '').slice(11, 16) || ''),
            datasets: [{
                label: 'Latência p95 (ms)',
                data: points.map(p => parseFloat(p.latency_p95_ms) || 0),
                borderColor: '#22d3ee',
                backgroundColor: 'rgba(34,211,238,0.08)',
                fill: true,
                tension: 0.3,
                pointRadius: 2,
            }],
        },
        options: _hubChartOpts('Latência da API — últimos pontos'),
    });
}

// ── Pilar 2: Acompanhamento ────────────────────────────────

function _hubRenderTracking(track) {
    const el = document.getElementById('hub-tracking');
    if (!el) return;
    const sessions = track.sessions || {};
    const funnels = track.funnels || {};
    const tickets = track.tickets || {};
    const steps = Array.isArray(funnels.steps) ? funnels.steps : [];
    const reasons = tickets.top_reasons || {};

    const sessionKpis = `
        <div class="hub-kpi-row">
            ${_hubKpi('Usuários ativos agora', _hubInt(sessions.active_now).toLocaleString('pt-BR'), '#10b981')}
            ${_hubKpi('Web', _hubInt(sessions.web).toLocaleString('pt-BR'), 'var(--cyan-400)')}
            ${_hubKpi('App', _hubInt(sessions.app).toLocaleString('pt-BR'), '#8b5cf6')}
            ${_hubKpi('Instalações APK ativas', _hubInt(sessions.apk_installs).toLocaleString('pt-BR'), '#f59e0b')}
        </div>`;

    const ticketKpis = `
        <div class="hub-kpi-row">
            ${_hubKpi('Tickets abertos', _hubInt(tickets.open), tickets.open > 50 ? '#ef4444' : '#10b981')}
            ${_hubKpi('TMA', tickets.avg_minutes !== undefined ? `${_hubFmt(tickets.avg_minutes, 0)} min` : '—', tickets.avg_minutes > 240 ? '#ef4444' : '#10b981')}
        </div>`;

    const reasonsHtml = Object.keys(reasons).length ? `
        <div class="hub-tags">
            ${Object.entries(reasons).slice(0, 8).map(([tag, count]) =>
                `<span class="hub-tag">${escapeHtml(tag)} <b>${_hubInt(count)}</b></span>`).join('')}
        </div>` : _hubNoData('Nenhum motivo de suporte classificado ainda.');

    el.querySelector('.hub-card-body').innerHTML = `
        <div class="hub-subsection" id="hub-sec-sessions">SESSÃO EM TEMPO REAL</div>
        ${sessionKpis}
        <div class="hub-chart-wrap" style="max-width:260px;margin:0 auto;"><canvas id="hub-chart-platform" height="200"></canvas></div>
        <div class="hub-subsection" id="hub-sec-funnels">FUNIL DE CONVERSÃO</div>
        <div class="hub-chart-wrap"><canvas id="hub-chart-funnel" height="${Math.max(120, steps.length * 36)}"></canvas></div>
        <div class="hub-subsection" id="hub-sec-tickets">SUPORTE / TICKETS</div>
        ${ticketKpis}
        ${reasonsHtml}`;

    _hubChartPlatform(sessions);
    _hubChartFunnel(steps);
}

function _hubChartPlatform(sessions) {
    const canvas = document.getElementById('hub-chart-platform');
    if (!canvas || typeof Chart === 'undefined') return;
    _hubDestroyChart('platform');
    const web = _hubInt(sessions.web);
    const app = _hubInt(sessions.app);
    if (!web && !app) return;
    _hubCharts.platform = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Web', 'App'],
            datasets: [{ data: [web, app], backgroundColor: ['rgba(34,211,238,0.7)', 'rgba(139,92,246,0.7)'], borderColor: 'rgba(11,18,32,0.8)', borderWidth: 2 }],
        },
        options: _hubChartOpts('Distribuição por plataforma', true),
    });
}

function _hubChartFunnel(steps) {
    const canvas = document.getElementById('hub-chart-funnel');
    if (!canvas || typeof Chart === 'undefined') return;
    _hubDestroyChart('funnel');
    if (!steps.length) return;
    _hubCharts.funnel = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: steps.map(s => s.name || s.id || '?'),
            datasets: [
                { label: 'Entraram', data: steps.map(s => parseFloat(s.entered) || 0), backgroundColor: 'rgba(59,130,246,0.45)' },
                { label: 'Concluíram', data: steps.map(s => parseFloat(s.converted) || 0), backgroundColor: 'rgba(16,185,129,0.55)' },
            ],
        },
        options: _hubChartOpts('Entrada vs. conclusão por etapa'),
    });
}

// ── Pilar 3: Segurança ─────────────────────────────────────

function _hubRenderSecurity(sec, quarantinedIps) {
    const el = document.getElementById('hub-security');
    if (!el) return;
    const apk = sec.apk || {};
    const network = sec.network || {};
    const authSec = sec.auth || {};
    const vulns = sec.vulnerabilities || {};
    const cveCount = (Array.isArray(vulns.web) ? vulns.web.length : 0) + (Array.isArray(vulns.app) ? vulns.app.length : 0);

    const quarantine = sec.quarantine || {};
    const activeQuarantine = Object.values(quarantine).filter(q => q && q.active).length;

    el.querySelector('.hub-card-body').innerHTML = `
        <div class="hub-subsection" id="hub-sec-apk">INTEGRIDADE DO APK (ANTI-TAMPERING)</div>
        <div class="hub-kpi-row">
            ${_hubKpi('Assinaturas inválidas', _hubInt(apk.invalid_signature_hits), apk.invalid_signature_hits > 0 ? '#ef4444' : '#10b981')}
            ${_hubKpi('Engenharia reversa', _hubInt(apk.tamper_attempts), apk.tamper_attempts > 0 ? '#f97316' : '#10b981')}
            ${_hubKpi('Reempacotamento', _hubInt(apk.repackage_alerts), apk.repackage_alerts > 0 ? '#f97316' : '#10b981')}
            ${_hubKpi('Root', _hubInt(apk.root_devices), apk.root_devices > 0 ? '#f59e0b' : '#10b981')}
            ${_hubKpi('Jailbreak', _hubInt(apk.jailbreak_devices), apk.jailbreak_devices > 0 ? '#f59e0b' : '#10b981')}
        </div>
        <div class="hub-subsection" id="hub-sec-network">SEGURANÇA DE REDE E TRÁFEGO (WAF)</div>
        <div class="hub-kpi-row">
            ${_hubKpi('Bloqueios WAF', _hubInt(network.waf_blocks), network.waf_blocks > 0 ? '#f59e0b' : '#10b981')}
            ${_hubKpi('SQL Injection', _hubInt(network.sqli_attempts), network.sqli_attempts > 0 ? '#ef4444' : '#10b981')}
            ${_hubKpi('XSS', _hubInt(network.xss_attempts), network.xss_attempts > 0 ? '#ef4444' : '#10b981')}
            ${_hubKpi('DDoS', _hubInt(network.ddos_attempts), network.ddos_attempts > 0 ? '#ef4444' : '#10b981')}
            ${_hubKpi('Bots/Emuladores', _hubInt(network.bot_blocks) + _hubInt(network.emulator_requests), '#f97316')}
        </div>
        <div class="hub-chart-wrap" style="max-width:280px;margin:10px auto;"><canvas id="hub-chart-attacks" height="200"></canvas></div>
        <div class="hub-subsection" id="hub-sec-auth">AUTENTICAÇÃO E FRAUDE</div>
        <div class="hub-kpi-row">
            ${_hubKpi('Falha de login (burst)', _hubInt(authSec.login_failures_burst), authSec.login_failures_burst > 100 ? '#ef4444' : '#10b981')}
            ${_hubKpi('Credential Stuffing', authSec.credential_stuffing_score !== undefined ? _hubFmt(authSec.credential_stuffing_score, 0) : '—', _hubVitalColor(authSec.credential_stuffing_score, [40, 70]))}
            ${_hubKpi('Contas falsas em lote', _hubInt(authSec.fake_accounts_bulk), authSec.fake_accounts_bulk > 10 ? '#ef4444' : '#10b981')}
            ${_hubKpi('IP impossível (viagem)', _hubInt(authSec.impossible_travel), authSec.impossible_travel > 0 ? '#ef4444' : '#10b981')}
        </div>
        <div class="hub-subsection">VULNERABILIDADES INTERNAS (CVE)</div>
        <div class="hub-kpi-row">
            ${_hubKpi('CVEs em dependências', cveCount, cveCount > 0 ? '#f97316' : '#10b981')}
            ${_hubKpi('IPs em quarentena', activeQuarantine || _hubInt(quarantinedIps), activeQuarantine > 0 ? '#ef4444' : '#10b981', 'Bloqueio preventivo ativo')}
        </div>`;

    _hubChartAttacks(network);
}

function _hubChartAttacks(network) {
    const canvas = document.getElementById('hub-chart-attacks');
    if (!canvas || typeof Chart === 'undefined') return;
    _hubDestroyChart('attacks');
    const entries = [
        ['SQLi', _hubInt(network.sqli_attempts)],
        ['XSS', _hubInt(network.xss_attempts)],
        ['DDoS', _hubInt(network.ddos_attempts)],
        ['WAF', _hubInt(network.waf_blocks)],
        ['Bots', _hubInt(network.bot_blocks)],
        ['Emuladores', _hubInt(network.emulator_requests)],
    ].filter(([, v]) => v > 0);
    if (!entries.length) return;
    _hubCharts.attacks = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: entries.map(e => e[0]),
            datasets: [{
                data: entries.map(e => e[1]),
                backgroundColor: ['#ef4444', '#f97316', '#dc2626', '#f59e0b', '#8b5cf6', '#22d3ee'],
                borderColor: 'rgba(11,18,32,0.8)',
                borderWidth: 2,
            }],
        },
        options: _hubChartOpts('Ataques e bloqueios por tipo', true),
    });
}

// ── Correlações (feed da IA) ───────────────────────────────

function _hubRenderCorrelations(correlations) {
    const el = document.getElementById('hub-correlations');
    if (!el) return;
    if (!correlations.length) {
        el.querySelector('.hub-card-body').innerHTML = _hubNoData('Nenhuma correlação ativa. A Cyber Core IA continua monitorando.');
        return;
    }
    const rows = correlations.map(c => {
        const cfg = HUB_SEVERITY[c.severity] || HUB_SEVERITY.medium;
        const action = c.recommended_action;
        const actionBtn = action ? `
            <button class="hub-action-btn" style="--btn-color:${cfg.color}"
                onclick='hubExecuteAction(${JSON.stringify({ type: action.type, params: action.params || {}, label: action.label })})'>
                ⚡ ${escapeHtml(action.label || action.type)}
            </button>` : '';
        return `
            <div class="hub-corr-item" style="--corr-color:${cfg.color}">
                <div class="hub-corr-head">
                    <span class="hub-sev-badge">${cfg.icon} ${cfg.label}</span>
                    <span class="hub-corr-pillar">${escapeHtml(HUB_PILLAR_LABELS[c.pillar] || c.pillar || '')}</span>
                    <span class="hub-corr-time">${c.generated_at ? new Date(c.generated_at).toLocaleString('pt-BR') : ''}</span>
                </div>
                <strong class="hub-corr-title">${escapeHtml(c.title || '')}</strong>
                <p class="hub-corr-msg">${escapeHtml(c.message || '')}</p>
                ${(c.evidence || []).length ? `<div class="hub-copilot-evidence">${c.evidence.map(ev => `<span>${escapeHtml(ev)}</span>`).join('')}</div>` : ''}
                ${actionBtn}
            </div>`;
    }).join('');
    el.querySelector('.hub-card-body').innerHTML = rows;
}

// ── Ações de segurança (log) ───────────────────────────────

function _hubRenderActions(actions) {
    const el = document.getElementById('hub-actions');
    if (!el) return;
    if (!actions.length) {
        el.querySelector('.hub-card-body').innerHTML = _hubNoData('Nenhuma ação executada (autônoma ou manual) até agora.');
        return;
    }
    el.querySelector('.hub-card-body').innerHTML = `
        <div class="hub-actions-list">
            ${actions.map(a => `
                <div class="hub-action-row">
                    <span class="hub-action-type">${escapeHtml(a.type || '')}</span>
                    <span class="hub-action-params">${escapeHtml(JSON.stringify(a.params || {}))}</span>
                    <span class="hub-action-actor">${escapeHtml(a.actor || '')}</span>
                    <span class="hub-action-time">${a.timestamp ? new Date(a.timestamp).toLocaleString('pt-BR') : ''}</span>
                </div>`).join('')}
        </div>`;
}

// ── Execução de ação pelo operador ─────────────────────────

async function hubExecuteAction(payload) {
    const label = payload.label || payload.type;
    const params = payload.params || {};
    const confirmMsgs = {
        quarantine_ip: `Colocar o IP ${params.ip || '?'} em quarentena? O tráfego deste IP será bloqueado de forma preventiva.`,
        release_ip: `Libertar o IP ${params.ip || '?'} da quarentena?`,
        revoke_access: `Revogar o acesso do usuário ${params.uid || '?'}? A conta ficará bloqueada até revisão de segurança.`,
        block_rollout: `Bloquear o rollout da versão ${params.app_version || '?'} do APK? O app deixará de promover esta versão (regressão detectada).`,
        unblock_rollout: `Desbloquear o rollout da versão ${params.app_version || '?'}?`,
    };
    if (!confirm(confirmMsgs[payload.type] || `Executar a "${label}"?`)) return;
    try {
        const result = await _hubFetch('/api/hub/actions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: payload.type, params, reason: label }),
        });
        if (result.result && result.result.status === 'skipped') {
            showToast(result.result.reason || 'Ação já aplicada anteriormente.', 'warning');
        } else {
            showToast(`Ação executada: ${label}`, 'success');
        }
        await renderHubPanel();
    } catch (e) {
        showToast('Falha ao executar ação: ' + e.message, 'error');
    }
}

// ── Chart.js defaults + opções ─────────────────────────────

function _hubChartOpts(title, legend = false) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: legend,
                labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 10 },
            },
            title: { display: !!title, text: title || '', color: '#94a3b8', font: { size: 10, weight: '600' } },
        },
        scales: legend ? {} : {
            x: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.04)' } },
            y: { ticks: { color: '#64748b', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.06)' }, beginAtZero: true },
        },
    };
}

// ── Ciclo de vida (auto-refresh) ───────────────────────────

async function startHubPanel() {
    if (!auth || !auth.currentUser) return;
    try {
        const tokenResult = await auth.currentUser.getIdTokenResult();
        if (!tokenResult.claims.admin && typeof tokenResult.claims.admin === 'undefined') {
            // claims.admin pode faltar mesmo para admin (allowlist/e-mail); tenta render
            // mesmo assim — o backend responde 403 e o painel mostra o estado de erro.
        }
    } catch (e) { /* segue e tenta render */ }
    renderHubPanel();
    startHubAutoRefresh();
}

function startHubAutoRefresh(intervalMs = 90_000) {
    stopHubAutoRefresh();
    _hubRefreshInterval = setInterval(() => {
        const panel = document.getElementById('panel-hub');
        if (panel && panel.classList.contains('active')) {
            renderHubPanel();
        }
    }, intervalMs);
}

function stopHubAutoRefresh() {
    if (_hubRefreshInterval) {
        clearInterval(_hubRefreshInterval);
        _hubRefreshInterval = null;
    }
}

// ── Deep links: submenu lateral -> seções do HUB ────────────

function hubFocus(sectionId, linkEl) {
    _hubPendingFocus = sectionId;
    showPanel('hub');
    if (linkEl) {
        document.querySelectorAll('.sub-link').forEach(el => el.classList.remove('active'));
        linkEl.classList.add('active');
    }
    // Fallback caso o render não conclua (ex.: usuário sem permissão).
    setTimeout(_hubApplyFocus, 1800);
}

function _hubApplyFocus() {
    if (!_hubPendingFocus) return;
    const el = document.getElementById(_hubPendingFocus);
    if (!el) return;
    const target = el.closest('.hub-card') || el;
    try { target.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { target.scrollIntoView(); }
    target.classList.add('hub-focus-flash');
    setTimeout(() => target.classList.remove('hub-focus-flash'), 2200);
    _hubPendingFocus = null;
}

// ── Copiloto flutuante (global) ─────────────────────────────

function toggleHubCopilotWidget() {
    const panel = document.getElementById('hub-copilot-widget-panel');
    const fab = document.getElementById('hub-copilot-fab');
    if (!panel || !fab) return;
    const willOpen = panel.hasAttribute('hidden');
    if (willOpen) {
        panel.removeAttribute('hidden');
        fab.setAttribute('aria-expanded', 'true');
        _hubRefreshWidgetBadge();
    } else {
        panel.setAttribute('hidden', '');
        fab.setAttribute('aria-expanded', 'false');
    }
}

function hubWidgetStart() {
    if (_hubWidgetTimer) return;
    setTimeout(_hubRefreshWidgetBadge, 5000);
    _hubWidgetTimer = setInterval(_hubRefreshWidgetBadge, 120_000);
}

async function _hubRefreshWidgetBadge() {
    if (!auth || !auth.currentUser) return;
    const badge = document.getElementById('hub-copilot-widget-badge');
    const alertEl = document.getElementById('hub-copilot-widget-alert');
    if (!badge && !alertEl) return;
    try {
        const overview = await _hubFetch('/api/hub/overview');
        const correlations = overview.correlations || [];
        const ranked = [...correlations].sort((a, b) =>
            (HUB_SEVERITY[a.severity]?.rank ?? 9) - (HUB_SEVERITY[b.severity]?.rank ?? 9));
        const urgent = ranked.filter(c => c.severity === 'critical' || c.severity === 'high');
        if (badge) {
            if (urgent.length) {
                badge.textContent = String(urgent.length);
                badge.style.display = 'inline-flex';
            } else {
                badge.style.display = 'none';
            }
        }
        if (alertEl) {
            if (ranked.length) {
                const top = ranked[0];
                const cfg = HUB_SEVERITY[top.severity] || HUB_SEVERITY.medium;
                alertEl.innerHTML = `<strong style="color:${cfg.color}">${escapeHtml(top.title || 'Alerta')}</strong><br>${escapeHtml(top.message || '')}`;
            } else {
                const level = (overview.health || {}).level;
                alertEl.textContent = level === 'ESTAVEL'
                    ? 'Nenhum alerta crítico. WAF e integridade do APK operando normalmente.'
                    : 'Nenhuma correlação ativa no momento.';
            }
        }
    } catch (e) {
        if (alertEl && !alertEl.dataset.filled) {
            alertEl.textContent = 'Não foi possível consultar o núcleo agora.';
        }
    }
}

async function hubWidgetLookup() {
    const input = document.getElementById('hub-copilot-widget-query');
    const out = document.getElementById('hub-copilot-widget-result');
    if (!input || !out) return;
    const query = input.value.trim();
    if (!query) { out.innerHTML = '<div class="hub-empty">Informe um UID ou e-mail.</div>'; return; }
    out.innerHTML = '<div class="hub-loading"><div class="secops-spinner"></div><p>Consultando o núcleo…</p></div>';
    try {
        const brief = await _hubFetch(`/api/hub/copilot?query=${encodeURIComponent(query)}`);
        out.innerHTML = _hubBriefHtml(brief);
    } catch (e) {
        out.innerHTML = `<div class="hub-empty" style="color:#f97316">${escapeHtml(e.message === 'HTTP 404' ? 'Usuário não encontrado.' : e.message)}</div>`;
    }
}
