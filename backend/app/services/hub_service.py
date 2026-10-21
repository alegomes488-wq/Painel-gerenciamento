"""
Painel HUB — serviço de dados (RTDB) dos três pilares:
  Desempenho / Acompanhamento / Segurança.

Recebe eventos dos agentes (site, PWA/iOS, APK, back-end), consolida o
snapshot e aciona o motor de correlação da Cyber Core IA
(app.services.hub_correlator). Ações autônomas (quarentena de IP) são
registradas em /hub/actions com trilha de auditoria.
"""
import hashlib
import html
import ipaddress
from datetime import datetime

from app.services.firebase_service import get_db
from app.services import hub_correlator

HUB_ROOT = "hub"
HISTORY_LIMIT = 120
ACTIONS_LOG_LIMIT = 200
QUARANTINE_LIMIT = 500
CORRELATIONS_LIMIT = 50

VALID_SECTIONS = {
    "web": "performance",
    "app": "performance",
    "api": "performance",
    "sessions": "tracking",
    "funnels": "tracking",
    "tickets": "tracking",
    "user_context": "tracking",
    "apk": "security",
    "network": "security",
    "auth": "security",
    "vulnerabilities": "security",
}

# Whitelist de campos escalares: seção -> campo -> (min, max)
_SCALAR_SPECS = {
    "web": {
        "lcp_ms": (0, 60000), "inp_ms": (0, 60000), "cls": (0, 1),
        "ttfb_ms": (0, 60000), "error_rate_5xx": (0, 100), "error_rate_4xx": (0, 100),
    },
    "app": {
        "launch_time_ms": (0, 120000), "frozen_frames_rate": (0, 100),
        "crash_rate": (0, 100), "anr_rate": (0, 100),
        "cpu_avg": (0, 100), "ram_avg": (0, 100), "battery_drain": (0, 100),
        "apk_version": None,  # string
        "hot_ip": None,       # ip validado
    },
    "api": {
        "latency_p95_ms": (0, 600000), "rps": (0, 1000000), "error_rate": (0, 100),
    },
    "sessions": {
        "active_now": (0, 10000000), "web": (0, 10000000), "app": (0, 10000000),
        "apk_installs": (0, 10000000),
    },
    "tickets": {
        "open": (0, 1000000), "avg_minutes": (0, 100000),
    },
    "user_context": {
        "uid": None,            # texto (obrigatório — vira chave de gravação)
        "platform": None,       # web | android | ios
        "app_version": None,
        "network_type": None,   # wifi | 4g | 5g | unknown
        "last_screen": None,
        "root": (0, 1),
        "jailbreak": (0, 1),
        "payment_blocked": (0, 1),
    },
    "apk": {
        "tamper_attempts": (0, 1000000), "repackage_alerts": (0, 1000000),
        "root_devices": (0, 1000000), "jailbreak_devices": (0, 1000000),
        "invalid_signature_hits": (0, 1000000),
        "hot_ip": None,
    },
    "network": {
        "waf_blocks": (0, 10000000), "sqli_attempts": (0, 10000000),
        "xss_attempts": (0, 10000000), "ddos_attempts": (0, 10000000),
        "bot_blocks": (0, 10000000), "emulator_requests": (0, 10000000),
        "suspicious_requests": (0, 10000000),
        "hot_ip": None,
    },
    "auth": {
        "login_failures_burst": (0, 10000000), "credential_stuffing_score": (0, 100),
        "fake_accounts_bulk": (0, 1000000), "impossible_travel": (0, 1000000),
        "hot_ip": None,
    },
}

# Campos "dicionário de dicionários" (segmentação): seção -> campo -> subcampo -> (min, max)
_NESTED_MAP_SPECS = {
    "app": {
        "by_version": {"crash_rate": (0, 100), "anr_rate": (0, 100), "sessions": (0, 10000000), "previous_crash_rate": (0, 100)},
        "by_device": {"crash_rate": (0, 100), "sessions": (0, 10000000)},
        "by_os": {"crash_rate": (0, 100), "sessions": (0, 10000000)},
    },
    "api": {
        "endpoints": {"latency_ms": (0, 600000), "error_rate": (0, 100), "rps": (0, 1000000)},
    },
    "tickets": {
        "top_reasons": None,  # dict str->int
    },
}

