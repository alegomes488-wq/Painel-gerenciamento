"""Painel HUB — testes do motor de correlação da Cyber Core IA (funções puras)."""
from app.services.hub_correlator import correlate, health_score, worst_severity


def _base_snapshot():
    return {
        "performance": {"web": {}, "app": {}, "api": {}},
        "tracking": {"sessions": {}, "funnels": {}, "tickets": {}},
        "security": {"apk": {}, "network": {}, "auth": {}, "vulnerabilities": {}},
    }


def test_correlate_snapshot_vazio_sem_findings():
    assert correlate(_base_snapshot()) == []
    assert correlate({}) == []
    assert correlate(None) == []


def test_p1_crash_rate_por_versao_com_tickets_de_login():
    """Exemplo do briefing: crash rate sobe após update + tickets 'erro ao logar'."""
    snap = _base_snapshot()
    snap["performance"]["app"]["by_version"] = {
        "2.1.0": {"crash_rate": 6.5, "previous_crash_rate": 1.0, "sessions": 500},
        "2.0.9": {"crash_rate": 1.2, "previous_crash_rate": 1.1, "sessions": 300},
    }
    snap["performance"]["app"]["by_device"] = {"Samsung Galaxy S23": {"crash_rate": 9.0}}
    snap["tracking"]["tickets"]["top_reasons"] = {"erro ao logar": 42, "pagamento": 5}

    findings = correlate(snap)
    assert findings, "deveria gerar correlação"
    top = findings[0]
    assert top["severity"] == "critical"
    assert top["pillar"] == "performance"
    assert "2.1.0" in top["title"]
    assert "Samsung" in top["message"]
    assert top["recommended_action"]["type"] == "block_rollout"


def test_p1_crash_rate_alto_sem_tickets_e_high():
    snap = _base_snapshot()
    snap["performance"]["app"]["by_version"] = {
        "3.0.0": {"crash_rate": 8.0, "previous_crash_rate": 2.0},
    }
    snap["tracking"]["tickets"]["top_reasons"] = {"saque": 10}

    findings = correlate(snap)
    assert findings
    assert findings[0]["severity"] == "high"
    assert findings[0]["recommended_action"] is None


def test_p2_degradacao_web_vitals_com_5xx():
    snap = _base_snapshot()
    snap["performance"]["web"] = {"lcp_ms": 5200, "ttfb_ms": 1200, "error_rate_5xx": 4.5}
    findings = correlate(snap)
    assert any(f["pillar"] == "performance" and f["severity"] == "high" for f in findings)


def test_p2_apenas_5xx_e_medium():
    snap = _base_snapshot()
    snap["performance"]["web"] = {"lcp_ms": 1200, "ttfb_ms": 200, "error_rate_5xx": 3.0}
    findings = correlate(snap)
    assert any(f["severity"] == "medium" and "5xx" in f["title"] for f in findings)


def test_p3_anr_acima_do_limite():
    snap = _base_snapshot()
    snap["performance"]["app"] = {"anr_rate": 0.9}
    findings = correlate(snap)
    assert any("ANR" in f["title"] for f in findings)


def test_s1_assinatura_invalida_com_pico_de_rps_recomenda_quarentena():
    snap = _base_snapshot()
    snap["security"]["apk"] = {"invalid_signature_hits": 12, "hot_ip": "203.0.113.9"}
    snap["performance"]["api"] = {"rps": 120}
    findings = correlate(snap)
    assert findings
    top = findings[0]
    assert top["severity"] == "critical"
    assert top["pillar"] == "security"
    action = top["recommended_action"]
    assert action["type"] == "quarantine_ip"
    assert action["params"]["ip"] == "203.0.113.9"


def test_s1_assinatura_invalida_sem_trafego_e_high_sem_acao():
    snap = _base_snapshot()
    snap["security"]["apk"] = {"invalid_signature_hits": 3, "repackage_alerts": 2}
    findings = correlate(snap)
    assert any(f["severity"] == "high" and f["recommended_action"] is None for f in findings)


def test_s2_credential_stuffing():
    snap = _base_snapshot()
    snap["security"]["auth"] = {"login_failures_burst": 500, "fake_accounts_bulk": 80}
    findings = correlate(snap)
    assert any(f["severity"] == "high" and "Credential Stuffing" in f["title"] for f in findings)


def test_s3_impossible_travel():
    snap = _base_snapshot()
    snap["security"]["auth"] = {"impossible_travel": 3}
    findings = correlate(snap)
    assert any("localizações impossíveis" in f["title"] for f in findings)


def test_s4_root_jailbreak_gera_nota_de_copilot():
    snap = _base_snapshot()
    snap["security"]["apk"] = {"root_devices": 4, "jailbreak_devices": 1}
    findings = correlate(snap)
    assert any("Root" in f["title"] and "desativar o Root" in f["message"] for f in findings)


def test_s5_cve_critica():
    snap = _base_snapshot()
    snap["security"]["vulnerabilities"] = {
        "web": [{"package": "lodash", "version": "4.17.11", "cve": "CVE-2020-8203", "severity": "critical"}],
        "app": [],
    }
    findings = correlate(snap)
    assert any("CVE" in f["title"] for f in findings)


def test_t1_abandono_de_funil():
    snap = _base_snapshot()
    snap["tracking"]["funnels"] = {"steps": [
        {"id": "s1", "name": "Cadastro", "entered": 1000, "converted": 900},
        {"id": "s2", "name": "Login", "entered": 900, "converted": 300},
    ]}
    findings = correlate(snap)
    assert any("Login" in f["title"] for f in findings)


def test_t2_suporte_saturado():
    snap = _base_snapshot()
    snap["tracking"]["tickets"] = {"open": 90, "avg_minutes": 360, "top_reasons": {"lento": 30}}
    findings = correlate(snap)
    assert any("Suporte saturado" in f["title"] for f in findings)


def test_worst_severity_e_health_score():
    snap = _base_snapshot()
    snap["security"]["auth"] = {"impossible_travel": 1}  # high
    snap["performance"]["app"] = {"anr_rate": 1.0}       # medium
    findings = correlate(snap)
    assert worst_severity(findings) == "high"
    assert worst_severity([]) is None

    health = health_score(findings)
    assert 0 <= health["score"] <= 100
    assert health["per_pillar"]["security"] == 100 - 15
    assert health["per_pillar"]["performance"] == 100 - 8
    assert health["per_pillar"]["tracking"] == 100
    assert health["level"] in ("ESTAVEL", "ATENCAO", "CRITICO", "RISCO_DE_OUTAGE")


def test_health_score_sem_correlacoes_e_estavel():
    health = health_score([])
    assert health["score"] == 100
    assert health["level"] == "ESTAVEL"


def test_thresholds_customizadas():
    snap = _base_snapshot()
    snap["thresholds"] = {"anr_rate_bad": 5.0}
    snap["performance"]["app"] = {"anr_rate": 1.0}
    assert not any("ANR" in f["title"] for f in correlate(snap))
