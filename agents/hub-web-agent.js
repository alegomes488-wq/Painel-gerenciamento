/**
 * ============================================================
 *  Cyber Core IA — Agente WEB do Painel HUB
 *  Coleta Core Web Vitals (LCP/INP/CLS/TTFB) e taxa de erro
 *  HTTP (4xx/5xx) no navegador e envia para POST /api/hub/events.
 *
 *  Uso (no site/PWA — página principal):
 *    <script src="https://SEU-BACKEND/hub-web-agent.js"
 *            data-backend="https://SEU-BACKEND"
 *            data-token="HUB_WEB_TOKEN"
 *            data-source="cinecash-web"></script>
 *
 *  O token (HUB_WEB_TOKEN) é restrito à seção "web" no backend —
 *  não dá acesso a leitura nem a eventos de segurança. Por ser
 *  estático no navegador, trate-o como DSN de telemetria.
 * ============================================================
 */
(function () {
    'use strict';

    var script = document.currentScript;
    var CFG = {
        backend: ((script && script.dataset.backend) || '').replace(/\/$/, ''),
        token: (script && script.dataset.token) || '',
        source: (script && script.dataset.source) || 'web-agent',
        intervalMs: parseInt((script && script.dataset.interval) || '60000', 10) || 60000,
    };
    if (!CFG.backend || !CFG.token) {
        console.warn('[hub-agent] data-backend/data-token ausentes — agente desativado.');
        return;
    }

    var state = { lcp: null, inp: null, cls: 0, ttfb: null, httpTotal: 0, http4xx: 0, http5xx: 0 };

    // ── TTFB (Navigation Timing) ─────────────────────────────
    try {
        var navs = performance.getEntriesByType && performance.getEntriesByType('navigation');
        if (navs && navs.length) state.ttfb = Math.round(navs[0].responseStart);
    } catch (e) { /* noop */ }

    // ── LCP ──────────────────────────────────────────────────
    try {
        new PerformanceObserver(function (list) {
            list.getEntries().forEach(function (en) { state.lcp = Math.round(en.startTime); });
        }).observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (e) { /* navegador sem suporte */ }

    // ── CLS ──────────────────────────────────────────────────
    try {
        new PerformanceObserver(function (list) {
            list.getEntries().forEach(function (en) {
                if (!en.hadRecentInput) state.cls += en.value;
            });
        }).observe({ type: 'layout-shift', buffered: true });
    } catch (e) { /* noop */ }

    // ── INP (pior interação da janela) ───────────────────────
    try {
        new PerformanceObserver(function (list) {
            var worst = 0;
            list.getEntries().forEach(function (en) { worst = Math.max(worst, en.duration || 0); });
            if (worst > 0) state.inp = Math.round(worst);
        }).observe({ type: 'event', durationThreshold: 40, buffered: true });
    } catch (e) { /* noop */ }

    // ── Wrap de fetch: conta 4xx/5xx (ignora o próprio agente) ─
    if (window.fetch) {
        var origFetch = window.fetch;
        window.fetch = function () {
            var args = arguments;
            return origFetch.apply(this, args).then(function (resp) {
                try {
                    var url = (resp && resp.url) || (typeof args[0] === 'string' ? args[0] : '');
                    // ignora apenas as próprias chamadas de telemetry do agente
                    if (url.indexOf('/api/hub') === -1 && resp && resp.status) {
                        state.httpTotal++;
                        if (resp.status >= 500) state.http5xx++;
                        else if (resp.status >= 400) state.http4xx++;
                    }
                } catch (e) { /* noop */ }
                return resp;
            });
        };
    }

    function send() {
        var data = {};
        if (state.lcp != null) data.lcp_ms = state.lcp;
        if (state.inp != null) data.inp_ms = state.inp;
        if (state.cls != null) data.cls = Math.round(state.cls * 1000) / 1000;
        if (state.ttfb != null) data.ttfb_ms = state.ttfb;
        if (state.httpTotal > 0) {
            data.error_rate_5xx = Math.round((state.http5xx / state.httpTotal) * 10000) / 100;
            data.error_rate_4xx = Math.round((state.http4xx / state.httpTotal) * 10000) / 100;
        }
        // janela zerada após cada envio (taxas por intervalo, não acumuladas)
        state.httpTotal = 0; state.http4xx = 0; state.http5xx = 0;
        if (!Object.keys(data).length) return;
        try {
            fetch(CFG.backend + '/api/hub/events', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Hub-Agent-Secret': CFG.token },
                body: JSON.stringify({ section: 'web', source: CFG.source, data: data }),
                keepalive: true,
            }).catch(function () { /* telemetry nunca derruba a página */ });
        } catch (e) { /* noop */ }
    }

    setInterval(send, CFG.intervalMs);
    // Última janela ao sair da página (best-effort com keepalive)
    window.addEventListener('pagehide', function () {
        if (document.visibilityState === 'hidden') send();
    });
})();
