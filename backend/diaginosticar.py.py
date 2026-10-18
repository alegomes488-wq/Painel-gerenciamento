#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DIAGNOSTICO PAINEL - Verifica erros de App Check, CSP e Firebase
Coloque este arquivo na pasta backend/ e execute: python diagnosticar.py
"""

import os
import sys
import json

print("=" * 70)
print("DIAGNOSTICO DO PAINEL - App Check, CSP e Firebase")
print("=" * 70)

# 1. CAMINHOS
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BACKEND_DIR, ".env")
MAIN_PY = os.path.join(BACKEND_DIR, "app", "main.py")
APPCHECK_PY = os.path.join(BACKEND_DIR, "app", "middleware", "appcheck.py")
FIREBASE_SERVICE_PY = os.path.join(BACKEND_DIR, "app", "services", "firebase_service.py")

print(f"\nPasta backend: {BACKEND_DIR}")
print(f".env: {ENV_PATH}")
print(f"main.py: {MAIN_PY}")
print(f"appcheck.py: {APPCHECK_PY}")

# 2. VERIFICAR .env
print("\n" + "-" * 70)
print("VERIFICANDO .env")
print("-" * 70)

env_vars = {}
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    print(f".env encontrado ({len(lines)} linhas)")
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip()
            env_vars[key] = value
            
            if key == "FIREBASE_SERVICE_ACCOUNT" and value:
                print(f"   ATENCAO Linha {i}: {key}=... (JSON inline - pode estar corrompido)")
            elif key == "GOOGLE_APPLICATION_CREDENTIALS":
                if value:
                    print(f"   OK Linha {i}: {key}={value}")
                    if os.path.exists(value):
                        print(f"      OK Arquivo existe!")
                    else:
                        print(f"      ERRO: ARQUIVO NAO ENCONTRADO!")
                        alt_path = os.path.join(BACKEND_DIR, os.path.basename(value))
                        if os.path.exists(alt_path):
                            print(f"      DICA: Mas existe em: {alt_path}")
                else:
                    print(f"   ERRO Linha {i}: {key}= (VAZIO)")
            elif key == "APP_CHECK_REQUIRED":
                print(f"   INFO Linha {i}: {key}={value}")
            elif key in ["FIREBASE_PROJECT_ID", "FIREBASE_APP_ID"]:
                print(f"   INFO Linha {i}: {key}={value}")
else:
    print(f"   ERRO: .env NAO ENCONTRADO em {ENV_PATH}")

# 3. VERIFICAR firebase-adminsdk.json
print("\n" + "-" * 70)
print("VERIFICANDO firebase-adminsdk.json")
print("-" * 70)

sdk_paths = [
    os.path.join(BACKEND_DIR, "firebase-adminsdk.json"),
    os.path.join(BACKEND_DIR, "service-account.json"),
]

if env_vars.get("GOOGLE_APPLICATION_CREDENTIALS"):
    sdk_paths.insert(0, env_vars["GOOGLE_APPLICATION_CREDENTIALS"])

found = False
for path in sdk_paths:
    if os.path.exists(path):
        print(f"OK Encontrado: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"   OK JSON valido")
            print(f"   project_id: {data.get('project_id', 'N/A')}")
            print(f"   client_email: {data.get('client_email', 'N/A')}")
            print(f"   private_key_id: {data.get('private_key_id', 'N/A')[:20]}...")
            found = True
        except json.JSONDecodeError as e:
            print(f"   ERRO JSON INVALIDO: {e}")
        break

if not found:
    print("ERRO: Nenhum firebase-adminsdk.json encontrado!")
    print("   Arquivos procurados:")
    for p in sdk_paths:
        print(f"      - {p}")

# 4. VERIFICAR main.py (CSP)
print("\n" + "-" * 70)
print("VERIFICANDO CSP em main.py")
print("-" * 70)

if os.path.exists(MAIN_PY):
    with open(MAIN_PY, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "Content-Security-Policy" in content:
        print("OK CSP encontrado em main.py")
        
        import re
        csp_match = re.search(r'connect-src[^;]+', content)
        if csp_match:
            csp = csp_match.group(0)
            print(f"\n   connect-src atual:")
            print(f"   {csp.strip()}")
            
            required = [
                "https://www.gstatic.com",
                "https://cdn.jsdelivr.net",
                "wss://*.firebaseio.com",
                "https://identitytoolkit.googleapis.com",
            ]
            print(f"\n   Verificando dominios essenciais:")
            for domain in required:
                if domain in csp:
                    print(f"      OK {domain}")
                else:
                    print(f"      FALTANDO: {domain}")
        else:
            print("   ATENCAO: Nao consegui extrair connect-src")
    else:
        print("ERRO: CSP NAO ENCONTRADO em main.py")
else:
    print(f"ERRO: main.py nao encontrado em {MAIN_PY}")

# 5. VERIFICAR appcheck.py
print("\n" + "-" * 70)
print("VERIFICANDO AppCheck Middleware")
print("-" * 70)

if os.path.exists(APPCHECK_PY):
    with open(APPCHECK_PY, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "_sa_dict" in content:
        print("OK Funcao _sa_dict encontrada")
        
        if "firebase-adminsdk.json" in content:
            print("OK Fallback para firebase-adminsdk.json presente")
        else:
            print("ATENCAO: Nao encontrou fallback para arquivo local")
        
        if "GOOGLE_APPLICATION_CREDENTIALS" in content:
            print("OK Le GOOGLE_APPLICATION_CREDENTIALS")
        else:
            print("ERRO: Nao le GOOGLE_APPLICATION_CREDENTIALS")
    else:
        print("ATENCAO: Funcao _sa_dict nao encontrada")
else:
    print(f"ERRO: appcheck.py nao encontrado em {APPCHECK_PY}")

# 6. VERIFICAR firebase_service.py
print("\n" + "-" * 70)
print("VERIFICANDO firebase_service.py")
print("-" * 70)

if os.path.exists(FIREBASE_SERVICE_PY):
    with open(FIREBASE_SERVICE_PY, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "firebase-adminsdk.json" in content:
        print("OK Fallback firebase-adminsdk.json presente")
    else:
        print("ATENCAO: Sem fallback para arquivo local")
    
    if "FIREBASE_SERVICE_ACCOUNT" in content:
        print("OK Le FIREBASE_SERVICE_ACCOUNT do .env")
    else:
        print("ATENCAO: Nao le FIREBASE_SERVICE_ACCOUNT")
else:
    print(f"ERRO: firebase_service.py nao encontrado")

# 7. RECOMENDACOES
print("\n" + "=" * 70)
print("RECOMENDACOES")
print("=" * 70)

recomendacoes = []

if not env_vars.get("GOOGLE_APPLICATION_CREDENTIALS"):
    recomendacoes.append("Adicione GOOGLE_APPLICATION_CREDENTIALS=\"C:\\\\Users\\\\...\\\\firebase-adminsdk.json\" no .env")

if env_vars.get("FIREBASE_SERVICE_ACCOUNT"):
    recomendacoes.append("Remova FIREBASE_SERVICE_ACCOUNT do .env (deixe apenas GOOGLE_APPLICATION_CREDENTIALS)")

if not found:
    recomendacoes.append("Baixe uma nova chave privada do Firebase Console e salve como firebase-adminsdk.json")

if env_vars.get("APP_CHECK_REQUIRED", "").lower() == "true":
    recomendacoes.append("APP_CHECK_REQUIRED=true - O frontend precisa enviar X-Firebase-AppCheck")

if not recomendacoes:
    print("OK Tudo parece configurado. Se o erro persistir, pode ser:")
    print("   1. O python-dotenv nao esta carregando o .env corretamente")
    print("   2. O arquivo JSON esta corrompido (baixe uma nova chave)")
    print("   3. O path no .env tem caracteres especiais ou encoding errado")
else:
    for i, rec in enumerate(recomendacoes, 1):
        print(f"{i}. {rec}")

print("\n" + "=" * 70)
print("Diagnostico concluido!")
print("=" * 70)