_MAX_SEGMENT_KEYS = 40
_MAX_MAP_ENTRIES = 40
_MAX_REASON_LEN = 80


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _sanitize_text(value, max_length: int = 200) -> str:
    """Escapa HTML e trunca (mesmo critério do monitor)."""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\x00", "")
    return html.escape(value, quote=True)[:max_length]


def _clamp(value, min_val: float, max_val: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return min_val
    return min(max(num, min_val), max_val)


def _valid_ip(value) -> str:
    """Retorna o IP se válido; string vazia caso contrário."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return ""


def sanitize_event(section: str, data: dict) -> dict:
    """
    Valida e sanea o payload de ingestão de uma seção do HUB.
    Campos fora da whitelist são descartados. Levanta ValueError em payload inválido.
    """
    if section not in VALID_SECTIONS:
        raise ValueError(f"Seção inválida: {section!r}")
    if not isinstance(data, dict):
        raise ValueError("data deve ser um objeto JSON")

    clean = {}
    specs = _SCALAR_SPECS.get(section, {})
    for field, spec in specs.items():
        if field not in data:
            continue
        raw = data[field]
        if spec is None:
            # Campo de texto: hot_ip tem validação especial de IP
            if field == "hot_ip":
                ip = _valid_ip(raw)
                if ip:
                    clean[field] = ip
            else:
                clean[field] = _sanitize_text(raw, 80)
        else:
            min_val, max_val = spec
            clean[field] = _clamp(raw, min_val, max_val)

    # Mapas segmentados (dict de dicts)
    for field, subspec in _NESTED_MAP_SPECS.get(section, {}).items():
        raw_map = data.get(field)
        if not isinstance(raw_map, dict):
            continue
        out_map = {}
        for key, sub in list(raw_map.items())[:_MAX_SEGMENT_KEYS]:
            key_clean = _sanitize_text(key, 60)
            if subspec is None:
                # dict str->int (ex.: top_reasons)
                try:
                    out_map[key_clean] = int(float(sub))
                except (TypeError, ValueError):
                    continue
            elif isinstance(sub, dict):
                sub_out = {}
                for sf, bounds in subspec.items():
                    if sf in sub:
                        sub_out[sf] = _clamp(sub[sf], bounds[0], bounds[1])
                if sub_out:
                    out_map[key_clean] = sub_out
        if out_map:
            clean[field] = out_map

    # Lista de passos de funil
    if section == "funnels":
        steps = data.get("steps")
        if isinstance(steps, list):
            out_steps = []
            for step in steps[:30]:
                if not isinstance(step, dict):
                    continue
                out_steps.append({
                    "id": _sanitize_text(step.get("id", ""), 60),
                    "name": _sanitize_text(step.get("name", ""), 120),
                    "entered": _clamp(step.get("entered"), 0, 100000000),
                    "converted": _clamp(step.get("converted"), 0, 100000000),
                })
            if out_steps:
                clean["steps"] = out_steps

    # Vulnerabilidades (listas por escopo)
    if section == "vulnerabilities":
        for scope in ("web", "app"):
            items = data.get(scope)
            if not isinstance(items, list):
                continue
            out_items = []
            for item in items[:100]:
                if not isinstance(item, dict):
                    continue
                out_items.append({
                    "package": _sanitize_text(item.get("package", ""), 120),
                    "version": _sanitize_text(item.get("version", ""), 40),
                    "cve": _sanitize_text(item.get("cve", ""), 40),
                    "severity": _sanitize_text(item.get("severity", ""), 20).lower(),
                })
            if out_items:
                clean[scope] = out_items

    if not clean:
        raise ValueError("Nenhum campo válido no payload")
    return clean


def _history_point(section: str, clean: dict) -> dict:
    """Resumo numérico para o histórico de séries temporais."""
    point = {"t": _now_iso()}
    keys = {
        "web": ("lcp_ms", "inp_ms", "ttfb_ms", "error_rate_5xx"),
        "app": ("crash_rate", "anr_rate", "launch_time_ms", "frozen_frames_rate"),
        "api": ("latency_p95_ms", "rps", "error_rate"),
        "sessions": ("active_now", "web", "app"),
    }.get(section, ())
    for key in keys:
        if key in clean:
            point[key] = clean[key]
    return point


def _trim_list_ref(ref, limit: int):
    """Remove entradas antigas de um nó lista (dict ordenado por chave)."""
    try:
        snapshot = ref.get()
        if isinstance(snapshot, dict) and len(snapshot) > limit:
            keys = sorted(snapshot.keys())
            for old_key in keys[: len(snapshot) - limit]:
                ref.child(old_key).delete()
    except Exception:
        pass  # nosec — trim nunca deve derrubar a ingestão


def ingest_event(section: str, data: dict, source: str = "") -> dict:
    """
    Grava um evento saneado no RTDB e atualiza o histórico da seção.
    Retorna o payload armazenado.
    """
    pillar = VALID_SECTIONS.get(section)
    if pillar is None:
        raise ValueError(f"Seção inválida: {section!r}")
    clean = sanitize_event(section, data)
    clean["updated_at"] = _now_iso()
    clean["source"] = _sanitize_text(source, 60)

    db = get_db()
    if section == "user_context":
        # Contexto é POR USUÁRIO: grava em /hub/tracking/user_context/{uid}
        # para o copilot do agente de suporte consultar ao atender.
        uid = clean.get("uid", "")
        if not uid:
            raise ValueError("user_context exige o campo 'uid'")
        db.reference(f"{HUB_ROOT}/tracking/user_context/{uid}").update(clean)
        return clean

    db.reference(f"{HUB_ROOT}/{pillar}/{section}").update(clean)

    if pillar == "performance":
        hist_ref = db.reference(f"{HUB_ROOT}/performance/history/{section}")
        hist_ref.push(_history_point(section, clean))
        _trim_list_ref(hist_ref, HISTORY_LIMIT)

    return clean


def read_pillar(pillar: str) -> dict:
    """Lê a seção consolidada de um pilar."""
    if pillar not in ("performance", "tracking", "security"):
        raise ValueError(f"Pilar inválido: {pillar!r}")
    db = get_db()
    data = db.reference(f"{HUB_ROOT}/{pillar}").get() or {}
    return data if isinstance(data, dict) else {}


def read_snapshot() -> dict:
    """Consolida os três pilares em um snapshot único para o correlator."""
    return {
        "performance": read_pillar("performance"),
        "tracking": read_pillar("tracking"),
        "security": read_pillar("security"),
        "generated_at": _now_iso(),
    }


def _persist_correlations(correlations: list) -> None:
    db = get_db()
    ref = db.reference(f"{HUB_ROOT}/correlations")
    stored = {}
    for corr in correlations[:CORRELATIONS_LIMIT]:
        stored[corr["id"]] = corr
    if stored:
        ref.update(stored)
    # Trim: mantém apenas as mais recentes (ids são hex aleatórios; usa generated_at)
    try:
        current = ref.get() or {}
        if isinstance(current, dict) and len(current) > CORRELATIONS_LIMIT:
            ordered = sorted(
                current.items(),
                key=lambda kv: (kv[1] or {}).get("generated_at", ""),
                reverse=True,
            )
            for old_id, _ in ordered[CORRELATIONS_LIMIT:]:
                ref.child(old_id).delete()
    except Exception:
        pass  # nosec


def run_correlations(snapshot: dict = None) -> list:
    """Executa o correlator e persiste o resultado em /hub/correlations."""
    if snapshot is None:
        snapshot = read_snapshot()
    findings = hub_correlator.correlate(snapshot)
    _persist_correlations(findings)
    return findings


def ingest_and_correlate(section: str, data: dict, source: str = "") -> dict:
    """
    Fluxo completo de ingestão: grava o evento, roda as correlações da
    Cyber Core IA e aplica ações autônomas críticas (quarentena de IP).
    Usado pelo canal HTTP (/api/hub/events) e pelo feeder interno de API.
    """
    stored = ingest_event(section, data, source=source)
    correlations = run_correlations()
    autonomous = apply_critical_autonomous_actions(correlations)
    return {
        "stored": stored,
        "correlations": len(correlations),
        "autonomous_actions": autonomous,
    }


def list_correlations(limit: int = CORRELATIONS_LIMIT) -> list:
    db = get_db()
    data = db.reference(f"{HUB_ROOT}/correlations").get() or {}
    items = [c for c in (data or {}).values() if isinstance(c, dict)]
    items.sort(key=lambda c: c.get("generated_at", ""), reverse=True)
    return items[:max(1, min(limit, CORRELATIONS_LIMIT))]


def _quarantine_key(ip: str) -> str:
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def quarantine_count() -> int:
    db = get_db()
    data = db.reference(f"{HUB_ROOT}/security/quarantine").get() or {}
    return len(data) if isinstance(data, dict) else 0


def _log_action(action_type: str, params: dict, actor: str, reason: str = "") -> dict:
    db = get_db()
    entry = {
        "type": _sanitize_text(action_type, 60),
        "params": {k: _sanitize_text(v, 120) for k, v in (params or {}).items()},
        "actor": _sanitize_text(actor, 80),
        "reason": _sanitize_text(reason, 200),
        "timestamp": _now_iso(),
    }
    db.reference(f"{HUB_ROOT}/actions").push(entry)
    _trim_list_ref(db.reference(f"{HUB_ROOT}/actions"), ACTIONS_LOG_LIMIT)
    return entry


def apply_autonomous_action(action_type: str, params: dict, actor: str = "cybercore-ia", reason: str = "") -> dict:
    """
    Executa uma ação de segurança autorizada pelo correlator / pelo operador.
    Ações suportadas:
      - quarantine_ip {ip}
      - release_ip {ip}
      - revoke_access {uid} (marca o usuário como bloqueado em /hub/access_revoked)
    """
    params = params or {}
    db = get_db()

    if action_type == "quarantine_ip":
        ip = _valid_ip(params.get("ip"))
        if not ip:
            raise ValueError("IP inválido para quarentena")
        ref = db.reference(f"{HUB_ROOT}/security/quarantine/{_quarantine_key(ip)}")
        current = ref.get() or {}
        if isinstance(current, dict) and current.get("active"):
            return {"status": "skipped", "reason": "IP já em quarentena", "ip": ip}
        if quarantine_count() >= QUARANTINE_LIMIT:
            raise ValueError("Limite de quarentenas atingido")
        record = {
            "ip": ip,
            "active": True,
            "reason": _sanitize_text(reason or "Correlação crítica da Cyber Core IA", 200),
            "by": _sanitize_text(actor, 80),
            "since": _now_iso(),
        }
        ref.set(record)
        _log_action("quarantine_ip", {"ip": ip}, actor, reason)
        return {"status": "applied", "action": "quarantine_ip", "ip": ip, "record": record}

    if action_type == "release_ip":
        ip = _valid_ip(params.get("ip"))
        if not ip:
            raise ValueError("IP inválido para liberação")
        ref = db.reference(f"{HUB_ROOT}/security/quarantine/{_quarantine_key(ip)}")
        current = ref.get() or {}
        if not current:
            return {"status": "skipped", "reason": "IP não estava em quarentena", "ip": ip}
        ref.delete()
        _log_action("release_ip", {"ip": ip}, actor, reason)
        return {"status": "applied", "action": "release_ip", "ip": ip}

    if action_type == "revoke_access":
        uid = _sanitize_text(params.get("uid", ""), 80)
        if not uid:
            raise ValueError("uid obrigatório para revogar acesso")
        db.reference(f"{HUB_ROOT}/access_revoked/{uid}").set({
            "active": True,
            "reason": _sanitize_text(reason or "Ação autônoma Cyber Core IA", 200),
            "by": _sanitize_text(actor, 80),
            "since": _now_iso(),
        })
        _log_action("revoke_access", {"uid": uid}, actor, reason)
        return {"status": "applied", "action": "revoke_access", "uid": uid}

    if action_type in ("block_rollout", "unblock_rollout"):
        version = _sanitize_text(params.get("app_version", ""), 40)
        if not version:
            raise ValueError("app_version obrigatório para bloquear/desbloquear rollout")
        ref = db.reference(f"{HUB_ROOT}/performance/blocked_rollouts/{version}")
        if action_type == "unblock_rollout":
            current = ref.get() or {}
            if not current or not current.get("active"):
                return {"status": "skipped", "reason": "Rollout não estava bloqueado", "app_version": version}
            ref.delete()
            _log_action("unblock_rollout", {"app_version": version}, actor, reason)
            return {"status": "applied", "action": "unblock_rollout", "app_version": version}
        record = {
            "active": True,
            "reason": _sanitize_text(reason or "Regressão detectada pela Cyber Core IA", 200),
            "by": _sanitize_text(actor, 80),
            "since": _now_iso(),
        }
        ref.set(record)
        _log_action("block_rollout", {"app_version": version}, actor, reason)
        return {"status": "applied", "action": "block_rollout", "app_version": version, "record": record}

    raise ValueError(f"Tipo de ação não suportado: {action_type!r}")


def apply_critical_autonomous_actions(correlations: list, actor: str = "cybercore-ia") -> list:
    """
    Aplica automaticamente apenas as ações autônomas de correlações CRÍTIAS.
    Whitelist de ações autônomas: quarantine_ip.
    """
    applied = []
    for corr in correlations:
        if not isinstance(corr, dict) or corr.get("severity") != "critical":
            continue
        action = corr.get("recommended_action") or {}
        if action.get("type") != "quarantine_ip":
            continue
        try:
            result = apply_autonomous_action(
                "quarantine_ip",
                action.get("params") or {},
                actor=actor,
                reason=corr.get("title", ""),
            )
            applied.append({"correlation_id": corr.get("id"), **result})
        except ValueError:
            continue  # nosec — ação inválida/limite: segue sem derrubar o ciclo
    return applied


def list_actions(limit: int = 30) -> list:
    db = get_db()
    data = db.reference(f"{HUB_ROOT}/actions").get() or {}
    items = [a for a in (data or {}).values() if isinstance(a, dict)]
    items.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    return items[:max(1, min(limit, ACTIONS_LOG_LIMIT))]


def build_overview() -> dict:
    """Visão consolidada do HUB: pilares + correlações + score de saúde."""
    snapshot = read_snapshot()
    correlations = run_correlations(snapshot)
    score = hub_correlator.health_score(correlations)
    return {
        "status": "success",
        "agent": "Cyber Core IA — HUB v1.0",
        "health": score,
        "worst_severity": hub_correlator.worst_severity(correlations),
        "critical_count": sum(1 for c in correlations if c.get("severity") == "critical"),
        "quarantined_ips": quarantine_count(),
        "correlations": correlations,
        "pillars": {
            "performance": snapshot.get("performance") or {},
            "tracking": snapshot.get("tracking") or {},
            "security": snapshot.get("security") or {},
        },
        "generated_at": _now_iso(),
    }


# ─────────────────────────────────────────────────────────────
# COPILOT DO AGENTE DE SUPORTE — brief contextual por usuário
# ─────────────────────────────────────────────────────────────

def _mask_email(email: str) -> str:
    """Mascara e-mail para o resumo (o agente já tem acesso ao cadastro)."""
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}***@{domain}"


def resolve_uid(query: str) -> str:
    """Resolve uid a partir de uid ou e-mail (busca no cadastro)."""
    query = str(query or "").strip()
    if not query:
        return ""
    db = get_db()
    users = db.reference("users").get() or {}
    if not isinstance(users, dict):
        return ""
    if query in users:
        return query
    query_low = query.lower()
    for uid, user in users.items():
        if isinstance(user, dict) and str(user.get("email", "")).strip().lower() == query_low:
            return uid
    return ""


def is_rollout_blocked(app_version: str) -> dict:
    """Status do bloqueio de rollout para uma versão do APK."""
    version = _sanitize_text(app_version, 40)
    if not version:
        return {"blocked": False}
    db = get_db()
    record = db.reference(f"{HUB_ROOT}/performance/blocked_rollouts/{version}").get() or {}
    blocked = bool(isinstance(record, dict) and record.get("active"))
    return {"blocked": blocked, "app_version": version, "record": record if blocked else {}}


def build_agent_brief(query: str) -> dict:
    """
    Resumo contextual para o agente de suporte atender um usuário:
    cadastro, contexto do dispositivo/rede (user_context), bloqueios,
    saques pendentes e flags de risco.
    """
    uid = resolve_uid(query)
    if not uid:
        raise ValueError(f"Usuário não encontrado: {query!r}")

    db = get_db()
    user = db.reference(f"users/{uid}").get() or {}
    if not isinstance(user, dict):
        user = {}
    context = db.reference(f"{HUB_ROOT}/tracking/user_context/{uid}").get() or {}
    if not isinstance(context, dict):
        context = {}
    revoked = db.reference(f"{HUB_ROOT}/access_revoked/{uid}").get() or {}
    access_revoked = bool(isinstance(revoked, dict) and revoked.get("active"))

    pending = db.reference("admin/pending_withdrawals").get() or {}
    pending_count = 0
    for w in (pending or {}).values():
        if isinstance(w, dict) and str(w.get("uid", "")) == uid:
            pending_count += 1

    flags = []
    if access_revoked:
        flags.append("ACCESS_REVOKED")
    if context.get("root"):
        flags.append("ROOT_DEVICE")
    if context.get("jailbreak"):
        flags.append("JAILBREAK_DEVICE")
    if context.get("payment_blocked"):
        flags.append("PAYMENT_BLOCKED_BY_SECURITY")
    if pending_count:
        flags.append("PENDING_WITHDRAWAL")
    if not context:
        flags.append("NO_DEVICE_CONTEXT")

    email = str(user.get("email", "") or "")
    parts = [
        f"Usuário {uid}" + (f" ({_mask_email(email)})" if email else "") + "."
    ]
    if context:
        device_bits = []
        if context.get("platform"):
            device_bits.append(str(context["platform"]))
        if context.get("app_version"):
            device_bits.append(f"app {context['app_version']}")
        if context.get("network_type"):
            device_bits.append(f"rede {context['network_type']}")
        if device_bits:
            parts.append("Dispositivo: " + ", ".join(device_bits) + ".")
        if context.get("root") or context.get("jailbreak"):
            parts.append(
                "ATENÇÃO: dispositivo com Root/Jailbreak — pagamentos são bloqueados "
                "por segurança; oriente o usuário a desativar o Root antes de pagar."
            )
        if context.get("last_screen"):
            parts.append(f"Última tela: {context['last_screen']}.")
    else:
        parts.append("Sem contexto de dispositivo reportado pelo app/site.")
    if access_revoked:
        parts.append(
            "Acesso REVOGADO pela Cyber Core IA"
            + (f" ({revoked.get('reason', '')})" if revoked.get("reason") else "")
            + " — não restaure sem revisão de segurança."
        )
    if pending_count:
        parts.append(f"{pending_count} solicitação(ões) de saque pendente(s) na fila.")

    return {
        "status": "success",
        "query": _sanitize_text(query, 120),
        "uid": uid,
        "summary": " ".join(parts),
        "flags": flags,
        "context": {k: v for k, v in context.items() if k != "source"},
        "access_revoked": access_revoked,
        "pending_withdrawals": pending_count,
        "generated_at": _now_iso(),
    }
