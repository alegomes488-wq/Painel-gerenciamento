/**
 * ============================================================
 *  TAREFA 5.1 — Modo Manutencao (fonte de verdade unica)
 * ============================================================
 *
 *  O SITE (CineCash-por-IA/www/app.js) le `config/maintenance` com onValue e
 *  mostra o overlay quando o valor e verdadeiro. O painel precisa ler e gravar
 *  EXATAMENTE o mesmo no — nada de `settings/maintenance` ou `localStorage`.
 *
 *  Problema que este modulo resolve (confirmado por leitura no RTDB):
 *    - `config/maintenance = true` mantinha o site em manutencao;
 *    - o painel NAO possuia nenhuma escrita para esse no;
 *    - o botao "DESCONECTAR" dos cards de projeto so alterna
 *      `neural/nodes/<id>/health/override` (online|offline) — nao e manutencao.
 *
 *  Principios implementados:
 *    1. Listener registrado UMA VEZ (guarda de handle) e removido no logout.
 *    2. Estados SEPARADOS — falha de leitura/config NAO vira manutencao:
 *         MAINTENANCE_ACTIVE | SERVICE_OPERATIONAL
 *         CONFIG_LOAD_ERROR   | SERVICE_UNAVAILABLE
 *    3. Gravacao sempre via backend autenticado (server-side decide autorizacao).
 *    4. Erro de gravacao e VISIVEL (toast + re-sincronizacao com a verdade).
 *    5. Nada de estado de manutencao em cache/localStorage — sempre o RTDB.
 */

const MAINTENANCE_REF_PATH = 'config/maintenance';

// Estados possiveis do controle. NUNCA confundir CONFIG_LOAD_ERROR com
// MAINTENANCE_ACTIVE — e o que mantinha o painel "ok" enquanto o site caia.
const MAINTENANCE_STATES = {
    MAINTENANCE_ACTIVE: 'MAINTENANCE_ACTIVE',
    SERVICE_OPERATIONAL: 'SERVICE_OPERATIONAL',
    CONFIG_LOAD_ERROR: 'CONFIG_LOAD_ERROR',
    SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE'
};

// Handle do listener + ultimo estado conhecido. Modulo-level => unico por pagina.
let _maintUnsub = null;
let _maintListenerAtivo = false;
let _maintEstado = MAINTENANCE_STATES.SERVICE_OPERATIONAL;
let _maintValorConhecido = false;   // true = valor veio do RTDB (fonte de verdade)
let _maintEmVoo = false;            // trava contra clique duplo / POST simultaneo

/**
 * Estado legivel para a UI.
 */
function getMaintenanceState() {
    return {
        estado: _maintEstado,
        // null = desconhecido (leitura falhou). Nunca coercer para false.
        valor: _maintValorConhecido ? (_maintEstado === MAINTENANCE_STATES.MAINTENANCE_ACTIVE) : null,
        confiavel: _maintValorConhecido
    };
}

function _isBoolean(v) {
    return typeof v === 'boolean';
}

/**
 * Aplica o estado ao painel: checkbox, badge e texto de estado.
 */
