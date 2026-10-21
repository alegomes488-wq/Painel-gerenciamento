"""Telemetria — métricas opcionais por agente (console reativo)."""
from app.routers import telemetry


def test_sanitize_metrics_normaliza_e_descarta_invalidas():
    metrics = [
        {"key": "success", "label": "Taxa de sucesso", "value": "99.4%"},
        {"key": "tx", "value": 42},
        {"key": "chave invalida", "value": "x"},
        {"key": "errors", "label": "Erros", "value": 2},
        {"key": "online", "value": True},
        {"key": "vazio", "value": None},
    ]

    assert telemetry._sanitize_metrics(metrics) == [
        {"key": "success", "label": "Taxa de sucesso", "value": "99.4%"},
        {"key": "tx", "label": "tx", "value": "42"},
        {"key": "errors", "label": "Erros", "value": "2"},
        {"key": "online", "label": "online", "value": "Sim"},
    ]


def test_sanitize_metrics_limita_seis_e_ignora_nao_lista():
    metrics = [{"key": f"k{i}", "value": i} for i in range(10)]
    assert len(telemetry._sanitize_metrics(metrics)) == 6
    assert telemetry._sanitize_metrics({"key": "x", "value": 1}) == []


def test_enqueue_event_inclui_metrics():
    telemetry._event_buffer.clear()
    event = telemetry._enqueue_event(
        "sentinel",
        "running",
        metrics=[{"key": "threats", "label": "Ameaças bloqueadas", "value": 12}],
    )

    assert event["metrics"] == [{"key": "threats", "label": "Ameaças bloqueadas", "value": "12"}]
