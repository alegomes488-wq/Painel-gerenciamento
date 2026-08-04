function updateStatusIndicators() {
    const isMaint = rtState.config?.maintenance || false;
    const check = document.getElementById('toggle-maintenance');
    if (check) check.checked = isMaint;
}

async function saveAuditParameters() {
    const cpm = parseFloat(document.getElementById('audit-cpm')?.value || 0);
    const wa = document.getElementById('audit-whatsapp')?.value.trim();
    try {
        await hubDb.ref('config').update({ cpm, adminWhatsapp: wa });
        showToast("Configurações salvas!", "success");
    } catch (e) {
        showToast("Erro ao salvar.", "error");
    }
}
