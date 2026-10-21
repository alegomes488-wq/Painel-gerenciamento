/* CYBERCORE — adaptador de apresentação. Não inicia agentes nem chama APIs.
 * Integração: window.CyberCoreAgentConsole.update(payload), após validar
 * a resposta no módulo autenticado, ou evento cybercore:agent-telemetry.
 * Mensagens no navegador não são prova de autenticidade do backend.
 */
(() => {
  'use strict';
  if (window.CyberCoreAgentConsole) return;
  const keys = ['financeiro', 'sentinel', 'auditor', 'fiscal'];
  const labels = {running: 'Em atividade', idle: 'Em espera', error: 'Falha informada', offline: 'Offline informado'};
  const liveLabels = {running: 'IA em atividade', idle: 'IA em espera', error: 'Falha reportada', offline: 'Offline'};
  const terminalLabels = {running: 'ACTIVE', idle: 'IDLE', error: 'ERROR', offline: 'OFFLINE'};
  const streamLabels = {waiting: 'Aguardando', running: 'Em andamento', complete: 'Concluído', error: 'Falha'};
  const records = new Map();
  const freshnessMs = 90000;
  const metricKey = /^[a-z][a-z0-9_]{0,23}$/;
  const reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const dt = new Intl.DateTimeFormat('pt-BR', {dateStyle: 'short', timeStyle: 'medium'});
  const clock = new Intl.DateTimeFormat('pt-BR', {timeStyle: 'medium'});
  const plain = (value, fallback, max = 600) => typeof value === 'string' && value.trim() ? value.trim().slice(0, max) : fallback;
  function stream(value) {
    return value && typeof value === 'object' && Object.hasOwn(streamLabels, value.state)
      ? {state: value.state, task: plain(value.task, 'Nenhuma descrição recebida.')}
      : {state: 'waiting', task: 'Nenhuma atividade informada.'};
  }
  function metrics(value) {
    const list = Array.isArray(value) ? value
      : value && typeof value === 'object'
        ? Object.entries(value).map(([key, item]) => ({key, label: key.replace(/_/g, ' '), value: item}))
        : [];
    const result = [];
    for (const item of list.slice(0, 6)) {
      if (!item || typeof item !== 'object' || !metricKey.test(item.key || '')) continue;
      if (!['string', 'number', 'boolean'].includes(typeof item.value)) continue;
      const text = String(item.value).trim().slice(0, 40);
      if (!text) continue;
      result.push({key: item.key, label: plain(item.label, item.key, 32), value: text});
    }
    return result;
  }
  function field(card, name, value) {
    const element = card.querySelector(`[data-field="${name}"]`);
    if (element) element.textContent = value;
  }
  function streamInto(element, text) {
    if (!element) return;
    if (element._streamTimer) { clearInterval(element._streamTimer); element._streamTimer = null; }
    const card = element.closest('.agent-console-card');
    if (reduceMotion || !element.offsetParent || text.length > 1200) {
      element.textContent = text;
      if (card) card.classList.remove('is-streaming');
      return;
    }
    element.textContent = '';
    if (card) card.classList.add('is-streaming');
    const step = Math.max(2, Math.ceil(text.length / 110));
    let index = 0;
    element._streamTimer = setInterval(() => {
      index = Math.min(text.length, index + step);
      element.textContent = text.slice(0, index);
      if (index >= text.length) {
        clearInterval(element._streamTimer);
        element._streamTimer = null;
        if (card) card.classList.remove('is-streaming');
      }
    }, 16);
  }
  function paintMetrics(card, record, recent) {
    for (const metric of record.metrics) {
      const element = card.querySelector(`[data-metric="${metric.key}"]`);
      if (element) element.textContent = metric.value;
    }
    const signals = card.querySelector('[data-metric="signals"]');
    if (signals) signals.textContent = String(record.history.length).padStart(2, '0');
    const grid = card.querySelector('[data-field="metric-grid"]');
    if (!grid) return;
    const cells = [
      ...record.metrics.map(metric => [metric.label, metric.value]),
      ['Sinais na sessão', String(record.history.length)],
      ['Estado do agente', recent ? labels[record.state] : 'Sinal desatualizado'],
      ['Monitoramento', recent ? streamLabels[record.monitor.state] : 'Último estado'],
      ['Análise', recent ? streamLabels[record.analysis.state] : 'Último estado'],
      ['Último sinal', clock.format(record.at)],
      ['Qualidade do sinal', recent ? 'Recente' : 'Desatualizado']
    ];
    grid.replaceChildren(...cells.map(([label, value]) => {
      const cell = document.createElement('div');
      cell.className = 'agent-metric-cell';
      const name = document.createElement('small');
      name.textContent = label;
      const content = document.createElement('b');
      content.textContent = value;
      cell.append(name, content);
      return cell;
    }));
  }
  function paintLive(card, record, recent) {
    const processing = recent && record.state === 'running';
    card.classList.toggle('is-processing', processing);
    const chip = card.querySelector('[data-field="live-chip"]');
    if (chip) chip.dataset.state = recent ? record.state : 'stale';
    field(card, 'live-label', !recent
      ? 'Sem sinal recente'
      : record.analysis.state === 'running' ? 'IA analisando dados' : liveLabels[record.state]);
    const terminal = card.querySelector('[data-field="terminal-state"]');
    if (terminal) {
      terminal.dataset.state = recent ? record.state : 'stale';
      terminal.textContent = !recent ? 'STALE' : record.analysis.state === 'running' ? 'PROCESSING' : terminalLabels[record.state];
    }
  }
  function refresh() {
    let reporting = 0, analyzing = 0;
    const now = Date.now();
    for (const key of keys) {
      const record = records.get(key);
      if (!record) continue;
      const card = document.querySelector(`[data-agent="${key}"]`);
      if (!card) continue;
      const recent = now - record.at <= freshnessMs;
      const state = card.querySelector('[data-field="state"]');
      state.dataset.state = recent ? record.state : 'stale';
      state.textContent = recent ? labels[record.state] : 'Sinal desatualizado';
      field(card, 'freshness', recent ? 'Sinal recente' : 'Sem sinal recente · último estado abaixo');
      field(card, 'monitor-state', recent ? streamLabels[record.monitor.state] : 'Último estado');
      field(card, 'analysis-state', recent ? streamLabels[record.analysis.state] : 'Último estado');
      paintLive(card, record, recent);
      paintMetrics(card, record, recent);
      if (recent) {
        reporting++;
        if (record.state === 'running' && record.analysis.state === 'running') analyzing++;
      }
    }
    for (const [id, count] of [['reporting', reporting], ['analyzing', analyzing], ['pending', keys.length - reporting]]) {
      const element = document.getElementById(`agent-count-${id}`);
      if (element) element.textContent = String(count).padStart(2, '0');
    }
    const notice = document.getElementById('agent-telemetry-notice');
    if (notice) {
      const message = reporting
        ? `${reporting} de 4 agentes com sinal recente. Os cards exibem o último estado recebido; abra os detalhes para consultar as evidências.`
        : records.size
          ? 'Nenhum sinal recente. Os últimos dados foram mantidos para consulta e não confirmam atividade atual.'
          : 'Aguardando telemetria dos agentes. Esta tela não inicia execuções; os estados serão atualizados quando os módulos enviarem dados.';
      if (notice.textContent !== message) notice.textContent = message;
    }
  }
  function update(payload) {
    if (!payload || typeof payload !== 'object' || !keys.includes(payload.agent) || !Object.hasOwn(labels, payload.state)) return false;
    if (typeof payload.observedAt !== 'string') return false;
    // ISO 8601 com fuso explícito evita interpretar horários locais ambíguos.
    if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(payload.observedAt)) return false;
    const at = Date.parse(payload.observedAt);
    if (!Number.isFinite(at) || at > Date.now() + 5000) return false;
    const previous = records.get(payload.agent);
    if (previous && at <= previous.at) return false;
    const card = document.querySelector(`[data-agent="${payload.agent}"]`);
    if (!card) return false;
    const incomingMetrics = metrics(payload.metrics);
    const record = {
      at, state: payload.state, monitor: stream(payload.monitoring), analysis: stream(payload.analysis),
      activity: plain(payload.activity, 'Sinal recebido sem descrição de atividade.'),
      result: plain(payload.result, 'Nenhum resultado informado neste sinal.', 1200),
      evidence: plain(payload.evidence, 'Nenhuma evidência informada neste sinal.', 1600),
      metrics: incomingMetrics.length ? incomingMetrics : previous ? previous.metrics : [],
      history: previous ? previous.history.slice(0, 7) : []
    };
    record.history.unshift({at, text: `${labels[record.state]} — ${record.activity}`});
    records.set(payload.agent, record);
    const legacy = document.getElementById(`ai-${payload.agent}-status`);
    if (legacy) legacy.textContent = record.activity;
    field(card, 'monitor-task', record.monitor.task);
    field(card, 'analysis-task', record.analysis.task);
    streamInto(card.querySelector('[data-field="result"]'), record.result);
    field(card, 'evidence', record.evidence);
    const time = card.querySelector('[data-field="updated"]');
    time.dateTime = new Date(at).toISOString();
    time.textContent = dt.format(at);
    const history = card.querySelector('[data-field="history"]');
    history.replaceChildren(...record.history.map(event => {
      const li = document.createElement('li');
      const when = document.createElement('time');
      when.dateTime = new Date(event.at).toISOString();
      when.textContent = clock.format(event.at);
      li.append(when, document.createTextNode(event.text));
      return li;
    }));
    refresh();
    return true;
  }
  function selectTab(tab) {
    const card = tab.closest('.agent-console-card');
    if (!card) return;
    card.querySelectorAll('.agent-tab').forEach(item => {
      const active = item === tab;
      item.classList.toggle('active', active);
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
    });
    card.querySelectorAll('.agent-tab-panel').forEach(panel => {
      panel.hidden = panel.dataset.panel !== tab.dataset.tab;
    });
  }
  window.CyberCoreAgentConsole = Object.freeze({update});
  window.addEventListener('cybercore:agent-telemetry', event => update(event.detail));
  document.addEventListener('click', event => {
    const tab = event.target.closest('.agent-tab');
    if (tab) selectTab(tab);
  });
  document.addEventListener('keydown', event => {
    const tab = event.target.closest('.agent-tab');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...tab.closest('.agent-console-card').querySelectorAll('.agent-tab')];
    const index = tabs.indexOf(tab);
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? tabs.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault();
    tabs[next].focus();
    selectTab(tabs[next]);
  });
  window.setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  document.addEventListener('visibilitychange', refresh);
  refresh();
})();
