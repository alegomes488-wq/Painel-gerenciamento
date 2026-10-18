import os, json
print("="*60)
print("DIAGNOSTICO DO PAINEL")
print("="*60)
backend = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(backend, ".env")
print(f"\nPasta: {backend}")
print(f".env: {env_path}")
env_vars = {}
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, _, v = s.partition("=")
                env_vars[k.strip()] = v.strip()
                if k.strip() == "GOOGLE_APPLICATION_CREDENTIALS" and v.strip():
                    print(f"\nLinha {i}: GOOGLE_APPLICATION_CREDENTIALS={v.strip()}")
                    exists = os.path.exists(v.strip())
                    print(f"  Arquivo existe? {exists}")
                    if not exists:
                        alt = os.path.join(backend, "firebase-adminsdk.json")
                        print(f"  Tentando fallback: {alt}")
                        print(f"  Existe? {os.path.exists(alt)}")
                elif k.strip() == "APP_CHECK_REQUIRED":
                    print(f"\nLinha {i}: APP_CHECK_REQUIRED={v.strip()}")
else:
    print("ERRO: .env NAO ENCONTRADO!")
print("\n" + "="*60)
print("Verificando firebase-adminsdk.json...")
sdk = os.path.join(backend, "firebase-adminsdk.json")
print(f"Path: {sdk}")
print(f"Existe? {os.path.exists(sdk)}")
if os.path.exists(sdk):
    try:
        with open(sdk, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"JSON valido? SIM")
        print(f"project_id: {data.get('project_id')}")
    except Exception as e:
        print(f"JSON invalido: {e}")
print("\n" + "="*60)
print("Verificando main.py (CSP)...")
main = os.path.join(backend, "app", "main.py")
if os.path.exists(main):
    with open(main, "r", encoding="utf-8") as f:
        content = f.read()
    if "connect-src" in content:
        import re
        m = re.search(r'connect-src[^;]+', content)
        if m:
            print(f"connect-src: {m.group(0)[:100]}...")
            print(f"Tem gstatic.com? {'gstatic.com' in m.group(0)}")
            print(f"Tem cdn.jsdelivr.net? {'cdn.jsdelivr.net' in m.group(0)}")
        else:
            print("Nao achou connect-src")
    else:
        print("Sem CSP no main.py")
else:
    print("main.py nao encontrado")
print("\n" + "="*60)
print("Diagnostico concluido!")
print("="*60)
