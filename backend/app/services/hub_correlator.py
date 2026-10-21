"""
Cyber Core IA — Motor de Correlação de Eventos do Painel HUB.

Funções PURAS (sem I/O, sem Firebase): recebem o snapshot consolidado dos
três pilares do HUB (Desempenho / Acompanhamento / Segurança) e devolvem as
correlações detectadas, cada uma com severidade, mensagem de contexto para o
copilot do agente de suporte e — quando aplicável — a ação recomendada.

Regras implementadas (v1):
  P1  Crash Rate por versão do APK + tickets de suporte com tags de login/erro
  P2  Queda brusca de performance web (Core Web Vitals + 5xx)
  P3  ANR elevado no app
  T1  Abandono crítico de funil
  T2  Saturação do suporte (volume + TMA altos)
  S1  Assinatura de APK inválida + pico de requisições -> quarentena de IP
  S2  Credential Stuffing (falhas de login em massa + contas falsas em lote)
  S3  Acesso geograficamente impossível (fraude de identidade)
  S4  Dispositivos com Root/Jailbreak ativos
  S5  Vulnerabilidades críticas (CVE) ativas
"""
import uuid
from datetime import datetime

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

PILLAR_LABELS = {
    "performance": "Desempenho",
    "tracking": "Acompanhamento",
    "security": "Segurança",
}

# Limiares padrão (sobrescrevíveis via snapshot["thresholds"])
DEFAULT_THRESHOLDS = {
    "crash_delta_pp": 3.0,          # pontos percentuais de aumento do Crash Rate
    "api_rps_burst": 50.0,          # req/s para considerar "requisições em massa"
    "lcp_ms_bad": 4000.0,
    "ttfb_ms_bad": 800.0,
    "error_5xx_bad": 2.0,           # %
    "anr_rate_bad": 0.5,            # %
    "funnel_conversion_bad": 40.0,  # %
    "tickets_open_bad": 50,
    "tickets_tma_bad_minutes": 240.0,
    "login_failures_bad": 100,
    "fake_accounts_bad": 10,
}

# Tags de ticket que indicam problema de autenticação/experiência de login
LOGIN_TICKET_KEYWORDS = ("log", "login", "entrar", "acess", "senha", "cadastro", "erro")


def _f(value, default=0.0):
    """Converte para float seguro."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default=0):
    """Converte para int seguro."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _get(data: dict, *path, default=None):
    """Acesso aninhado seguro: _get(d, 'a', 'b', 'c')."""
    cur = data
    for part in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def _thresholds(snapshot: dict) -> dict:
    merged = dict(DEFAULT_THRESHOLDS)
    custom = snapshot.get("thresholds") if isinstance(snapshot.get("thresholds"), dict) else {}
    for key, value in custom.items():
        if key in DEFAULT_THRESHOLDS:
            merged[key] = _f(value, DEFAULT_THRESHOLDS[key])
    return merged


