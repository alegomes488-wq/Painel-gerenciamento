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


# ─── Financeiro: fluxo de caixa e pagamentos ───────────────────────────────
def _snapshot_financeiro() -> dict:
    from firebase_admin import db

    pending = db.reference("admin/pending_withdrawals").get() or {}
    cfg = db.reference("config/withdrawals").get() or {}
    allowed = cfg.get("allowedAmounts") or ALLOWED_AMOUNTS_DEFAULT

    n = len(pending)
    total = 0.0
    for w in pending.values():
        if isinstance(w, dict):
            try:
                total += float(w.get("amount") or 0)
            except (TypeError, ValueError):
                pass

    if n == 0:
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhuma solicitação de pagamento na fila.",
            ana_state="waiting", ana_task="Sem movimentação para comparar neste ciclo.",
            activity="Fila de saques vazia — nada a coletar agora.",
            result="Fluxo estável: nenhum saque aguardando aprovação.",
            evidence=f"Fonte: admin/pending_withdrawals (vazio). Ciclo {_iso_now()}.",
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

    return dict(
        state="running",
        mon_state=mon_state, mon_task=f"{n} solicitação(ões) de pagamento em observação.",
        ana_state=ana_state, ana_task=ana_task,
        activity=f"Coleta de entradas, saídas e solicitações ({n} pendente(s)).",
        result=result, evidence=evidence,
    )


# ─── Sentinel: segurança e disponibilidade ─────────────────────────────────
def _snapshot_sentinel() -> dict:
    from app.services.secops_agent import SecOpsSentinelAgent

    audit = SecOpsSentinelAgent.audit_system_security()
    checks = audit.get("audit_results") or []
    falhas = [c.get("item", "?") for c in checks if c.get("status") == "FAIL"]
    warns = [c.get("item", "?") for c in checks if c.get("status") == "WARN"]

    if falhas:
        return dict(
            state="error",
            mon_state="running", mon_task=f"{len(checks)} verificações de segurança coletadas.",
            ana_state="error", ana_task=f"Falha em {len(falhas)} verificação(ões) de segurança.",
            activity="Checkup de integridade de chaves, conexões e configurações.",
            result="Risco observado: " + ", ".join(falhas[:4]),
            evidence=f"Fonte: audit_system_security | WARNs: {', '.join(warns[:4]) or 'nenhum'}",
        )
    return dict(
        state="running",
        mon_state="running", mon_task=f"{len(checks)} verificações de segurança em andamento.",
        ana_state="running", ana_task="Sem anomalia identificada neste ciclo.",
        activity="Disponibilidade e eventos de segurança monitorados.",
        result=f"Configuração íntegra — {len(checks)} verificações OK, {len(warns)} aviso(s).",
        evidence="Fonte: audit_system_security (chaves, webhook, app check, n8n)",
    )


# ─── Auditor: integridade das operações ────────────────────────────────────
def _snapshot_auditor() -> dict:
    from firebase_admin import db

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
            evidence=f"Fonte: logs/financial | Eventos 24h: {len(recentes)}",
        )
    if not recentes:
        return dict(
            state="idle",
            mon_state="waiting", mon_task="Nenhum evento financeiro nas últimas 24h.",
            ana_state="waiting", ana_task="Sem trilha nova para conferir.",
            activity="Trilha de auditoria sem eventos recentes.",
            result="Nenhuma operação registrada nas últimas 24 horas.",
            evidence="Fonte: logs/financial (últimas 24h vazias)",
        )
    return dict(
        state="running",
        mon_state="running", mon_task=f"{len(recentes)} evento(s) financeiro(s) coletados (24h).",
        ana_state="running", ana_task="Sem duplicidade nem inconsistência encontrada.",
        activity="Registros de operações e trilhas de auditoria conferidos.",
        result=f"{len(recentes)} evento(s) nas últimas 24h, todos consistentes.",
        evidence=f"Fonte: logs/financial | Pagamentos únicos: {len(pagos_por_wid)}",
    )


# ─── Fiscal: regras e conformidade ─────────────────────────────────────────
def _snapshot_fiscal() -> dict:
    from firebase_admin import db

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
        return dict(
            state="error",
            mon_state="running", mon_task=f"{len(nodes)} projeto(s) e {len(pending)} saque(s) sob regra.",
            ana_state="error", ana_task=f"{len(pendencias)} pendência(s) de regra identificada(s).",
            activity="Documentos e regras disponibilizados para conferência.",
            result="Pendências: " + "; ".join(pendencias[:3]),
            evidence=f"Regras: allowedAmounts={allowed} | pixTypes={sorted(VALID_PIX_TYPES)}",
        )
    return dict(
        state="running",
        mon_state="running", mon_task=f"{len(nodes)} projeto(s) monitorados sob as regras vigentes.",
        ana_state="running", ana_task="Sem pendência de regra neste ciclo.",
        activity="Conferência de documentos, valores e tipos de chave permitidos.",
        result=f"{len(pending)} saque(s) conformes; {len(nodes)} projeto(s) sob regras.",
        evidence=f"Regras: allowedAmounts={allowed} | pixTypes={sorted(VALID_PIX_TYPES)}",
    )


_AGENTS = (
    ("financeiro", _snapshot_financeiro),
    ("sentinel", _snapshot_sentinel),
    ("auditor", _snapshot_auditor),
    ("fiscal", _snapshot_fiscal),
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