function renderMaintenanceUI() {
    const { estado, valor, confiavel } = getMaintenanceState();

    const check = document.getElementById('maint-toggle');
    const badge = document.getElementById('maint-state-badge');
    const motivo = document.getElementById('maint-reason');
    const btn = document.getElementById('maint-apply');

    // Checkbox so pode refletir a verdade quando ela e confiavel.
    // Quando a leitura falhou: desmarca e BLOQUEIA o controle, para o operador
    // nao acreditar que desligou algo que nao foi lido.
    if (check) {
        check.checked = confiavel ? (valor === true) : false;
        check.disabled = !confiavel || _maintEmVoo;
    }

    if (motivo) {
        motivo.disabled = !confiavel || _maintEmVoo;
    }

    if (btn) {
        btn.disabled = !confiavel || _maintEmVoo;
    }

    // Rotulo do switch: precisa acompanhar o estado, senao o painel mostra
    // "DESLIGADA" com o switch marcado (rotulo invertido, o bug do painel
    // antigo no outro projeto).
    const label = document.getElementById('maint-toggle-label');
    if (label) {
        if (!confiavel) {
            label.textContent = 'ESTADO DESCONHECIDO';
        } else {
            label.textContent = valor === true
                ? 'Manutenção LIGADA'
                : 'Manutenção DESLIGADA';
        }
    }

    // TAREFA 5.3: o badge de texto em bloco saiu do HTML (o controle foi para
    // o card de projeto). O guard vira `if (badge)` em vez de `return`
    // antecipado — antes, um `return` aqui IMPEDIA o redesenho dos cards,
    // que e justamente o que mantem o botao de cada card sincronizado.
    if (badge) {
        badge.classList.remove(
            'maint-state-active', 'maint-state-ok',
            'maint-state-error', 'maint-state-unavailable'
        );

        let texto = '';
        let classe = '';

        switch (estado) {
            case MAINTENANCE_STATES.MAINTENANCE_ACTIVE:
                texto = 'MANUTENCAO ATIVA — SITE EXIBINDO OVERLAY';
                classe = 'maint-state-active';
                break;
            case MAINTENANCE_STATES.CONFIG_LOAD_ERROR:
                texto = 'ERRO AO LER CONFIG — ESTADO DESCONHECIDO';
                classe = 'maint-state-error';
                break;
            case MAINTENANCE_STATES.SERVICE_UNAVAILABLE:
                texto = 'BACKEND INDISPONIVEL — ESTADO DESCONHECIDO';
                classe = 'maint-state-unavailable';
                break;
            case MAINTENANCE_STATES.SERVICE_OPERATIONAL:
            default:
                texto = 'SISTEMA OPERACIONAL — SEM MANUTENCAO';
                classe = 'maint-state-ok';
                break;
        }

        badge.textContent = texto;
        badge.classList.add(classe);
    }

    // Os cards de projeto sao re-renderizados do zero a cada evento do RTDB
    // (renderWatchProjects -> innerHTML). O botao de manutencao mora no card,
    // entao precisa ser redesenhado junto para refletir o estado atual — e,
    // principalmente, para ser DESABILITADO enquanto ha leitura incerta ou
    // escrita em andamento.
    if (typeof renderWatchProjects === 'function') {
        try {
            renderWatchProjects();
        } catch (e) {
            console.warn('[MAINT] Falha ao redesenhar cards:', e && e.message);
        }
    }
}

/**
 * Botao de manutencao injetado em cada card de projeto (4a posicao da linha
 * ID | AGENT | ATIVAR/DESCONECTAR | MANUTENCAO).
 *
 * ALCANCE GLOBAL — leia antes de mexer: `config/maintenance` e UM no unico
 * compartilhado por todos os sites/apps. Nao existe manutencao por projeto no
 * modelo de dados, e o site (CineCash-por-IA/www/app.js) so le esse caminho.
 * Todos os cards mostram e alteram o MESMO valor. O `title` diz isso ao
 * operador para que derrubar o site a partir do card do APK nao pareca
 * derrubar apenas o APK.
 *
 * Por que o estado NAO fica no DOM: o card e recriado a cada evento do RTDB.
 * Guardar `checked`/`disabled` no elemento perderia o estado na proxima
 * atualizacao. Entao o botao e derivado do estado em memoria a cada render,
 * e o clique le o estado atual de novo (nunca confiar no rotulo do botao).
 */
function renderMaintenanceButton() {
    const { estado, valor, confiavel } = getMaintenanceState();

    const bloqueado = !confiavel || _maintEmVoo;

    let title;
    if (!confiavel) {
        title = 'Estado da manutencao DESCONHECIDO (leitura falhou: ' +
            estado + '). Clique para reconciliar — nada sera gravado sem confirmacao.';
    } else if (valor === true) {
        title = 'Manutencao ATIVA (config/maintenance = true). O site inteiro esta ' +
            'exibindo o overlay para TODOS os usuarios. Clique para DESLIGAR.';
    } else {
        title = 'Manutencao DESLIGADA (config/maintenance = false). Clique para ' +
            'ATIVAR — vai derrubar o site inteiro, nao apenas este app.';
    }

    const disAttr = bloqueado ? ' disabled' : '';
    const trackOn = 'var(--success)';
    const trackOff = 'var(--danger)';
    const thumbColor = 'var(--bg-elevated)';
    const disabledTrack = 'var(--border)';
    const disabledThumb = 'var(--text-muted)';

    // Um <button> real, NAO <label>+<input opacidade 0>. O input invisivel com
    // data-action fazia o clique cair no label/thumb (sem data-action) e
    // closest('[data-action]') devolvia null -> clique morto. Como os botoes
    // ID/AGENT, o alvo do clique precisa carregar o proprio data-action.
    const trackColor = bloqueado ? disabledTrack : (valor === true ? trackOn : trackOff);
    const thumbBg = bloqueado ? disabledThumb : thumbColor;
    const thumbLeft = valor === true ? '26px' : '3px';
    const opacity = bloqueado ? '0.5' : '1';
    const cursor = bloqueado ? 'not-allowed' : 'pointer';

    const estiloBotao = `
        display: inline-flex; align-items: center; gap: 0;
        box-sizing: border-box;
        width: 52px; height: 26px; padding: 0 4px;
        border: 0; margin: 0;
        background: ${trackColor};
        border-radius: 13px; position: relative;
        cursor: ${cursor}; opacity: ${opacity};
        transition: background 0.2s ease, box-shadow 0.2s ease, opacity 0.2s;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.05);
    `.replace(/\s+/g, ' ').trim();

    const estiloThumb = `
        position: absolute; top: 3px; left: ${thumbLeft};
        width: 20px; height: 20px; border-radius: 50%;
        background: ${thumbBg};
        box-shadow: 0 1px 4px rgba(0,0,0,0.4), 0 0 0 1px rgba(0,0,0,0.1);
        transition: left 0.18s cubic-bezier(0.25, 0.46, 0.45, 0.94),
                    background 0.18s ease, box-shadow 0.18s ease;
        will-change: left, background;
    `.replace(/\s+/g, ' ').trim();

    return `<button type="button" data-action="maintenance" role="switch" aria-checked="${valor === true}" aria-label="Modo manuten\u00e7\u00e3o" class="maint-switch" title="${escapeHtml(title)}" style="${estiloBotao}"${disAttr}>
        <span class="maint-thumb" style="${estiloThumb}"></span>
    </button>`;
}