def _correlation(pillar, severity, title, message, evidence=None, action=None):
    return {
        "id": uuid.uuid4().hex[:12],
        "pillar": pillar,
        "severity": severity,
        "title": title,
        "message": message,
        "evidence": [str(e) for e in (evidence or [])],
        "recommended_action": action,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def _ticket_tags_indicate_login(tickets: dict) -> list:
    """Retorna as tags de tickets relacionadas a login/erros."""
    hits = []
    top_reasons = _get(tickets, "top_reasons", default={}) or {}
    if not isinstance(top_reasons, dict):
        return hits
    for tag, count in top_reasons.items():
        tag_low = str(tag).lower()
        if any(kw in tag_low for kw in LOGIN_TICKET_KEYWORDS) and _i(count, 0) > 0:
            hits.append(f"{tag} ({_i(count)} chamados)")
    return hits


def _worst_version_segment(app: dict) -> tuple:
    """Retorna (versão, dados) com maior delta de Crash Rate."""
    by_version = _get(app, "by_version", default={}) or {}
    worst = (None, None, -1.0)  # (versão, dados, delta)
    if not isinstance(by_version, dict):
        return None, None
    for version, data in by_version.items():
        if not isinstance(data, dict):
            continue
        current = _f(data.get("crash_rate"))
        previous = _f(data.get("previous_crash_rate"), current)
        delta = current - previous
        if delta > worst[2]:
            worst = (str(version), data, delta)
    return worst[0], worst[1] if worst[0] else None


def _worst_device_segment(app: dict) -> tuple:
    by_device = _get(app, "by_device", default={}) or {}
    worst = (None, None, -1.0)
    if not isinstance(by_device, dict):
        return None, None
    for device, data in by_device.items():
        if not isinstance(data, dict):
            continue
        crash = _f(data.get("crash_rate"))
        if crash > worst[2]:
            worst = (str(device), data, crash)
    return worst[0], worst[1] if worst[0] else None


def _hot_ip(snapshot: dict) -> str:
    """Busca o IP mais quente reportado nos módulos de segurança."""
    for path in (
        ("security", "network", "hot_ip"),
        ("security", "auth", "hot_ip"),
        ("security", "apk", "hot_ip"),
    ):
        ip = _get(snapshot, *path, default="")
        if isinstance(ip, str) and ip.strip():
            return ip.strip()
    return ""


def correlate(snapshot: dict) -> list:
    """
    Executa todas as regras de correlação sobre o snapshot consolidado.
    Retorna lista ordenada por severidade (critical primeiro).
    """
    if not isinstance(snapshot, dict):
        return []
    th = _thresholds(snapshot)
    perf = snapshot.get("performance") or {}
    track = snapshot.get("tracking") or {}
    sec = snapshot.get("security") or {}
    web = perf.get("web") or {}
    app = perf.get("app") or {}
    api = perf.get("api") or {}
    sessions = track.get("sessions") or {}
    funnels = track.get("funnels") or {}
    tickets = track.get("tickets") or {}
    apk = sec.get("apk") or {}
    network = sec.get("network") or {}
    auth = sec.get("auth") or {}
    vulns = sec.get("vulnerabilities") or {}

    findings = []

    # ── P1: Crash Rate por versão + tickets de login/erro ──────────────────
    version, version_data = _worst_version_segment(app)
    if version and version_data:
        delta = _f(version_data.get("crash_rate")) - _f(
            version_data.get("previous_crash_rate"), _f(version_data.get("crash_rate"))
        )
        if delta >= th["crash_delta_pp"]:
            login_tags = _ticket_tags_indicate_login(tickets)
            worst_device, _ = _worst_device_segment(app)
            if login_tags:
                findings.append(_correlation(
                    "performance",
                    "critical",
                    f"Versão {version} do APK com Crash Rate elevado + tickets de login",
                    (
                        f"A versão {version} do app subiu {delta:.1f}pp no Crash Rate e os "
                        f"chamados de suporte com tags de login/erro aumentaram em paralelo "
                        f"({'; '.join(login_tags)})."
                        + (f" Dispositivo mais afetado: {worst_device}." if worst_device else "")
                        + " Oriente o time a bloquear a atualização desta versão e priorizar o hotfix."
                    ),
                    evidence=[
                        f"crash_rate={_f(version_data.get('crash_rate')):.2f}%",
                        f"delta={delta:.2f}pp",
                        f"tickets_login={'; '.join(login_tags)}",
                    ],
                    action={
                        "type": "block_rollout",
                        "label": f"Bloquear rollout da versão {version}",
                        "params": {"app_version": version},
                    },
                ))
            else:
                findings.append(_correlation(
                    "performance",
                    "high",
                    f"Crash Rate da versão {version} subiu {delta:.1f}pp",
                    (
                        f"A versão {version} do app registrou alta de {delta:.1f}pp no Crash Rate. "
                        f"Ainda não há tickets de login correlatos — monitore as próximas horas "
                        f"para confirmar se é regressão de release."
                    ),
                    evidence=[f"crash_rate={_f(version_data.get('crash_rate')):.2f}%"],
                ))

    # ── P2: Core Web Vitals + taxa de erro 5xx ─────────────────────────────
    lcp = _f(web.get("lcp_ms"))
    ttfb = _f(web.get("ttfb_ms"))
    err5xx = _f(web.get("error_rate_5xx"))
    if (lcp >= th["lcp_ms_bad"] or ttfb >= th["ttfb_ms_bad"]) and err5xx >= th["error_5xx_bad"]:
        findings.append(_correlation(
            "performance",
            "high",
            "Degradação do site: Core Web Vitals ruins somados a erro 5xx",
            (
                f"O site está com LCP de {lcp:.0f}ms e TTFB de {ttfb:.0f}ms, além de "
                f"{err5xx:.1f}% de respostas 5xx. Padrão compatível com instabilidade no "
                f"back-end afetando o carregamento — verifique deploy recente e saúde da API."
            ),
            evidence=[f"lcp_ms={lcp:.0f}", f"ttfb_ms={ttfb:.0f}", f"error_rate_5xx={err5xx:.2f}%"],
        ))
    elif err5xx >= th["error_5xx_bad"]:
        findings.append(_correlation(
            "performance",
            "medium",
            "Taxa de erro 5xx acima do esperado",
            f"Respostas 5xx em {err5xx:.1f}% das requisições do site.",
            evidence=[f"error_rate_5xx={err5xx:.2f}%"],
        ))

    # ── P3: ANR elevado ────────────────────────────────────────────────────
    anr = _f(app.get("anr_rate"))
    if anr >= th["anr_rate_bad"]:
        findings.append(_correlation(
            "performance",
            "medium",
            "App Not Responding (ANR) acima do limite",
            (
                f"Taxa de ANR em {anr:.2f}% — o app está travando em dispositivos reais. "
                f"Combine com os dados de Frozen Frames para localizar a tela travada."
            ),
            evidence=[f"anr_rate={anr:.2f}%"],
        ))

    # ── T1: Abandono crítico de funil ──────────────────────────────────────
    steps = funnels.get("steps") if isinstance(funnels.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict):
            continue
        entered = _f(step.get("entered"))
        converted = _f(step.get("converted"))
        if entered <= 0:
            continue
        conversion = (converted / entered) * 100.0
        if conversion < th["funnel_conversion_bad"]:
            findings.append(_correlation(
                "tracking",
                "medium",
                f"Abandono crítico no funil: {step.get('name', step.get('id', '?'))}",
                (
                    f"A etapa '{step.get('name', step.get('id', '?'))}' converte apenas "
                    f"{conversion:.1f}% ({int(converted)}/{int(entered)}). Identifique o ponto "
                    f"de abandono antes que afete a aquisição."
                ),
                evidence=[f"conversion={conversion:.1f}%"],
            ))

    # ── T2: Saturação do suporte ───────────────────────────────────────────
    open_tickets = _i(tickets.get("open"))
    tma = _f(tickets.get("avg_minutes"))
    if open_tickets >= th["tickets_open_bad"] and tma >= th["tickets_tma_bad_minutes"]:
        top = _ticket_tags_indicate_login(tickets) or [
            f"{k} ({v})" for k, v in list((_get(tickets, "top_reasons", default={}) or {}).items())[:3]
        ]
        findings.append(_correlation(
            "tracking",
            "medium",
            "Suporte saturado: volume e tempo médio de atendimento altos",
            (
                f"{open_tickets} chamados em aberto com TMA de {tma:.0f} minutos. "
                f"Principais motivos: {'; '.join(top) if top else 'não classificado'}."
            ),
            evidence=[f"open={open_tickets}", f"avg_minutes={tma:.0f}"],
        ))

    # ── S1: Assinatura de APK inválida + pico de requisições → quarentena ──
    invalid_sig = _i(apk.get("invalid_signature_hits"))
    tamper = _i(apk.get("tamper_attempts")) + _i(apk.get("repackage_alerts"))
    rps = _f(api.get("rps"))
    suspicious = _i(network.get("suspicious_requests")) + _i(network.get("emulator_requests"))
    if invalid_sig > 0 and (rps >= th["api_rps_burst"] or suspicious >= th["api_rps_burst"]):
        ip = _hot_ip(snapshot)
        action = None
        if ip:
            action = {
                "type": "quarantine_ip",
                "label": f"Colocar {ip} em quarentena",
                "params": {"ip": ip},
            }
        findings.append(_correlation(
            "security",
            "critical",
            "APK com assinatura inválida gerando requisições em massa",
            (
                f"Foram detectadas {invalid_sig} requisições com assinatura de APK inválida "
                f"(possível reempacotamento/clonagem) com tráfego suspeito "
                f"(rps={rps:.0f}, suspeitos={suspicious})"
                + (f" originadas de {ip}." if ip else ".")
                + (" A Cyber Core IA recomenda cortar o token de acesso e colocar o IP em quarentena."
                   if ip else " Informe o IP de origem para permitir a quarentena automática.")
            ),
            evidence=[
                f"invalid_signature_hits={invalid_sig}",
                f"tamper_attempts={tamper}",
                f"rps={rps:.0f}",
                f"hot_ip={ip or 'não informado'}",
            ],
            action=action,
        ))
    elif invalid_sig > 0 or tamper > 0:
        findings.append(_correlation(
            "security",
            "high",
            "Tentativas de violação de integridade do APK",
            (
                f"{invalid_sig} assinaturas inválidas e {tamper} tentativas de "
                f"engenharia reversa/reempacotamento detectadas."
            ),
            evidence=[f"invalid_signature_hits={invalid_sig}", f"tamper_total={tamper}"],
        ))

    # ── S2: Credential Stuffing ────────────────────────────────────────────
    login_fail = _i(auth.get("login_failures_burst"))
    fake_accounts = _i(auth.get("fake_accounts_bulk"))
    if login_fail >= th["login_failures_bad"] and fake_accounts >= th["fake_accounts_bad"]:
        findings.append(_correlation(
            "security",
            "high",
            "Ataque de Credential Stuffing com criação de contas em lote",
            (
                f"{login_fail} falhas de login em massa e {fake_accounts} contas criadas em lote. "
                f"Padrão típico de credential stuffing — aumente o rate-limit de login e "
                f"exija verificação de e-mail."
            ),
            evidence=[f"login_failures_burst={login_fail}", f"fake_accounts_bulk={fake_accounts}"],
            action={
                "type": "tighten_login_rate_limit",
                "label": "Redobrar rate-limit de login",
                "params": {},
            },
        ))
    elif login_fail >= th["login_failures_bad"]:
        findings.append(_correlation(
            "security",
            "medium",
            "Pico de falhas de login",
            f"{login_fail} falhas de login concentradas — monitore possível varredura de senhas.",
            evidence=[f"login_failures_burst={login_fail}"],
        ))

    # ── S3: Acesso geograficamente impossível ──────────────────────────────
    impossible = _i(auth.get("impossible_travel"))
    if impossible > 0:
        findings.append(_correlation(
            "security",
            "high",
            "Acessos simultâneos de localizações impossíveis",
            (
                f"{impossible} ocorrência(s) de acesso simultâneo de IPs geograficamente "
                f"incompatíveis — forte indício de fraude de identidade/conta roubada. "
                f"Revise sessões ativas e force reautenticação."
            ),
            evidence=[f"impossible_travel={impossible}"],
        ))

    # ── S4: Root / Jailbreak ───────────────────────────────────────────────
    root = _i(apk.get("root_devices"))
    jail = _i(apk.get("jailbreak_devices"))
    if root > 0 or jail > 0:
        findings.append(_correlation(
            "security",
            "medium",
            "Dispositivos com Root/Jailbreak ativos na base",
            (
                f"{root} dispositivo(s) com Root e {jail} com Jailbreak tentaram usar o app. "
                f"Pagamentos são bloqueados por segurança nestes dispositivos — se o usuário "
                f"abrir chamado sobre 'pagamento não funciona', oriente a desativar o Root."
            ),
            evidence=[f"root_devices={root}", f"jailbreak_devices={jail}"],
        ))

    # ── S5: Vulnerabilidades críticas ──────────────────────────────────────
    critical_cves = []
    for scope in ("web", "app"):
        items = vulns.get(scope) if isinstance(vulns.get(scope), list) else []
        for item in items:
            if isinstance(item, dict) and str(item.get("severity", "")).lower() == "critical":
                critical_cves.append(
                    f"{scope}:{item.get('package', '?')} {item.get('version', '?')} ({item.get('cve', 'CVE?')})"
                )
    if critical_cves:
        findings.append(_correlation(
            "security",
            "high",
            "Vulnerabilidades críticas (CVE) ativas",
            (
                f"{len(critical_cves)} dependência(s) com CVE crítica ativa: "
                f"{'; '.join(critical_cves[:5])}. Priorize o upgrade."
            ),
            evidence=critical_cves[:10],
        ))

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    return findings


def worst_severity(correlations: list) -> str:
    """Retorna a severidade mais alta da lista (ou None)."""
    if not correlations:
        return None
    return min(
        (c.get("severity") for c in correlations if isinstance(c, dict)),
        key=lambda s: SEVERITY_ORDER.get(s, 9),
        default=None,
    )


def health_score(correlations: list) -> dict:
    """
    Calcula o score de saúde (0-100) por pilar e global a partir das correlações.
    Pesos: critical -30, high -15, medium -8, low -3.
    """
    weights = {"critical": 30, "high": 15, "medium": 8, "low": 3}
    per_pillar = {"performance": 100, "tracking": 100, "security": 100}
    for corr in correlations:
        if not isinstance(corr, dict):
            continue
        pillar = corr.get("pillar")
        weight = weights.get(corr.get("severity"), 0)
        if pillar in per_pillar:
            per_pillar[pillar] = max(0, per_pillar[pillar] - weight)
    overall = int(round(sum(per_pillar.values()) / len(per_pillar)))
    if overall >= 90:
        level = "ESTAVEL"
    elif overall >= 70:
        level = "ATENCAO"
    elif overall >= 40:
        level = "CRITICO"
    else:
        level = "RISCO_DE_OUTAGE"
    return {"score": overall, "level": level, "per_pillar": per_pillar}
