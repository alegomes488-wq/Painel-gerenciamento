"""
Testes NEGATIVOS da guarda de estáticos (TAREFA 6.1).

Duas camadas:
  1. `is_blocked_static_path` — função pura, testada direto (sem I/O).
  2. `GuardedStaticFiles` montada num app real com TestClient — prova que o
     que importa (o que o cliente HTTP recebe) mudou.

Regra que estes testes existem para provar: um segredo dentro de www/admin/
NUNCA chega ao cliente. Um teste que só verifica a função pura não prova
isto — o StaticFiles do Starlette tem o próprio `lookup_path`, e foi
justamente ele que vazou as credenciais.
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core.static_guard import (
    BLOCKED_MARKERS,
    BLOCKED_ROOTS,
    GuardedStaticFiles,
    is_blocked_static_path,
)

# ───────────────────────────────────────────────────────────────────────────
# 1. Função pura
# ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "backend/.env",
        "backend/firebase-adminsdk.json",
        "backend/app/main.py",
        "backend/",
        "backend",
        "BACKEND/.env",
        "Backend/app/core/security.py",
        ".env",
        "js/.env",
        "js/config.env",
        "deep/nested/.git/config",
        "www/admin/backend/.env",
        "x.pem",
        "x.key",
        "x.p12",
        "server.p12",
        # Copias de trabalho dentro da raiz estatica (FASE 4, item 4.1).
        "styles.css.bak-audit-20261005",
        "index.html.bak-audit-20261005",
        "styles.css.truncado-20261005",
        "js/main.js.bak-audit-20261005",
        "app.js.bak-lgpd-20261003",
        "x.bak",
    ],
)
def test_bloqueia_caminho_sensivel(path):
    assert is_blocked_static_path(path) is True, f"{path} deveria ser bloqueado"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/",
        "index.html",
        "styles.css",
        "sw.js",
        "firebase-messaging-sw.js",
        "favicon.svg",
        "icons.svg",
        "js/main.js",
        "js/modules/watch.js",
        "js/modules/maintenance.js",
        "lib/chart.js",
        "LEIA-ME.txt",
        # "backendend.js" NAO pode ser barrado: o match e por segmento exato.
        "backendend.js",
        "js/backend.js",
        "some/backendish/file.js",
        "estilo.css",
        "app.js",
        "a.b.c.js",
    ],
)
def test_nao_bloqueia_asset_do_painel(path):
    assert is_blocked_static_path(path) is False, f"{path} NÃO deveria ser bloqueado"


def test_roots_bloqueados_sao_explicitos_e_auditives():
    """A lista precisa ser pequena e nomeada — nao um filtro aberto."""
    assert BLOCKED_ROOTS == frozenset({"backend"})


def test_marcadores_de_backup_casam_por_substring_nao_por_sufixo():
    """Este teste existe por causa de um erro que eu quase escrevi.

    A primeira versao da correcao usou `BLOCKED_SUFFIXES` com `.bak-audit-` e
    casou com `last.endswith(suf)`. Isso NAO bloqueia
    `styles.css.bak-audit-20261005`, porque o nome termina em `-20261005`.

    Se este teste falhar, alguem trocou substring por sufixo de novo.
    """
    assert BLOCKED_MARKERS == frozenset({".bak", ".truncado"})

    for nome in (
        "styles.css.bak-audit-20261005",
        "index.html.bak-audit-20261005",
        "styles.css.truncado-20261005",
    ):
        # A prova de que sufixo nao serviria:
        assert not nome.endswith(".bak"), f"{nome} NAO termina em .bak"
        assert not nome.endswith(".bak-audit-"), f"{nome} NAO termina em .bak-audit-"
        assert not nome.endswith(".truncado"), f"{nome} NAO termina em .truncado"
        # E a prova de que substring funciona:
        assert is_blocked_static_path(nome) is True


def test_marcador_nao_engole_asset_legitimo():
    """.bak e .truncado nao podem aparecer em nenhum asset que o painel usa."""
    for nome in (
        "index.html",
        "styles.css",
        "sw.js",
        "firebase-messaging-sw.js",
        "favicon.svg",
        "icons.svg",
        "LEIA-ME.txt",
        "js/main.js",
        "js/modules/maintenance.js",
        "lib/chart.js",
    ):
        assert is_blocked_static_path(nome) is False, f"{nome} foi barrado por engano"


def test_path_vazio_e_raiz_sao_permitidos():
    """`/` tem que chegar ao index.html (o painel abre em /)."""
    assert is_blocked_static_path("") is False
    assert is_blocked_static_path("/") is False


def test_normaliza_barras_e_prefixo_dot():
    assert is_blocked_static_path("./backend/.env") is True
    assert is_blocked_static_path("./js/main.js") is False
    assert is_blocked_static_path("backend\\.env") is True
    assert is_blocked_static_path("/backend/.env") is True


# ───────────────────────────────────────────────────────────────────────────
# 2. Comportamento HTTP (o que importa)
# ───────────────────────────────────────────────────────────────────────────

ADMIN_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "www", "admin"
)


def _client(cls):
    app = FastAPI()
    app.mount("/", cls(directory=ADMIN_DIR, html=True), name="admin")
    return TestClient(app)


@pytest.mark.skipif(
    not os.path.isdir(ADMIN_DIR), reason="www/admin ausente neste checkout"
)
class TestHTTP:
    """Precisa do www/admin real: é lá que a credencial vazada estava."""

    @pytest.mark.parametrize(
        "caminho",
        [
            "/backend/.env",
            "/backend/firebase-adminsdk.json",
            "/backend/diagnosticar.py",
            "/backend/renovar_admin.py",
            "/backend/Dockerfile",
            "/backend/app/main.py",
            "/.env",
        ],
    )
    def test_segredo_ou_codigo_de_backend_responde_404(self, caminho):
        r = _client(GuardedStaticFiles).get(caminho)
        assert r.status_code == 404, (
            f"{caminho} devolvia {r.status_code} — credencial exposta"
        )
        # Reforço: o corpo não pode conter material de segredo.
        corpo = r.text.lower()
        for marca in ("begin private key", "api_key=", "private_key"):
            assert marca not in corpo, f"{caminho} vazou {marca!r} no corpo do 404"

    @pytest.mark.parametrize(
        "caminho",
        ["/index.html", "/styles.css", "/sw.js", "/js/main.js", "/favicon.svg"],
    )
    def test_asset_do_painel_continua_servido(self, caminho):
        r = _client(GuardedStaticFiles).get(caminho)
        assert r.status_code == 200, f"{caminho} parou de ser servido ({r.status_code})"

    def test_404_da_guarda_e_indistinguivel_do_404_normal(self):
        """Não pode vazar que a pasta existe (oráculo para sondagem)."""
        g = _client(GuardedStaticFiles)
        p = _client(StaticFiles)
        bloqueado = g.get("/backend/.env")
        inexistente = g.get("/nao/existe/nada.js")
        antes_guarda = p.get("/nao/existe/nada.js")

        assert bloqueado.status_code == inexistente.status_code == 404
        assert bloqueado.headers.get("content-length") == \
            inexistente.headers.get("content-length"), "tamanho de resposta diferente"
        assert bloqueado.text == antes_guarda.text or \
            bloqueado.headers.get("content-type") == antes_guarda.headers.get(
                "content-type"
            ), "formato de resposta diferente do 404 normal"


@pytest.mark.skipif(
    not os.path.isdir(ADMIN_DIR), reason="www/admin ausente neste checkout"
)
def test_controle_o_que_a_guarda_muda_e_realmente_o_static_files_puro():
    """Controle negativo — prova que o teste acima tem dentes.

    Aqui o esperado e o OPOSTO do teste principal: o `StaticFiles` puro DEVE
    entregar o arquivo. Se este teste passa, esta demonstrado que
    `StaticFiles` puro vaza e que e a `GuardedStaticFiles` que impede.

    Se algum dia este teste comecar a falhar, o `www/admin/backend/` deixou de
    existir — e ai o teste principal perde a condicao que torna o 404
    significativo.
    """
    puro = _client(StaticFiles).get("/backend/.env")
    guarda = _client(GuardedStaticFiles).get("/backend/.env")

    assert puro.status_code == 200, (
        "StaticFiles puro deixou de servir /backend/.env. Se o arquivo sumiu, "
        "este controle nao prova mais nada — reavalie o teste principal."
    )
    assert guarda.status_code == 404, "a guarda precisa continuar barrando"

    # A diferenca entre os dois e exatamente o que a guarda corrige.
    assert puro.status_code != guarda.status_code