/**
 * Clique no botao de manutencao do card.
 *
 * Le o estado ATUAL do modulo (nao o rotulo do botao, que pode estar
 * desatualizado se o card nao foi re-renderizado) e inverte.
 *
 * Regras que nao sao negociaveis:
 *  - leitura incerta => reconcilia pelo backend; se continuar incerta, CANCELA.
 *    Nunca grava por cima de um estado que nao deu para ler;
 *  - ATIVAR exige confirmacao explicita (derrubar o site e o dano maior);
 *  - DESATIVAR nunca exige confirmacao (a saida do modo manutencao precisa
 *    estar sempre disponivel, inclusive durante o incidente).
 */
async function toggleMaintenanceFromCard() {
    if (_maintEmVoo) {
        showToast('Gravacao em andamento. Aguarde.', 'warning');
        return false;
    }

    if (!getMaintenanceState().confiavel) {
        showToast(
            'Estado da manutencao desconhecido. Reconciliando com o servidor antes de alterar.',
            'warning'
        );
        await refreshMaintenanceFromBackend();
        if (!getMaintenanceState().confiavel) {
            showToast(
                'Nao foi possivel confirmar o estado atual. Nada foi gravado.',
                'error'
            );
            return false;
        }
    }

    const ligando = getMaintenanceState().valor !== true;

    if (ligando) {
        const ok = window.confirm(
            'ATIVAR o modo manutencao?\n\n' +
            'O site cinecash.com.br passara a exibir o overlay de manutencao ' +
            'para TODOS os usuarios ate este controle ser desligado.\n\n' +
            'Este controle e GLOBAL: vale para todos os apps e sites deste painel, ' +
            'nao apenas para este projeto.\n\n' +
            'Motivo: (nao informado — use o painel para registrar)'
        );
        if (!ok) {
            renderMaintenanceUI();
            return false;
        }
    }

    const gravado = await setMaintenance(ligando, '');
    if (!gravado) renderMaintenanceUI();
    return gravado;
}

/**
 * Callback do listener. Separado para ficar testavel e sem efeito colateral.
 */
