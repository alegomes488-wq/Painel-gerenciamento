"""Análise dos relatos do Agente Nexus para a Central de Agentes.

Funções puras (sem Firebase) para que Sentinel, Auditor e Fiscal compartilhem
o mesmo contexto e possam ser testadas isoladamente.

Fontes esperadas:
  logs/nexus/{uid}/{push_id} = {"report": {...}, "received_at": "..."}
  users/{uid} = {"email", "cpf", "fullname", "createdAt", "balance", ...}
  admin/pending_withdrawals/{wid} = {"uid", "amount", ...}
"""
import base64
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_LABEL = {"critical": "crítico", "high": "alto", "medium": "médio", "low": "baixo"}

REQUIRED_REPORT_FIELDS = ("uid", "ads_watched", "page_context", "session_duration")
IDENTITY_FIELDS = ("email", "cpf", "fullname", "createdAt", "created_at")


def mask_uid(uid) -> str:
    text = str(uid or "")
    return (text[:6] + "…") if len(text) > 6 else (text or "?")


def _parse_dt(raw):
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if at.tzinfo is not None:
        at = at.astimezone().replace(tzinfo=None)
    return at


def _decode_activity_hash(raw):
    if not isinstance(raw, str) or not raw:
        return None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        data = base64.b64decode(padded, validate=False)
        obj = json.loads(data.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def _norm_email(value) -> str:
    return str(value or "").strip().lower()


def _norm_cpf(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _norm_text(value) -> str:
    return str(value or "").strip()


def _identity_values(user: dict) -> dict:
    return {
        "email": _norm_email(user.get("email")),
        "cpf": _norm_cpf(user.get("cpf")),
        "fullname": _norm_text(user.get("fullname")),
        "createdAt": _norm_text(user.get("createdAt") or user.get("created_at")),
    }


def parse_reports(logs_nexus) -> list:
    reports = []
    if not isinstance(logs_nexus, dict):
        return reports
    for path_uid, entries in logs_nexus.items():
        if not isinstance(entries, dict):
            continue
        for push_id, event in entries.items():
            if not isinstance(event, dict):
                continue
            report = event.get("report")
            if not isinstance(report, dict):
                report = {}
            reports.append({
                "key": str(push_id),
                "path_uid": str(path_uid),
                "report": report,
                "received_at": _parse_dt(event.get("received_at")),
                "received_raw": event.get("received_at"),
            })
    reports.sort(key=lambda item: item["received_at"] or datetime.min)
    return reports


def _finding(code, severity, detail, uid=None):
    return {
        "code": code,
        "severity": severity,
        "uid": mask_uid(uid) if uid else "",
        "detail": detail,
    }


def _duplicate_groups(users: dict, field: str, normalizer) -> dict:
    groups = defaultdict(list)
    for uid, user in users.items():
        if not isinstance(user, dict):
            continue
        value = normalizer(user.get(field))
        if value:
            groups[value].append(uid)
    return {value: uids for value, uids in groups.items() if len(uids) > 1}


def analyze_nexus(logs_nexus, users, now=None) -> dict:
    now = now or datetime.now()
    users = users if isinstance(users, dict) else {}
    pending = None
    reports = parse_reports(logs_nexus)
    cutoff = now - timedelta(hours=24)

    findings = []
    flags_by_uid = defaultdict(set)
    latest_by_uid = {}
    reports_by_uid = defaultdict(list)
    recent_by_uid = Counter()
    identities_by_uid = defaultdict(lambda: defaultdict(set))
    invalid_hash_uids = set()

    for item in reports:
        uid = item["path_uid"]
        report = item["report"]
        report_uid = _norm_text(report.get("uid"))
        reports_by_uid[uid].append(item)
        if item["received_at"] and (latest_by_uid.get(uid) is None or item["received_at"] > latest_by_uid[uid]):
            latest_by_uid[uid] = item["received_at"]

        if report_uid and report_uid != uid:
            findings.append(_finding(
                "UID_MISMATCH", "critical",
                "O UID interno do relato não corresponde ao caminho do registro.",
                uid,
            ))
            flags_by_uid[uid].add("critical")

        missing = [field for field in REQUIRED_REPORT_FIELDS if field not in report]
        if missing:
            findings.append(_finding(
                "INVALID_REPORT", "medium",
                "Relato sem campo(s) obrigatório(s): " + ", ".join(missing) + ".",
                uid,
            ))
            flags_by_uid[uid].add("medium")

        if item["received_at"] is None:
            findings.append(_finding(
                "INVALID_TIMESTAMP", "medium",
                "Relato sem data de recebimento válida.",
                uid,
            ))
            flags_by_uid[uid].add("medium")
        elif item["received_at"] > now + timedelta(minutes=5):
            findings.append(_finding(
                "INVALID_TIMESTAMP", "medium",
                "Relato com data de recebimento no futuro.",
                uid,
            ))
            flags_by_uid[uid].add("medium")

        if item["received_at"] and item["received_at"] >= cutoff:
            recent_by_uid[uid] += 1

        ads = report.get("ads_watched")
        if ads is not None:
            try:
                ads = int(ads)
            except (TypeError, ValueError):
                ads = None
            if ads is not None and ads < 0:
                findings.append(_finding(
                    "INVALID_REPORT", "medium",
                    "Relato com quantidade negativa de anúncios.",
                    uid,
                ))
                flags_by_uid[uid].add("medium")

        raw_hash = report.get("activity_hash")
        if raw_hash:
            decoded = _decode_activity_hash(raw_hash)
            if decoded is None:
                invalid_hash_uids.add(uid)
            else:
                for field in IDENTITY_FIELDS:
                    value = _norm_text(decoded.get(field))
                    if value:
                        identities_by_uid[uid][field].add(value)

    for uid in reports_by_uid:
        if uid not in users:
            findings.append(_finding(
                "ORPHAN_REPORT", "high",
                "Relato recebido para UID sem conta cadastrada.",
                uid,
            ))
            flags_by_uid[uid].add("high")

    for uid in sorted(invalid_hash_uids):
        findings.append(_finding(
            "ACTIVITY_HASH_INVALID", "medium",
            "Hash de atividade inválido ou corrompido no relato.",
            uid,
        ))
        flags_by_uid[uid].add("medium")

    for uid, fields in identities_by_uid.items():
        mutated = [field for field, values in fields.items() if len(values) > 1]
        current = _identity_values(users.get(uid)) if isinstance(users.get(uid), dict) else {}
        for field in fields:
            if field not in mutated and current.get(field) and len(fields[field]) == 1:
                if current[field] not in fields[field]:
                    mutated.append(field)
        if mutated:
            findings.append(_finding(
                "IDENTITY_MUTATED", "high",
                "Dados de identidade divergiram entre relatos/cadastro: " + ", ".join(sorted(set(mutated))) + ".",
                uid,
            ))
            flags_by_uid[uid].add("high")

    for uid, events in reports_by_uid.items():
        recent = [e for e in events if e["received_at"] and e["received_at"] >= now - timedelta(minutes=10)]
        if len(recent) > 12:
            findings.append(_finding(
                "REPORT_BURST", "medium",
                f"{len(recent)} relatos em 10 minutos — volume compatível com automação.",
                uid,
            ))
            flags_by_uid[uid].add("medium")

        recent_ads = [
            int(e["report"].get("ads_watched"))
            for e in events
            if e["received_at"] and e["received_at"] >= cutoff and str(e["report"].get("ads_watched", "")).isdigit()
        ]
        if len(recent_ads) >= 3 and any(b < a for a, b in zip(recent_ads, recent_ads[1:])):
            findings.append(_finding(
                "ADS_REGRESSION", "medium",
                "Quantidade de anúncios diminuiu entre relatos recentes.",
                uid,
            ))
            flags_by_uid[uid].add("medium")

    user_email_groups = _duplicate_groups(users, "email", _norm_email)
    for email, uids in user_email_groups.items():
        findings.append(_finding(
            "DUPLICATE_EMAIL", "high",
            f"{len(uids)} contas compartilham o mesmo e-mail.",
            uids[0],
        ))
        for uid in uids:
            flags_by_uid[uid].add("high")

    user_cpf_groups = _duplicate_groups(users, "cpf", _norm_cpf)
    for cpf, uids in user_cpf_groups.items():
        findings.append(_finding(
            "DUPLICATE_CPF", "critical",
            f"{len(uids)} contas compartilham o mesmo CPF.",
            uids[0],
        ))
        for uid in uids:
            flags_by_uid[uid].add("critical")

    fp_groups = defaultdict(list)
    for uid, user in users.items():
        if not isinstance(user, dict):
            continue
        security = user.get("security")
        fingerprint = _norm_text(security.get("fingerprint")) if isinstance(security, dict) else ""
        if fingerprint:
            fp_groups[fingerprint].append(uid)
    for fingerprint, uids in fp_groups.items():
        if len(uids) > 1:
            findings.append(_finding(
                "DUPLICATE_DEVICE", "high",
                f"{len(uids)} contas compartilham o mesmo dispositivo.",
                uids[0],
            ))
            for uid in uids:
                flags_by_uid[uid].add("high")

    unique_findings = []
    seen = set()
    for finding in findings:
        key = (finding["code"], finding["uid"], finding["detail"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(finding)
    unique_findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["code"], f["uid"]))

    counts = Counter(finding["severity"] for finding in unique_findings)
    recent_total = sum(1 for item in reports if item["received_at"] and item["received_at"] >= cutoff)
    last_seen = max((item["received_at"] for item in reports if item["received_at"]), default=None)

    return {
        "reports": reports,
        "findings": unique_findings[:80],
        "counts": {level: counts.get(level, 0) for level in SEVERITY_ORDER},
        "flags_by_uid": {uid: sorted(levels, key=lambda level: SEVERITY_ORDER[level]) for uid, levels in flags_by_uid.items()},
        "valid_accounts": len(users),
        "reported_accounts": len(reports_by_uid),
        "orphan_accounts": sum(1 for uid in reports_by_uid if uid not in users),
        "duplicate_accounts": len({uid for uids in user_email_groups.values() for uid in uids})
        + len({uid for uids in user_cpf_groups.values() for uid in uids})
        + len({uid for uids in fp_groups.values() if len(uids) > 1 for uid in uids}),
        "total_reports": len(reports),
        "recent_24h": recent_total,
        "latest_by_uid": latest_by_uid,
        "last_seen_at": last_seen,
        "now": now,
    }


def summary_text(intel: dict) -> str:
    if intel["total_reports"] == 0:
        return "Nexus (site): nenhum relato recebido."
    if intel["recent_24h"] == 0:
        when = intel["last_seen_at"].strftime("%d/%m/%Y %H:%M") if intel.get("last_seen_at") else "sem data"
        return f"Nexus (site): nenhum relato nas últimas 24h (último em {when})."
    text = f"Nexus (site): {intel['recent_24h']} relato(s) nas últimas 24h de {intel['reported_accounts']} conta(s)"
    if intel.get("last_seen_at"):
        text += f"; último às {intel['last_seen_at'].strftime('%H:%M')}"
    return text + "."


def audit_financial_consistency(intel, users, pending, now=None) -> dict:
    now = now or datetime.now()
    users = users if isinstance(users, dict) else {}
    pending = pending if isinstance(pending, dict) else {}
    reports_by_uid = defaultdict(list)
    for item in intel.get("reports", []):
        reports_by_uid[item["path_uid"]].append(item)

    candidates = set(intel.get("flags_by_uid", {}).keys())
    for w in pending.values():
        if isinstance(w, dict) and w.get("uid"):
            candidates.add(str(w["uid"]))

    findings = []
    flags_by_uid = defaultdict(set)
    pending_by_uid = defaultdict(list)
    for wid, w in pending.items():
        if isinstance(w, dict) and w.get("uid"):
            pending_by_uid[str(w["uid"])].append((wid, w))

    for uid in sorted(candidates):
        user = users.get(uid)
        withdrawals = pending_by_uid.get(uid, [])
        latest = reports_by_uid.get(uid, [])
        latest = latest[-1] if latest else None
        balance = None
        if isinstance(user, dict):
            try:
                balance = float(user.get("balance") or 0)
            except (TypeError, ValueError):
                balance = None

        total_pending = 0.0
        for _, w in withdrawals:
            try:
                total_pending += float(w.get("amount") or 0)
            except (TypeError, ValueError):
                pass

        if balance is not None and total_pending > balance + 0.01:
            findings.append(_finding(
                "WITHDRAWAL_EXCEEDS_BALANCE", "high",
                f"Saques pendentes (R$ {total_pending:.2f}) acima do saldo da conta (R$ {balance:.2f}).",
                uid,
            ))
            flags_by_uid[uid].add("high")

        if len(withdrawals) > 1:
            findings.append(_finding(
                "DUPLICATE_WITHDRAWAL", "medium",
                f"{len(withdrawals)} solicitações de saque pendentes para a mesma conta.",
                uid,
            ))
            flags_by_uid[uid].add("medium")

        if not latest or not isinstance(user, dict):
            continue

        report = latest["report"]
        recent = latest["received_at"] is not None and latest["received_at"] >= now - timedelta(hours=24)
        if not recent:
            continue

        try:
            reported_ads = int(report.get("ads_watched"))
        except (TypeError, ValueError):
            reported_ads = None
        try:
            ledger_ads = int(user.get("videosWatched") or 0)
        except (TypeError, ValueError):
            ledger_ads = 0

        if reported_ads is not None and reported_ads > ledger_ads:
            findings.append(_finding(
                "REPORT_AHEAD_OF_LEDGER", "medium",
                f"Relato declara {reported_ads} anúncios; conta registra {ledger_ads}.",
                uid,
            ))
            flags_by_uid[uid].add("medium")

        try:
            reported_balance = float(report.get("balance"))
        except (TypeError, ValueError):
            reported_balance = None
        if reported_balance is not None and balance is not None and abs(reported_balance - balance) > 0.01:
            findings.append(_finding(
                "BALANCE_MISMATCH", "medium",
                f"Saldo do relato (R$ {reported_balance:.2f}) difere do ledger (R$ {balance:.2f}).",
                uid,
            ))
            flags_by_uid[uid].add("medium")

    unique_findings = []
    seen = set()
    for finding in findings:
        key = (finding["code"], finding["uid"], finding["detail"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(finding)
    unique_findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["code"], f["uid"]))
    counts = Counter(finding["severity"] for finding in unique_findings)

    return {
        "findings": unique_findings,
        "counts": {level: counts.get(level, 0) for level in SEVERITY_ORDER},
        "flags_by_uid": {uid: sorted(levels, key=lambda level: SEVERITY_ORDER[level]) for uid, levels in flags_by_uid.items()},
        "checked_accounts": len(candidates),
    }


def _max_severity(levels):
    if not levels:
        return "low"
    return sorted(levels, key=lambda level: SEVERITY_ORDER.get(level, 9))[0]


def build_action_plan(intel, audit, financeiro=None, now=None) -> dict:
    now = now or datetime.now()
    financeiro = financeiro or {}
    uids = set(intel.get("flags_by_uid", {}).keys()) | set(audit.get("flags_by_uid", {}).keys())
    actions = []
    for uid in sorted(uids):
        levels = list(intel.get("flags_by_uid", {}).get(uid, [])) + list(audit.get("flags_by_uid", {}).get(uid, []))
        severity = _max_severity(levels)
        codes = set()
        for finding in intel.get("findings", []) + audit.get("findings", []):
            if finding.get("uid") == mask_uid(uid):
                codes.add(finding["code"])
        if severity == "critical":
            recommended = ["BLOCK_ACCOUNT_PENDING_REVIEW", "FREEZE_WITHDRAWALS", "SECOND_ANALYSIS"]
        elif severity == "high":
            recommended = ["HOLD_WITHDRAWALS", "MANUAL_REVIEW", "REAUTHENTICATE_SESSION"]
        elif severity == "medium":
            recommended = ["ENVIRONMENT_PERSONALIZATION", "MONITOR"]
        else:
            recommended = ["MONITOR"]
        actions.append({
            "uid": uid,
            "uid_masked": mask_uid(uid),
            "severity": severity,
            "codes": sorted(codes),
            "actions": recommended,
        })

    actions.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["uid"]))
    counts = Counter(action["severity"] for action in actions)
    questions = []
    if actions:
        questions = [
            "Sentinel: confirme a identidade imutável e a unicidade de e-mail, CPF e dispositivo dos UIDs sinalizados.",
            "Auditor: confirme se saldos, anúncios e saques dos UIDs sinalizados fecham com o ledger.",
            "Nexus: justifique relatos com divergência de saldo/anúncios, rajadas ou dados de identidade alterados.",
            "Financeiro: suspenda aprovações dos UIDs sinalizados até a segunda análise.",
        ]

    plan = {
        "generated_at": now.isoformat(),
        "status": "pending_approval" if actions else "clear",
        "severity": _max_severity([a["severity"] for a in actions]) if actions else "none",
        "counts": {level: counts.get(level, 0) for level in SEVERITY_ORDER},
        "actions": actions[:20],
        "questions": questions,
        "sources": {
            "nexus_reports": intel.get("total_reports", 0),
            "nexus_recent_24h": intel.get("recent_24h", 0),
            "sentinel_findings": len(intel.get("findings", [])),
            "auditor_findings": len(audit.get("findings", [])),
            "pending_withdrawals": financeiro.get("pending_count", 0),
        },
        "requires_admin_approval": True,
    }
    signature = hashlib.sha256(
        json.dumps({"actions": plan["actions"], "status": plan["status"]}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    plan["signature"] = signature
    return plan


def plan_summary(plan: dict) -> str:
    if not plan.get("actions"):
        return "Nenhum plano de ação necessário neste ciclo."
    counts = plan.get("counts", {})
    blocks = sum(1 for action in plan["actions"] if "BLOCK_ACCOUNT_PENDING_REVIEW" in action["actions"])
    holds = sum(1 for action in plan["actions"] if "HOLD_WITHDRAWALS" in action["actions"])
    return (
        f"Plano para {len(plan['actions'])} conta(s): {blocks} bloqueio(s) preventivo(s), "
        f"{holds} retenção(ões) de saque; {counts.get('critical', 0)} crítico(s), "
        f"{counts.get('high', 0)} alto(s), {counts.get('medium', 0)} médio(s)."
    )
