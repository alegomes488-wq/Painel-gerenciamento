"""
TAREFA 5.5 (autorizado) — 429 do verifyToken é limite de taxa, não token ruim.

O QUE ESTE TESTE PROVA

Antes da correção, `AppCheckMiddleware._verify_appcheck_token` tratava 429
igual a qualquer status inesperado e devolvia `False` — que o `dispatch`
convertia em **401 "App Check token invalid"**. O frontend lia "token ruim",
pedia um token novo, e a troca estourava o limite de novo. Ciclo
autoalimentado; é o que aparece como `app-check/throttled` no console.

A correção devolve `None` (indisponível) para 429, e o `dispatch` já mapeava
`None` para 503. Além disso o 503 agora leva `Retry-After`.

TRÊS CAMADAS DE PROVA

1. `_verify_appcheck_token` com `httpx.post` stubado por status — prova o
   mapeamento bruto, sem HTTP nem FastAPI.
2. Resposta HTTP real via TestClient — prova o que o cliente recebe, que é o
   que importa. Um teste que só verifica o retorno da função não prova que o
   código HTTP mudou.
3. Controle negativo — afirma que o comportamento ANTIGO (429 -> False/401)
   é diferente do novo. Sem isso, os testes acima passariam mesmo se a
   correção fosse revertida, porque o stub é meu e não do Google.

RESALVA HONESTA

`httpx.post` está stubado. Estes testes provam o que o backend FAZ com cada
status; não provam que o Google devolve 429 neste volume, nem qual é o
limite. Isso só se confirma com os logs reais do middleware.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def appcheck_app(monkeypatch):
    from app.middleware.appcheck import AppCheckMiddleware

    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-proj")
    monkeypatch.setenv("FIREBASE_APP_ID", "test-app")
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")

    app = FastAPI()

    @app.get("/api/probe")
    async def probe():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "online"}

    app.add_middleware(AppCheckMiddleware)
    return app


@pytest.fixture
def verify_real(monkeypatch):
    """Instancia o middleware de verdade, com credencial e HTTP stubados.

    Devolve uma funcao que recebe o status HTTP do verifyToken e devolve o
    que `_verify_appcheck_token` respondeu.
    """
    from app.middleware import appcheck as ac

    # Sem isto, `_verify_appcheck_token` aborta em "FIREBASE_APP_ID nao
    # configurado" e devolve False ANTES de chegar no httpx.post — o que faria
    # todos os testes da camada 1 medirem o mesmo erro de configuracao em vez
    # do mapeamento de status.
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-proj")
    monkeypatch.setenv("FIREBASE_APP_ID", "test-app")

    class _Resp:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    def aplicar(status_code, text="", erro=None):
        monkeypatch.setattr(ac.AppCheckMiddleware, "_init_credentials", lambda self: None)
        monkeypatch.setattr(
            ac.AppCheckMiddleware, "_refresh_token", lambda self: "fake-access-token"
        )

        def _post(url, headers=None, json=None, timeout=None):
            if erro is not None:
                raise erro
            return _Resp(status_code, text)

        monkeypatch.setattr(ac.httpx, "post", _post)

        mw = ac.AppCheckMiddleware(FastAPI())
        return mw._verify_appcheck_token("token-qualquer")

    return aplicar


# ──────────────────────────────────────────────────────────────────────────
# Camada 1 — o mapeamento bruto de status
# ──────────────────────────────────────────────────────────────────────────


def test_429_retorna_none_e_nao_false(verify_real):
    """429 = limite de taxa. `None` (indisponível), nunca `False` (token ruim)."""
    resultado = verify_real(429, text="quota exceeded")
    assert resultado is None, (
        f"429 devolviu {resultado!r}. Se False, o dispatch responde 401 e o "
        f"frontend pede token novo -> ciclo de throttling."
    )


@pytest.mark.parametrize("status", [400, 401, 403])
def test_status_de_token_invalido_continua_false(verify_real, status):
    """400/401/403 realmente são token ruim -> False. Não mudou."""
    resultado = verify_real(status, text="invalid token")
    assert resultado is False, f"{status} devolviu {resultado!r}, esperado False"


def test_200_continua_true(verify_real):
    assert verify_real(200) is True


def test_erro_de_rede_continua_none(verify_real):
    import httpx

    resultado = verify_real(0, erro=httpx.HTTPError("timeout"))
    assert resultado is None


def test_500_continua_false_comportamento_nao_mudado(verify_real):
    """500 cai no `return False` final. NÃO foi alterado — só 429 foi.

    Documentado aqui de propósito: é comportamento herdado e discutível, mas
    mexer nele não estava autorizado.
    """
    assert verify_real(500, text="internal error") is False


def test_config_ausente_continua_false(verify_real, monkeypatch):
    """Sem FIREBASE_APP_ID, o comportamento herdado é False (fail-closed)."""
    from app.middleware.appcheck import AppCheckMiddleware

    monkeypatch.setattr(AppCheckMiddleware, "_init_credentials", lambda self: None)
    mw = AppCheckMiddleware(FastAPI())
    mw.app_id = None
    assert mw._verify_appcheck_token("t") is False


# ──────────────────────────────────────────────────────────────────────────
# Camada 2 — o que o cliente HTTP recebe
# ──────────────────────────────────────────────────────────────────────────


def test_http_429_vira_503_com_retry_after(appcheck_app, verify_real):
    """O ponto central: o cliente recebe 503, não 401."""
    verify_real(429, text="quota exceeded")
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "t"})

    assert r.status_code == 503, f"recebeu {r.status_code} (401 seria a regressão)"
    assert r.json()["detail"] == "Serviço de validação indisponível"


def test_503_carrega_retry_after(appcheck_app, verify_real):
    """Sem Retry-After o cliente repete na hora e o limite estoura de novo."""
    verify_real(429, text="quota exceeded")
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "t"})

    retry = r.headers.get("Retry-After")
    assert retry is not None, "503 sem Retry-After"
    assert int(retry) >= 1, f"Retry-After invalido: {retry!r}"


def test_503_de_erro_de_rede_tambem_tem_retry_after(appcheck_app, verify_real):
    """O 503 de erro de rede passou a ter o mesmo cabecalho — coerencia."""
    import httpx

    verify_real(0, erro=httpx.HTTPError("timeout"))
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "t"})

    assert r.status_code == 503
    assert r.headers.get("Retry-After") is not None


@pytest.mark.parametrize("status", [400, 401, 403])
def test_http_token_invalido_continua_401(appcheck_app, verify_real, status):
    """401 de token inválido NÃO pode virar 503 — seria mascarar erro do cliente."""
    verify_real(status, text="invalid token")
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "t"})

    assert r.status_code == 401, f"{status} virou {r.status_code}"
    assert r.json()["detail"] == "App Check token invalid"
    assert r.headers.get("Retry-After") is None, "401 nao deve mandar esperar"


def test_http_200_passa(appcheck_app, verify_real):
    verify_real(200)
    c = TestClient(appcheck_app)
    r = c.get("/api/probe", headers={"X-Firebase-AppCheck": "t"})
    assert r.status_code == 200


def test_header_ausistente_continua_401_sem_chamar_google(appcheck_app):
    """Sem header, o middleware nem chega ao verifyToken."""
    c = TestClient(appcheck_app)
    r = c.get("/api/probe")
    assert r.status_code == 401
    assert r.json()["detail"] == "X-Firebase-AppCheck header required"


# ──────────────────────────────────────────────────────────────────────────
# Camada 3 — controle negativo: o teste tem dentes?
# ──────────────────────────────────────────────────────────────────────────


def test_comportamento_antigo_seria_401_e_nao_503(verify_real):
    """Controle: reproduz o mapeamento ANTIGO e mostra que é diferente.

    Sem este teste, os de cima passariam mesmo com a correção revertida,
    porque o stub de `httpx.post` é meu — não é o Google respondendo.
    """

    def mapeamento_antigo(status_code):
        if status_code == 200:
            return True
        if status_code in (400, 401, 403):
            return False
        return False  # <- 429 caia AQUI

    antigo_429 = mapeamento_antigo(429)
    assert antigo_429 is False, "o mapeamento antigo nao daria 401 para 429?"
    assert verify_real(429) is not antigo_429, (
        "429 agora devolve o mesmo que o mapeamento antigo devolvia — "
        "a correcao de fato mudou alguma coisa?"
    )


def test_429_e_400_pertencem_a_familias_diferentes(verify_real):
    """A distincao que importa: mesmo servico, respostas de familias distintas."""
    throttled = verify_real(429, text="quota")
    invalid = verify_real(400, text="bad token")

    assert throttled is None, "429 deve ser 'nao deu para saber'"
    assert invalid is False, "400 deve ser 'o token e ruim mesmo'"
    assert throttled is not invalid