function _applyMaintenanceSnapshot(snapshot) {
    const raw = snapshot.val();

    if (!_isBoolean(raw)) {
        // No ausente => falsy no JS do site => site opera normal.
        // String/número aqui é SUSPEITO (ex.: "true" deixado por bug anterior):
        // não tratamos como manutencao sem avisar, porque o site trata como
        // truthy. Marcamos estado desconhecido para forçar investigação.
        if (raw !== null && raw !== undefined) {
            console.warn('[MAINT] config/maintenance com tipo inesperado:', typeof raw, raw);
            _maintEstado = MAINTENANCE_STATES.CONFIG_LOAD_ERROR;
            _maintValorConhecido = false;
            renderMaintenanceUI();
            showToast(
                'config/maintenance com tipo invalido (' + typeof raw +
                '). Corrija no Firebase antes de confiar neste controle.',
                'error'
            );
            return;
        }

        _maintEstado = MAINTENANCE_STATES.SERVICE_OPERATIONAL;
        _maintValorConhecido = true;
        renderMaintenanceUI();
        return;
    }

    _maintValorConhecido = true;
    const novoEstado = raw
        ? MAINTENANCE_STATES.MAINTENANCE_ACTIVE
        : MAINTENANCE_STATES.SERVICE_OPERATIONAL;

    const mudou = novoEstado !== _maintEstado;
    _maintEstado = novoEstado;
    renderMaintenanceUI();

    if (mudou) {
        console.log('[MAINT] Estado alterado pelo RTDB ->', novoEstado, '(valor cru:', raw, ')');
        // Avisa o operador quando a manutencao LIGA sozinha (mudanca vinda de
        // outro painel, do Firebase Console ou de automacao). Derrubar o site
        // sem nenhum registro no painel era o sintoma original desta TAREFA 5.1.
        // Desligar NAO gera alerta de queda.
        if (novoEstado === MAINTENANCE_STATES.MAINTENANCE_ACTIVE) {
            // Alerta forte (warning persistente em vez do toast efemero de 4s),
            // porque derrubar o site sem registro no painel era o sintoma
            // original desta TAREFA 5.1.
            showToast(
                'MODO MANUTENCAO ATIVADO — o site passara a exibir o overlay para todos os usuarios.',
                'warning'
            );
        }
    }
}

/**
 * Erro do listener do RTDB (App Check, permissão, rede).
 * NAO declara manutencao. Declara CONFIG_LOAD_ERROR e mostra o motivo.
 */
function _applyMaintenanceError(err) {
    console.error('[MAINT] Erro no listener config/maintenance:', err && err.message);
    _maintEstado = MAINTENANCE_STATES.CONFIG_LOAD_ERROR;
    _maintValorConhecido = false;
    renderMaintenanceUI();
    showToast(
        'Nao foi possivel ler config/maintenance (' + ((err && err.message) || 'erro') +
        '). Isso NAO significa manutencao ativa.',
        'error'
    );
}

/**
 * Registra o listener em tempo real. Idempotente: chamar duas vezes nao cria
 * dois listeners (o que causaria render duplicado e estado inconsistente).
 */
function initMaintenanceListener() {
    if (_maintListenerAtivo) {
        console.log('[MAINT] Listener ja registrado — ignorando chamada duplicada.');
        return false;
    }

    if (!hubDb) {
        _maintEstado = MAINTENANCE_STATES.SERVICE_UNAVAILABLE;
        _maintValorConhecido = false;
        renderMaintenanceUI();
        return false;
    }

    _maintListenerAtivo = true;
    try {
        _maintUnsub = hubDb.ref(MAINTENANCE_REF_PATH).on(
            'value',
            _applyMaintenanceSnapshot,
            _applyMaintenanceError
        );
        console.log('[MAINT] Listener de tempo real registrado em', MAINTENANCE_REF_PATH);
        return true;
    } catch (e) {
        _maintListenerAtivo = false;
        _maintUnsub = null;
        console.error('[MAINT] Falha ao registrar listener:', e.message);
        _maintEstado = MAINTENANCE_STATES.CONFIG_LOAD_ERROR;
        _maintValorConhecido = false;
        renderMaintenanceUI();
        return false;
    }
}

/**
 * Remove o listener (logout / teardown). Idempotente.
 */
function stopMaintenanceListener() {
    if (!_maintListenerAtivo) return false;

    if (hubDb && _maintUnsub) {
        try {
            hubDb.ref(MAINTENANCE_REF_PATH).off('value', _maintUnsub);
            console.log('[MAINT] Listener removido.');
        } catch (e) {
            console.warn('[MAINT] Erro ao remover listener:', e && e.message);
        }
    }

    _maintUnsub = null;
    _maintListenerAtivo = false;
    _maintValorConhecido = false;
    _maintEstado = MAINTENANCE_STATES.SERVICE_OPERATIONAL;
    renderMaintenanceUI();
    return true;
}

/**
 * Le o estado direto do backend. Usado como reconciliacao quando o listener
 * falha — o painel continua sabendo a verdade sem write.
 */
