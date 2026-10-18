"""
TAREFA 6.1 — Guarda de arquivos estáticos do painel admin.

PROBLEMA COMPROVADO (ver `_verify_static_exposure.py`):

    backend/app/main.py:27   ADMIN_DIR = PROJECT_ROOT/"www"/"admin"
    backend/app/main.py:157  app.mount("/", StaticFiles(directory=ADMIN_DIR, html=True))

`www/admin/` é a RAIZ estática do painel e, ao mesmo tempo, o diretório onde
acabaram cópias do backend (`www/admin/backend/`, com `.env` e
`firebase-adminsdk.json`). O `StaticFiles` do Starlette serve qualquer arquivo
que consiga abrir — `html=True` só muda o índice de DIRETÓRIO, não restringe
extensão nem tipo. Resultado medido:

    GET /backend/.env                    -> 200   (720 bytes, contem GROQ_API_KEY=)
    GET /backend/firebase-adminsdk.json  -> 200   (contem "BEGIN PRIVATE KEY")

Uma chave Admin SDK publicada dá leitura/escrita total no Realtime Database.

POR QUE ISTO EXISTE E NÃO É APAGAR ARQUIVO

Apagar `www/admin/backend/` resolveria o sintoma, mas sem provar que nada
depende daquele caminho (deploy legado, manual, referência em script) seria
remover às cegas. A guarda é o contrário: mantém os arquivos onde estão e faz o
servidor recusar a entrega. Reversível e sem efeito colateral no painel.

O QUE A GUARDA BLOQUEIA

1. Qualquer segmento de caminho que comece com "." — `.env`, `.git`,
   `.pytest_cache`. Nenhum arquivo legítimo do painel começa com ponto
   (verificado: o painel precisa de index.html, styles.css, sw.js,
   firebase-messaging-sw.js, favicon.svg, icons.svg, js/**, lib/**).
2. Subárvores no nível raiz que são código de servidor, não assets:
   `backend`. A lista é explícita e fácil de auditar — não é um "denylist"
   aberto que alguém possa contornar por engano.

O QUE A GUARDA NÃO MUDA

Não altera regras de negócio, Firebase, autenticação, pagamentos, PIX,
recompensas ou saldo. Não toca em rotas de API. Só a entrega de arquivo
estático fora de `www/admin/` — que nunca deveria ter sido servida.

NOTA OPERACIONAL (não resolvido aqui)

Mesmo com a guarda, a chave continua no disco e a chave deve ser considerada
exposta se o host já publicou esses caminhos. Rotacionar a chave do service
account é operação de segurança, não de código.
"""

from __future__ import annotations

import os

from starlette.staticfiles import StaticFiles

# Subárvores da raiz estática que são BACKEND, nunca assets do painel.
# Nome explícito: a lista é revisável, e o caminho precisa casar exatamente.
BLOCKED_ROOTS: frozenset[str] = frozenset({"backend"})

# Extensões que nunca deveriam sair de um servidor de painel.
# Defence in depth: se amanhã alguém mover um .env para fora de `backend/`,
# a guarda ainda recusa.
BLOCKED_SUFFIXES: frozenset[str] = frozenset({".env", ".pem", ".key", ".p12"})

# Marcadores que, aparecendo em QUALQUER ponto do nome do arquivo, indicam
# cópia de trabalho — código removido que não deve ser servido.
#
# Aqui é SUBSTRING, não sufixo, e isso é deliberado. Os backups deste projeto
# carregam data no fim do nome:
#     styles.css.bak-audit-20261005     -> termina em "-20261005"
#     styles.css.truncado-20261005      -> idem
# Um `endswith(".bak-audit-")` NÃO casaria com nenhum dos dois. Medido, não
# suposto.
#
# Nenhum asset legítimo do painel contém estes marcadores: index.html,
# styles.css, sw.js, firebase-messaging-sw.js, favicon.svg, icons.svg,
# LEIA-ME.txt, js/**, lib/**. Verificado.
BLOCKED_MARKERS: frozenset[str] = frozenset({".bak", ".truncado"})


def is_blocked_static_path(path: str) -> bool:
    """Diz se `path` (relativo à raiz estática) deve ser recusado.

    Função pura e testável — sem I/O, sem estado. Separada da classe para
    poder ser verificada diretamente nos testes.
    """
    if not path:
        return False

    # Normaliza para "/" e remove "./" inicial.
    norm = path.replace("\\", "/").lstrip("/")
    while norm.startswith("./"):
        norm = norm[2:]

    segments = [s for s in norm.split("/") if s not in ("", ".")]
    if not segments:
        return False

    # 1. dotfile em qualquer nivel (bloqueia .env, .git/..., .pytest_cache/...)
    if any(seg.startswith(".") for seg in segments):
        return True

    # 2. subarvore de backend no nivel raiz
    if segments[0].lower() in BLOCKED_ROOTS:
        return True

    # 3. extensao sensivel (defence in depth)
    last = segments[-1].lower()
    if any(last == suf or last.endswith(suf) for suf in BLOCKED_SUFFIXES):
        return True

    # 4. extensao ".env" com prefixo: pega "config.env"/"prod.env" dentro de
    #    js/ ou lib/. O arquivo ".env" puro ja cai no ponto 1 (dotfile).
    if last.endswith(".env"):
        return True

    # 5. copia de trabalho (.bak / .bak-audit-AAAAmmdd / .truncado-AAAAmmdd).
    #    Substring, porque a data fica no FIM do nome.
    return any(marker in last for marker in BLOCKED_MARKERS)


class GuardedStaticFiles(StaticFiles):
    """`StaticFiles` que se recusa a entregar dotfiles e código de backend.

    Não sobrescreve `file_response`: em Starlette 1.0 o filtro natural é
    `lookup_path`, que é chamada tanto por `get_response` (GET) quanto por
    `get_route_path`/checagem de rota. Devolver `(path, None)` faz o StaticFiles
    cair no 404 normal dele — nada de exceção, nada de resposta diferente da de
    um arquivo inexistente.
    """

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        # 404 idêntico ao de um arquivo inexistente: não revela que a pasta
        # existe, então não serve de oráculo para quem sondar o host.
        bloqueado = is_blocked_static_path(path)
        return ("", None) if bloqueado else super().lookup_path(path)