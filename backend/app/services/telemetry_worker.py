"""Worker de telemetria — Central de Agentes (Financeiro, Sentinel, Auditor, Fiscal).

Coleta periódica do RTDB e dos serviços locais e publica sinais no buffer SSE
(app.routers.telemetry). O console (agent-console.js) exibe apenas o que chegar
por aqui; este worker NÃO executa ações, apenas observa/anisa/relata.

Habilitação: TELEMETRY_WORKER=true (padrão). Intervalo: TELEMETRY_INTERVAL (s, padrão 30).
O console considera sinal "recente" por 90s — intervalo padrão garante 3 emissões.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from app.routers import telemetry

logger = logging.getLogger("telemetry.worker")

ENABLED = os.environ.get("TELEMETRY_WORKER", "true").lower() in ("1", "true", "yes")
INTERVAL = max(10, int(os.environ.get("TELEMETRY_INTERVAL", "30")))

ALLOWED_AMOUNTS_DEFAULT = [0.5, 3.0, 5.0, 10.0, 50.0]
VALID_PIX_TYPES = {"CPF", "CNPJ", "EMAIL", "PHONE", "EVP"}

_task: asyncio.Task | None = None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Nexus Intel (compartilhado entre todos os agentes) ─────────────────────
_NEXUS_INTEL = None
_NEXUS_INTEL_AT = None


def _load_nexus_intel():
    global _NEXUS_INTEL, _NEXUS_INTEL_AT
    from datetime import datetime as _dt
    from firebase_admin import db
    from app.services import nexus_intel

    now = _dt.now()
    if _NEXUS_INTEL is not None and _NEXUS_INTEL_AT is not None and (now - _NEXUS_INTEL_AT).total_seconds() < 10:
        return _NEXUS_INTEL

    logs_nexus = db.reference("logs/nexus").get() or {}
    users = db.reference("users").get() or {}
    pending = db.reference("admin/pending_withdrawals").get() or {}

    intel = nexus_intel.analyze_nexus(logs_nexus, users, now=now)
    audit = nexus_intel.audit_financial_consistency(intel, users, pending, now=now)
    plan = nexus_intel.build_action_plan(intel, audit, {"pending_count": len(pending)}, now=now)

    _NEXUS_INTEL = {
        "intel": intel,
        "audit": audit,
        "plan": plan,
        "users": users,
        "pending": pending,
    }
    _NEXUS_INTEL_AT = now
    return _NEXUS_INTEL


# ─── Financeiro: fluxo de caixa e pagamentos ───────────────────────────────
def _snapshot_financeiro() -> dict:
    from firebase_admin import db
    from app.services import nexus_intel

    pending = db.reference("admin/pending_withdrawals").get() or {}
    cfg = db.reference("config/withdrawals").get() or {}
    allowed = cfg.get("allowedAmounts") or ALLOWED_AMOUNTS_DEFAULT

    try:
        ctx = _load_nexus_intel()
        intel = ctx["intel"]
        audit = ctx["audit"]
    except Exception:
        intel = {"recent_24h": 0, "last_seen_at": None, "findings": []}
        audit = {"findings": []}

    nexus_text = nexus_intel.summary_text(intel)
    nexus_flag = len(intel.get("findings", [])) + len(audit.get("findings", []))

    n = len(pending)
    total = 0.0
    for w in pending.values():
        if isinstance(w, dict):
            try:
                total += float(w.get("amount") or 0)
            except (TypeError, ValueError):
                pass

    if n == 0:
        if nexus_flag > 0:
            return dict(
                state="running",
                mon_state="running", mon_task="Nenhuma solicitação de pagamento na fila, mas há achados no Nexus.",
                ana_state="running", ana_task=f"{nexus_flag} alerta(s) Nexus/Auditoria a filtrar.",
                activity=f"Fila vazia em observação. {nexus_text}",
                result=f"Sem saques pendentes, porém {nexus_flag} alerta(s) do ecossistema sob filtragem.",
                evidence=f"Fonte: admin/pending_withdrawals (vazio). {nexus_text} Ciclo {_iso_now()}.",
                metrics=[
                    {"key": "pending", "label": "Saques pendentes", "value": 0},
                    {"key": "amount", "label": "Valor pendente", "value": "R$ 0,00"},
                ],
            )
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhuma solicitação de pagamento na fila.",
            ana_state="waiting", ana_task="Sem movimentação para comparar neste ciclo.",
            activity=f"Fila de saques vazia — nada a coletar agora. {nexus_text}",
            result="Fluxo estável: nenhum saque aguardando aprovação.",
            evidence=f"Fonte: admin/pending_withdrawals (vazio). {nexus_text} Ciclo {_iso_now()}.",
            metrics=[
                {"key": "pending", "label": "Saques pendentes", "value": 0},
                {"key": "amount", "label": "Valor pendente", "value": "R$ 0,00"},
            ],
        )

    if n == 0:
        if nexus_flag > 0:
            return dict(
                state="running",
                mon_state="running", mon_task="Nenhuma solicitação de pagamento na fila, mas há achados no Nexus.",
                ana_state="running", ana_task=f"{nexus_flag} alerta(s) Nexus/Auditoria a filtrar.",
                activity=f"Fila vazia em observação. {nexus_text}",
                result=f"Sem saques pendentes, porém {nexus_flag} alerta(s) do ecossistema sob filtragem.",
                evidence=f"Fonte: admin/pending_withdrawals (vazio). {nexus_text} Ciclo {_iso_now()}.",
                metrics=[
                    {"key": "pending", "label": "Saques pendentes", "value": 0},
                    {"key": "amount", "label": "Valor pendente", "value": "R$ 0,00"},
                ],
            )
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhuma solicitação de pagamento na fila.",
            ana_state="waiting", ana_task="Sem movimentação para comparar neste ciclo.",
            activity=f"Fila de saques vazia — nada a coletar agora. {nexus_text}",
            result="Fluxo estável: nenhum saque aguardando aprovação.",
            evidence=f"Fonte: admin/pending_withdrawals (vazio). {nexus_text} Ciclo {_iso_now()}.",
            metrics=[
                {"key": "pending", "label": "Saques pendentes", "value": 0},
                {"key": "amount", "label": "Valor pendente", "value": "R$ 0,00"},
            ],
        )

    divergentes = [
        wid for wid, w in pending.items()
        if isinstance(w, dict) and w.get("amount") not in allowed
    ]
    if divergentes:
        mon_state, ana_state = "running", "error"
        ana_task = f"{len(divergentes)} valor(es) fora da lista permitida."
        result = f"{n} saque(s) pendentes (R$ {total:.2f}); divergência de valor em {len(divergentes)}."
        evidence = "IDs: " + ", ".join(divergentes[:5]) + f" | Permitidos: {allowed}"
    else:
        mon_state, ana_state = "running", "running"
        ana_task = "Valores conferidos com a lista permitida — sem divergência."
        result = f"{n} saque(s) pendentes somando R$ {total:.2f}, todos dentro do permitido."
        evidence = f"Fonte: admin/pending_withdrawals | Permitidos: {allowed}"

    fin_text = nexus_intel.plan_summary(ctx["plan"]) if ctx else ""
    if fin_text:
        nexus_text = f"{nexus_text} {fin_text}"

    return dict(
        state="running",
        mon_state=mon_state, mon_task=f"{n} solicitação(ões) de pagamento em observação.",
        ana_state=ana_state, ana_task=ana_task,
        activity=f"Coleta de entradas, saídas e solicitações ({n} pendente(s)). {nexus_text}",
        result=result, evidence=f"{evidence}. {nexus_text}",
        metrics=[
            {"key": "pending", "label": "Saques pendentes", "value": n},
            {"key": "amount", "label": "Valor pendente", "value": f"R$ {total:.2f}"},
        ],
    )


# ─── Sentinel: segurança e disponibilidade ─────────────────────────────────
def _snapshot_sentinel() -> dict:
    from app.services.secops_agent import SecOpsSentinelAgent
    from app.services import nexus_intel

    try:
        ctx = _load_nexus_intel()
        intel = ctx["intel"]
    except Exception:
        intel = {"findings": [], "total_reports": 0, "recent_24h": 0}

    nexus_text = nexus_intel.summary_text(intel)
    nexus_findings = intel.get("findings", [])

    audit = SecOpsSentinelAgent.audit_system_security()
    checks = audit.get("audit_results") or []
    falhas = [c.get("item", "?") for c in checks if c.get("status") == "FAIL"]
    warns = [c.get("item", "?") for c in checks if c.get("status") == "WARN"]

    if falhas:
        activity = "Checkup de integridade de chaves, conexões e configurações."
        result = "Risco observado: " + ", ".join(falhas[:4])
        evidence = f"Fonte: audit_system_security | WARNs: {', '.join(warns[:4]) or 'nenhum'}"
        if nexus_findings:
            activity = f"Varredura de identidade e relatos do Nexus ({len(nexus_findings)} alerta(s)). {nexus_text}"
            result = f"Infra em alerta + Nexus: {len(nexus_findings)} achado(s) de integridade/duplicidade."
            evidence = f"{evidence}. {nexus_text}"
        return dict(
            state="error",
            mon_state="running", mon_task=f"{len(checks)} verificações de segurança coletadas.",
            ana_state="error", ana_task=f"Falha em {len(falhas)} verificação(ões) de segurança.",
            activity=activity,
            result=result,
            evidence=evidence,
            metrics=[
                {"key": "threats", "label": "Ameaças bloqueadas", "value": len(falhas) + len(nexus_findings)},
                {"key": "alert", "label": "Nível de alerta", "value": "Crítico"},
            ],
        )

    if nexus_findings:
        critical = sum(1 for f in nexus_findings if f["severity"] == "critical")
        high = sum(1 for f in nexus_findings if f["severity"] == "high")
        severity = "crítico(s)" if critical else ("alto(s)" if high else "observado(s)")
        return dict(
            state="error" if critical else "running",
            mon_state="running", mon_task=f"{len(checks)} verificações de segurança em andamento.",
            ana_state="error" if critical else "running",
            ana_task=f"{len(nexus_findings)} achado(s) de identidade/duplicidade ({severity}).",
            activity=f"Varredura de identidade e relatos do Nexus. {nexus_text}",
            result=f"Sentinel identificou {len(nexus_findings)} alerta(s) com base nos relatos e no cadastro de usuários.",
            evidence=f"Fonte: logs/nexus + users. {nexus_text}",
            metrics=[
                {"key": "threats", "label": "Ameaças bloqueadas", "value": len(nexus_findings)},
                {"key": "alert", "label": "Nível de alerta", "value": "Crítico" if critical else ("Alto" if high else "Médio")},
            ],
        )

    return dict(
        state="running",
        mon_state="running", mon_task=f"{len(checks)} verificações de segurança em andamento.",
        ana_state="running", ana_task="Sem anomalia identificada neste ciclo.",
        activity=f"Disponibilidade e eventos de segurança monitorados. {nexus_text}",
        result=f"Configuração íntegra — {len(checks)} verificações OK, {len(warns)} aviso(s).",
        evidence=f"Fonte: audit_system_security (chaves, webhook, app check, n8n). {nexus_text}",
        metrics=[
            {"key": "threats", "label": "Ameaças bloqueadas", "value": 0},
            {"key": "alert", "label": "Nível de alerta", "value": "Baixo"},
        ],
    )


# ─── Auditor: integridade das operações ────────────────────────────────────
def _snapshot_auditor() -> dict:
    from firebase_admin import db
    from app.services import nexus_intel

    try:
        ctx = _load_nexus_intel()
        intel = ctx["intel"]
        audit_nexus = ctx["audit"]
    except Exception:
        intel = {"recent_24h": 0, "last_seen_at": None}
        audit_nexus = {"findings": []}

    nexus_text = nexus_intel.summary_text(intel)
    audit_findings = audit_nexus.get("findings", [])

    logs = db.reference("logs/financial").get() or {}
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    recentes = []
    pagos_por_wid: dict[str, int] = {}
    for lid, ev in (logs or {}).items():
        if not isinstance(ev, dict):
            continue
        ts = ev.get("timestamp") or 0
        if now_ms - ts <= 86_400_000:
            recentes.append(ev)
            if ev.get("type") == "withdrawal_paid":
                wid = ev.get("wid", "")
                pagos_por_wid[wid] = pagos_por_wid.get(wid, 0) + 1

    duplicados = [wid for wid, c in pagos_por_wid.items() if c > 1]

    if duplicados:
        return dict(
            state="error",
            mon_state="running", mon_task=f"{len(recentes)} evento(s) financeiro(s) nas últimas 24h.",
            ana_state="error", ana_task=f"{len(duplicados)} pagamento(s) com registro duplicado.",
            activity="Conferência de consistência e duplicidades da trilha de auditoria.",
            result="Duplicidade detectada em pagamento(s): " + ", ".join(duplicados[:5]),
            evidence=f"Fonte: logs/financial | Eventos 24h: {len(recentes)}. {nexus_text}",
            metrics=[
                {"key": "errors", "label": "Erros identificados", "value": len(duplicados)},
                {"key": "scan", "label": "Status da varredura", "value": "Duplicidade detectada"},
            ],
        )
    if not recentes and not audit_findings:
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhum evento financeiro nas últimas 24h.",
            ana_state="waiting", ana_task="Sem trilha nova para conferir.",
            activity=f"Trilha de auditoria sem eventos recentes. {nexus_text}",
            result="Nenhuma operação registrada nas últimas 24 horas.",
            evidence=f"Fonte: logs/financial (últimas 24h vazias). {nexus_text}",
            metrics=[
                {"key": "errors", "label": "Erros identificados", "value": 0},
                {"key": "scan", "label": "Status da varredura", "value": "Ocioso"},
            ],
        )
    if audit_findings:
        high = sum(1 for f in audit_findings if f["severity"] in ("critical", "high"))
        return dict(
            state="error" if high else "running",
            mon_state="running", mon_task=f"{len(recentes)} evento(s) financeiro(s) nas últimas 24h.",
            ana_state="error" if high else "running",
            ana_task=f"Segunda filtragem: {len(audit_findings)} inconsistência(s) Nexus x ledger.",
            activity=f"Conferência cruzada entre Nexus, usuários e saques pendentes. {nexus_text}",
            result=f"Auditor identificou {len(audit_findings)} ponto(s) a esclarecer.",
            evidence=f"Fonte: logs/nexus + users + admin/pending_withdrawals. {nexus_text}",
            metrics=[
                {"key": "errors", "label": "Erros identificados", "value": len(audit_findings)},
                {"key": "scan", "label": "Status da varredura", "value": "Inconsistências encontradas"},
            ],
        )
    if not recentes:
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhum evento financeiro nas últimas 24h.",
            ana_state="waiting", ana_task="Sem trilha nova para conferir.",
            activity=f"Trilha de auditoria sem eventos recentes. {nexus_text}",
            result="Nenhuma operação registrada nas últimas 24 horas.",
            evidence=f"Fonte: logs/financial (últimas 24h vazias). {nexus_text}",
            metrics=[
                {"key": "errors", "label": "Erros identificados", "value": 0},
                {"key": "scan", "label": "Status da varredura", "value": "Ocioso"},
            ],
        )
    return dict(
        state="running",
        mon_state="running", mon_task=f"{len(recentes)} evento(s) financeiro(s) coletados (24h).",
        ana_state="running", ana_task="Sem duplicidade nem inconsistência encontrada.",
        activity=f"Registros de operações e trilhas de auditoria conferidos. {nexus_text}",
        result=f"{len(recentes)} evento(s) nas últimas 24h, todos consistentes.",
        evidence=f"Fonte: logs/financial | Pagamentos únicos: {len(pagos_por_wid)}. {nexus_text}",
        metrics=[
            {"key": "errors", "label": "Erros identificados", "value": 0},
            {"key": "scan", "label": "Status da varredura", "value": "Varrendo logs (24h)"},
        ],
    )


# ─── Hub: métricas de API para o painel HUB ────────────────────────────────
def _snapshot_hub() -> dict:
    """Drena o buffer de métricas de API e publica a seção 'api' do HUB."""
    from app.services import hub_feeder
    from app.middleware import hub_metrics

    if not hub_metrics.ENABLED:
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Coleta de métricas de API desativada (HUB_METRICS=false).",
            ana_state="waiting", ana_task="Sem série de latência para correlacionar.",
            activity="Painel HUB: coletor interno de API desligado.",
            result="Seção 'api' do HUB não será atualizada neste ciclo.",
            evidence="Fonte: hub_metrics (desativado via HUB_METRICS).",
        )

    try:
        result = hub_feeder.drain_and_feed()
    except ValueError:
        result = None  # buffer vazio — nada a publicar neste ciclo
    pending = hub_metrics.pending_count()

    if result is None:
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhuma requisição de API desde o último ciclo.",
            ana_state="waiting", ana_task="Sem dados novos para correlacionar.",
            activity="Painel HUB: buffer de métricas vazio.",
            result="Nenhuma métrica de API a publicar neste ciclo.",
            evidence="Fonte: hub_metrics (buffer vazio).",
        )

    stored = result.get("stored") or {}
    return dict(
        state="running",
        mon_state="running", mon_task=f"{result.get('events', 0)} requisições agregadas na seção 'api'.",
        ana_state="running", ana_task=f"{result.get('correlations', 0)} correlação(ões) ativa(s) no HUB.",
        activity="Painel HUB: publicação de latência p95, throughput e taxa de erro da API.",
        result=(
            f"API: p95={stored.get('latency_p95_ms', 0)}ms, "
            f"rps={stored.get('rps', 0)}, erros={stored.get('error_rate', 0)}%."
        ),
        evidence=(
            f"Fonte: hub_metrics ({result.get('events', 0)} eventos). "
            f"Quarentenas aplicadas: {len(result.get('autonomous_actions') or [])}. "
            f"Novos eventos no buffer: {pending}."
        ),
    )


# ─── Fiscal: regras e conformidade ─────────────────────────────────────────
def _snapshot_fiscal() -> dict:
    from firebase_admin import db
    from app.services import nexus_intel

    try:
        ctx = _load_nexus_intel()
        intel = ctx["intel"]
        audit = ctx["audit"]
        plan = ctx["plan"]
    except Exception:
        intel = {"findings": [], "total_reports": 0}
        audit = {"findings": []}
        plan = {"actions": [], "questions": [], "signature": ""}

    nexus_text = nexus_intel.summary_text(intel)
    plan_text = nexus_intel.plan_summary(plan)

    cfg = db.reference("config/withdrawals").get() or {}
    allowed = cfg.get("allowedAmounts") or ALLOWED_AMOUNTS_DEFAULT
    pending = db.reference("admin/pending_withdrawals").get() or {}
    nodes = db.reference("neural/nodes").get() or {}

    pendencias = []
    for wid, w in pending.items():
        if not isinstance(w, dict):
            continue
        if w.get("amount") not in allowed:
            pendencias.append(f"{wid}: valor {w.get('amount')} fora da regra")
        if w.get("pixType") not in VALID_PIX_TYPES:
            pendencias.append(f"{wid}: pixType {w.get('pixType')} inválido")

    if pendencias:
        activity = "Documentos e regras disponibilizados para conferência."
        result = "Pendências: " + "; ".join(pendencias[:3])
        evidence = f"Regras: allowedAmounts={allowed} | pixTypes={sorted(VALID_PIX_TYPES)}"
        if plan.get("actions"):
            activity = f"Filtragem cruzada com Sentinel/Auditor/Nexus. {nexus_text} {plan_text}"
            result = f"Fiscal + Cyber Core: {len(plan['actions'])} conta(s) com plano de ação; {len(pendencias)} pendência(s) de saque."
            evidence = f"{evidence}. {nexus_text} Perguntas: {plan['questions'][0] if plan.get('questions') else '—'}"
        return dict(
            state="error",
            mon_state="running", mon_task=f"{len(nodes)} projeto(s) e {len(pending)} saque(s) sob regra.",
            ana_state="error", ana_task=f"{len(pendencias)} pendência(s) de regra identificada(s).",
            activity=activity,
            result=result,
            evidence=evidence,
            metrics=[
                {"key": "pending", "label": "Pendências de regra", "value": len(pendencias)},
                {"key": "nodes", "label": "Projetos monitorados", "value": len(nodes)},
            ],
        )

    if plan.get("actions"):
        return dict(
            state="error",
            mon_state="running", mon_task=f"{len(nodes)} projeto(s) monitorados sob as regras vigentes.",
            ana_state="error", ana_task="Plano de ação aguardando aprovação e repasse ao Cyber Core.",
            activity=f"Filtragem completa (Sentinel → Auditor → Nexus → Financeiro). {nexus_text} {plan_text}",
            result=f"Cyber Core IA: plano assinado ({plan.get('signature','')}) com {len(plan['actions'])} ação(ões).",
            evidence=f"Regras: allowedAmounts={allowed} | pixTypes={sorted(VALID_PIX_TYPES)}. {nexus_text} {', '.join(plan.get('questions', [])[:2])}",
            metrics=[
                {"key": "pending", "label": "Pendências de regra", "value": 0},
                {"key": "nodes", "label": "Projetos monitorados", "value": len(nodes)},
            ],
        )

    return dict(
        state="running",
        mon_state="running", mon_task=f"{len(nodes)} projeto(s) monitorados sob as regras vigentes.",
        ana_state="running", ana_task="Sem pendência de regra neste ciclo.",
        activity=f"Conferência de documentos, valores e tipos de chave permitidos. {nexus_text}",
        result=f"{len(pending)} saque(s) conformes; {len(nodes)} projeto(s) sob regras.",
        evidence=f"Regras: allowedAmounts={allowed} | pixTypes={sorted(VALID_PIX_TYPES)}. {nexus_text}",
        metrics=[
            {"key": "pending", "label": "Pendências de regra", "value": 0},
            {"key": "nodes", "label": "Projetos monitorados", "value": len(nodes)},
        ],
    )


_AGENTS = (
    ("financeiro", _snapshot_financeiro),
    ("sentinel", _snapshot_sentinel),
    ("auditor", _snapshot_auditor),
    ("fiscal", _snapshot_fiscal),
    ("hub", _snapshot_hub),
)


def _emit(agent: str, snap: dict) -> None:
    telemetry._enqueue_event(
        agent,
        snap.get("state", "idle"),
        monitoring={"state": snap.get("mon_state", "waiting"), "task": snap.get("mon_task", "")},
        analysis={"state": snap.get("ana_state", "waiting"), "task": snap.get("ana_task", "")},
        activity=snap.get("activity", ""),
        result=snap.get("result", ""),
        evidence=snap.get("evidence", ""),
        metrics=snap.get("metrics", []),
        observed_at=_iso_now(),
    )


def _run_cycle_sync() -> None:
    from app.services import firebase_service  # noqa: F401 — SDK init é no import
    for agent, collector in _AGENTS:
        try:
            snap = collector()
        except Exception as exc:  # pragma: no cover - depende de rede/RTDB
            logger.exception("telemetry: falha no coletor %s", agent)
            snap = dict(
                state="error",
                mon_state="error", mon_task="Falha ao coletar dados do módulo.",
                ana_state="error", ana_task="Análise indisponível nesta rodada.",
                activity=f"Falha de coleta do agente {agent}.",
                result=f"Erro: {type(exc).__name__}",
                evidence="Verifique a conexão com o RTDB/backend.",
            )
        _emit(agent, snap)


async def _cycle() -> None:
    # RTDB do firebase-admin é síncrono — roda em thread para não bloquear o loop.
    await asyncio.to_thread(_run_cycle_sync)


async def _loop() -> None:
    # Primeira emissão imediata (sinal aparece ao abrir o painel).
    while True:
        try:
            await _cycle()
        except Exception:  # pragma: no cover
            logger.exception("telemetry: ciclo falhou")
        await asyncio.sleep(INTERVAL)


async def start_telemetry_worker() -> None:
    global _task
    if not ENABLED or _task is not None:
        return
    _task = asyncio.create_task(_loop())
    logger.info("telemetry: worker iniciado (intervalo %ss)", INTERVAL)


async def stop_telemetry_worker() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
        logger.info("telemetry: worker parado")