async function refreshMaintenanceFromBackend() {
    try {
        if (!auth?.currentUser) throw new Error('nao autenticado');
        const idToken = await auth.currentUser.getIdToken();

        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/admin/maintenance`, {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${idToken}` }
        });
        const data = await resp.json().catch(() => ({}));

        if (!resp.ok) {
            throw new Error(data.detail || `HTTP ${resp.status}`);
        }

        // read_ok=false => o backend nao conseguiu ler. Nao assume manutencao.
        if (data.read_ok !== true || !_isBoolean(data.maintenance)) {
            _maintEstado = MAINTENANCE_STATES.CONFIG_LOAD_ERROR;
            _maintValorConhecido = false;
            renderMaintenanceUI();
            return;
        }

        _maintValorConhecido = true;
        _maintEstado = data.maintenance
            ? MAINTENANCE_STATES.MAINTENANCE_ACTIVE
            : MAINTENANCE_STATES.SERVICE_OPERATIONAL;
        renderMaintenanceUI();
    } catch (e) {
        const msg = (e && e.message) || 'erro';
        if (/indispon/i.test(msg) || /fetch|Failed to fetch|NetworkError/i.test(msg)) {
            _maintEstado = MAINTENANCE_STATES.SERVICE_UNAVAILABLE;
        } else {
            _maintEstado = MAINTENANCE_STATES.CONFIG_LOAD_ERROR;
        }
        _maintValorConhecido = false;
        renderMaintenanceUI();
    }
}

/**
 * Aplica a mudanca de manutencao via BACKEND (nunca escrita direta no RTDB).
 *
 * @param {boolean} enabled  estado desejado (booleano real)
 * @param {string}  reason   motivo opcional (auditoria)
 * @returns {Promise<boolean>} true se o RTDB confirmar o novo valor
 */
async function setMaintenance(enabled, reason) {
    if (typeof enabled !== 'boolean') {
        showToast('Valor invalido: use o controle, nao texto.', 'error');
        return false;
    }

    if (_maintEmVoo) {
        showToast('Gravacao em andamento. Aguarde.', 'warning');
        return false;
    }

    if (!getMaintenanceState().confiavel) {
        showToast(
            'Estado atual desconhecido (leitura falhou). Reconciliando antes de alterar.',
            'warning'
        );
        await refreshMaintenanceFromBackend();
        if (!getMaintenanceState().confiavel) {
            showToast('Nao foi possivel confirmar o estado atual. Gravacao cancelada.', 'error');
            return false;
        }
    }

    _maintEmVoo = true;
    renderMaintenanceUI();

    try {
        if (!auth?.currentUser) throw new Error('Nao autenticado');
        const idToken = await auth.currentUser.getIdToken();

        const resp = await fetch(`${BRASILHEXA_BACKEND_URL}/api/admin/maintenance`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${idToken}`
            },
            // confirm:true e exigido pelo backend apenas para ATIVAR.
            body: JSON.stringify({ enabled, confirm: true, reason: reason || '' })
        });

        const data = await resp.json().catch(() => ({}));

        if (!resp.ok) {
            throw new Error(data.detail || `HTTP ${resp.status}`);
        }

        if (!_isBoolean(data.confirmed) || data.confirmed !== enabled) {
            throw new Error(
                `confirmacao divergente: RTDB=${JSON.stringify(data.confirmed)} pedido=${enabled}`
            );
        }

        _maintValorConhecido = true;
        _maintEstado = enabled
            ? MAINTENANCE_STATES.MAINTENANCE_ACTIVE
            : MAINTENANCE_STATES.SERVICE_OPERATIONAL;
        renderMaintenanceUI();

        showToast(
            enabled
                ? 'Manutencao ATIVADA. O site deve exibir o overlay.'
                : 'Manutencao DESATIVADA. O site deve voltar ao normal.',
            enabled ? 'warning' : 'success'
        );
        return true;
    } catch (e) {
        // Falha de gravacao e VISIVEL e a UI volta a reflecting a verdade do RTDB.
        showToast('Falha ao gravar manutencao: ' + ((e && e.message) || 'erro'), 'error');
        await refreshMaintenanceFromBackend();
        return false;
    } finally {
        _maintEmVoo = false;
        renderMaintenanceUI();
    }
}

/**
 * REMVIDO na TAREFA 5.3 — applyMaintenanceFromUI()
 *
 * Esse handler lia `maint-toggle` e `maint-reason` do bloco de manutencao que
 * ficava em `panel-settings`. Como o controle foi para o card de projeto, os
 * dois elementos sairam do HTML e a funcao passou a resolver `alvo = false`
 * para sempre — isto e, um clique nela tentaria DESLIGAR a manutencao sem
 * perguntar nada, e sem trilha de motivo. Manter isso seria um botão fantasma
 * perigoso, nao codigo morto inofensivo.
 *
 * Substituída por toggleMaintenanceFromCard(), que le o estado do modulo
 * (fonte de verdade) em vez de um checkbox possivelmente desatualizado.
 */
