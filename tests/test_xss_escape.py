"""TAREFA 4.3: XSS regressão — escapeHtml DOM-based neutraliza payloads clássicos."""
import pytest


def test_escape_html_neutralizes_script_tags(monkeypatch):
    """Payload <script>alert(1)</script> é escapado (não executa)."""
    from app.routers.projects import sanitize_string
    result = sanitize_string('<script>alert(1)</script>', 200)
    assert '<script>' not in result
    assert '&lt;script&gt;' in result


def test_escape_html_neutralizes_event_handlers(monkeypatch):
    from app.routers.projects import sanitize_string
    result = sanitize_string('<img src=x onerror=alert(1)>', 200)
    # A TAG fica como texto literal (&lt;img ... &gt;), logo O onerror não é um atributo
    # HTML executável — o navegador renderiza como texto, não como elemento.
    assert result.startswith('&lt;img')
    assert result.endswith('&gt;')
    assert '<img' not in result  # nenhuma tag de abertura real sobrevive


def test_escape_html_removes_null_bytes(monkeypatch):
    from app.routers.projects import sanitize_string
    assert '\x00' not in sanitize_string('a\x00b', 10)