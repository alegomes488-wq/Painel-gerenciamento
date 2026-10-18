#!/usr/bin/env python3
"""Troca a senha do acesso Admin (Firebase Auth) via Admin SDK.

Como usar:
  python trocar_senha_admin.py --check          # apenas consulta, nao altera nada
  python trocar_senha_admin.py                  # muda a senha (pergunta digitando, oculta)
  python trocar_senha_admin.py --set            # muda a senha via env NOVA_SENHA (automacao)
  python trocar_senha_admin.py --set --email x  # alvo por e-mail em vez do UID padrao

A senha NUNCA e impressa em tela nem gravada em arquivo.
"""
import sys, os, json, getpass, argparse
from pathlib import Path

# ── Carrega .env (backend/.env e .env raiz) ──────────────────────────────
def _load_dotenv(path):
    if not path.exists():
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_dotenv(Path(__file__).parent / ".env")
_load_dotenv(Path(__file__).parent.parent / ".env")

# ── Firebase Admin SDK ───────────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, auth

if not firebase_admin._apps:
    cred = None
    # 1) Prefere o arquivo local: versao do .env pode estar desatualizada (key rotacionada).
    for p in [
        Path(__file__).parent / "firebase-adminsdk.json",
        Path(__file__).parent / "serviceAccountKey.json",
    ]:
        if p.exists():
            try:
                cred = credentials.Certificate(str(p))
                break
            except Exception:
                cred = None
    # 2) Fallback: env var FIREBASE_SERVICE_ACCOUNT
    if cred is None:
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
        if raw:
            try:
                info = json.loads(raw)
                if info.get("private_key"):
                    cred = credentials.Certificate(info)
            except ValueError:
                pass
    if cred is None:
        sys.exit("Credencial nao encontrada. Verifique backend/.env, .env ou firebase-adminsdk.json")
    firebase_admin.initialize_app(cred)

DEFAULT_UID = "yVjmEMnlHcPgEb5kozRnJNLmHY63"
DEFAULT_EMAIL = os.environ.get("ADMIN_EMAIL", "alegomes488@gmail.com")


def describe(user):
    return {
        "uid": user.uid,
        "email": user.email,
        "emailVerified": user.email_verified,
        "disabled": user.disabled,
        "claims": (user.custom_claims or {}),
    }


def main():
    ap = argparse.ArgumentParser(description="Troca a senha do acesso Admin.")
    ap.add_argument("--check", action="store_true", help="Somente consulta (nao altera nada).")
    ap.add_argument("--set", action="store_true", help="Usa a env NOVA_SENHA em vez de digitar.")
    ap.add_argument("--uid", default=DEFAULT_UID, help="UID do Firebase Auth (padrao: admin).")
    ap.add_argument("--email", default="", help="Alternativamente, localizar por e-mail.")
    args = ap.parse_args()

    target_uid = None
    try:
        if args.email:
            target_uid = auth.get_user_by_email(args.email).uid
        else:
            target_uid = auth.get_user(args.uid).uid
    except Exception as e:
        sys.exit(f"Usuario nao encontrado: {e}")

    user = auth.get_user(target_uid)
    info = describe(user)
    print("Conta encontrada:")
    print(f"  UID        : {info['uid']}")
    print(f"  E-mail     : {info['email']}")
    print(f"  Verificado : {info['emailVerified']}")
    print(f"  Desativada : {info['disabled']}")
    print(f"  Claims     : {info['claims']}")

    if args.check:
        print("\nModo --check: nenhuma alteracao feita.")
        return

    # Coleta a nova senha (minimo 6 caracteres, exigencia do Firebase)
    if args.set:
        nova = os.environ.get("NOVA_SENHA", "").strip()
        if len(nova) < 6:
            sys.exit("NOVA_SENHA deve ter pelo menos 6 caracteres.")
    else:
        nova = getpass.getpass("Nova senha (min 6 caracteres): ")
        if len(nova) < 6:
            sys.exit("Senha muito curta (minimo 6 caracteres).")
        conf = getpass.getpass("Confirme a nova senha: ")
        if nova != conf:
            sys.exit("As senhas nao conferem. Nada foi alterado.")

    auth.update_user(target_uid, password=nova)
    print(f"\nSUCESSO! Senha do admin ({info['email']}) alterada.")
    print("Sessoes antigas serao invalidadas — faca login novamente com a nova senha.")


if __name__ == "__main__":
    main()