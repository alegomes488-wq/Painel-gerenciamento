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
  const streamLabels = {waiting: 'Aguardando', running: 'Em andamento', complete: 'Concluído', error: 'Falha'};
  const records = new Map();
  const freshnessMs = 90000;
  const dt = new Intl.DateTimeFormat('pt-BR', {dateStyle: 'short', timeStyle: 'medium'});
  const clock = new Intl.DateTimeFormat('pt-BR', {timeStyle: 'medium'});
  const plain = (value, fallback, max = 600) => typeof value === 'string' && value.trim() ? value.trim().slice(0, max) : fallback;
  function stream(value) {
    return value && typeof value === 'object' && Object.hasOwn(streamLabels, value.state)
      ? {state: value.state, task: plain(value.task, 'Nenhuma descrição recebida.')}
      : {state: 'waiting', task: 'Nenhuma atividade informada.'};
  }
  function field(card, name, value) { card.querySelector(`[data-field="${name}"]`).textContent = value; }
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
    const record = {
      at, state: payload.state, monitor: stream(payload.monitoring), analysis: stream(payload.analysis),
      activity: plain(payload.activity, 'Sinal recebido sem descrição de atividade.'),
      result: plain(payload.result, 'Nenhum resultado informado neste sinal.', 1200),
      evidence: plain(payload.evidence, 'Nenhuma evidência informada neste sinal.', 1600),
      history: previous ? previous.history.slice(0, 7) : []
    };
    record.history.unshift({at, text: `${labels[record.state]} — ${record.activity}`});
    records.set(payload.agent, record);
    const legacy = document.getElementById(`ai-${payload.agent}-status`);
    if (legacy) legacy.textContent = record.activity;
    field(card, 'monitor-task', record.monitor.task);
    field(card, 'analysis-task', record.analysis.task);
    field(card, 'result', record.result);
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
  window.CyberCoreAgentConsole = Object.freeze({update});
  window.addEventListener('cybercore:agent-telemetry', event => update(event.detail));
  window.setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  document.addEventListener('visibilitychange', refresh);
  refresh();
})();
