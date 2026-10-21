/**
 * TAREFA 5.1 — este código procurava `#toggle-maintenance`, elemento que NUNCA
 * existiu no index.html (verificado: 0 ocorrências de "manuten" no HTML antigo).
 * Era código morto: o painel exibia "sistema ok" enquanto o site ficava em
 * manutenção, porque nada renderizava o estado real.
 *
 * Agora delega ao módulo de manutenção, que tem listener próprio em
 * `config/maintenance` e separa MAINTENANCE_ACTIVE / SERVICE_OPERATIONAL /
 * CONFIG_LOAD_ERROR / SERVICE_UNAVAILABLE.
 *
 * Mantido como ponto de entrada porque main.js chama updateStatusIndicators()
 * a cada evento do listener de `config`.
 */
function updateStatusIndicators() {
    if (typeof renderMaintenanceUI === 'function') {
        renderMaintenanceUI();
    }
}

function loadConfigUI() {
    try {
        const cfg = rtState.config || {};
        const cpmEl = document.getElementById('audit-cpm');
        const waEl = document.getElementById('audit-whatsapp');
        if (cpmEl && cfg.cpm !== undefined && cfg.cpm !== null) {
            cpmEl.value = Number(cfg.cpm).toFixed(2);
        }
        if (waEl && cfg.adminWhatsapp !== undefined && cfg.adminWhatsapp !== null) {
            waEl.value = cfg.adminWhatsapp;
        }
    } catch (e) {
        console.warn('[Settings] Erro ao carregar config UI:', e);
    }
}

async function saveAuditParameters() {
    const cpm = parseFloat(document.getElementById('audit-cpm')?.value || 0);
    const wa = document.getElementById('audit-whatsapp')?.value.trim();
    // TAREFA 3.4: savagem via endpoint backend com validação (não direto no RTDB)
    try {
        if (!auth?.currentUser) throw new Error('Não autenticado');
        const idToken = await auth.currentUser.getIdToken();
        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/admin/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
            body: JSON.stringify({ cpm, adminWhatsapp: wa })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            throw new Error(data.detail || `HTTP ${resp.status}`);
        }
        showToast("Configurações salvas!", "success");
    } catch (e) {
        showToast("Erro ao salvar: " + (e.message || e), "error");
    }
}
