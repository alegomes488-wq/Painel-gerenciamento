import os
import sys
import json
import asyncio
import requests
from datetime import datetime
from contextlib import asynccontextmanager
import time

import firebase_admin
from firebase_admin import credentials, db, messaging
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from collections import deque

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# Adiciona a raiz do projeto ao sys.path para permitir imports relativos e pacotes
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

WWW_DIR = os.path.join(PROJECT_ROOT, "www")
ADMIN_DIR = os.path.join(WWW_DIR, "admin")

# --- CONFIGURAÇÃO DE AMBIENTE ---
os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8')

# --- CONFIGURA O FIREBASE ---
backend_dir = os.path.dirname(__file__)
cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

if cred_json:
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
    print("Firebase iniciado via Variável de Ambiente")
else:
    cred_filename = "serviceAccountKey.json"
    cred_path = os.path.join(backend_dir, cred_filename)
    if not os.path.exists(cred_path):
        cred_filename = "firebase-adminsdk.json"
        cred_path = os.path.join(backend_dir, cred_filename)

    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
        print(f"Firebase iniciado com {cred_filename}")
    else:
        print("ERRO: Credenciais Firebase não encontradas!")

# --- CONSTANTES CYBERCORE ---
HUB_MODE = os.environ.get("HUB_MODE", "USER")
MEMORY_BASE = "cybercore/memory"
COMMAND_BUS = "cybercore/commands"
AGENT_STATUS = "cybercore/agents"
ALERT_LEVEL = "cybercore/alert_level"

# --- MEMÓRIA INTELIGENTE (FIREBASE) ---
MEMORY_CONTEXT = "cybercore_memory"
CONTEXT_MAX = 50

def memory_load(uid: str):
    try:
        data = db.reference(f'{MEMORY_CONTEXT}/{uid}/context').get() or []
        return deque(data, maxlen=CONTEXT_MAX)
    except:
        return deque(maxlen=CONTEXT_MAX)

def memory_save(uid: str, context: deque):
    try:
        db.reference(f'{MEMORY_CONTEXT}/{uid}/context').set(list(context))
        db.reference(f'{MEMORY_CONTEXT}/{uid}/last_updated').set(datetime.now().isoformat())
    except Exception as e:
        print(f"[MEMORIA] Erro ao salvar: {e}")

def memory_summarize(uid: str, full_context: deque):
    try:
        texto = "\n".join([f"{m['role']}: {m['content']}" for m in full_context])
        summary_ref = db.reference(f'{MEMORY_CONTEXT}/{uid}/summary')
        existing = summary_ref.get() or []
        session = {"timestamp": datetime.now().isoformat(), "messages": len(full_context), "preview": texto[:200]}
        existing.append(session)
        if len(existing) > 20: existing = existing[-20:]
        summary_ref.set(existing)
    except Exception as e:
        print(f"[MEMORIA] Erro ao sumarizar: {e}")

def memory_recall(uid: str, query: str = ""):
    try:
        summaries = db.reference(f'{MEMORY_CONTEXT}/{uid}/summary').get() or []
        if not query: return summaries[-5:] if summaries else []
        return [s for s in summaries if query.lower() in s.get("preview", "").lower()][-5:]
    except:
        return []

# --- UTILITÁRIOS ---

def get_dollar_rate():
    try:
        resp = requests.get("https://economia.awesomeapi.com.br/last/USD-BRL", timeout=5)
        return float(resp.json()['USDBRL']['bid'])
    except: return 5.25

def tool_analyze_health():
    try:
        users = db.reference('users').get() or {}
        config = db.reference('config').get() or {}
        total_debt = sum([float(u.get('balance', 0)) for u in users.values() if isinstance(u, dict)])
        hits = config.get('stats', {}).get('hits', 0)
        cpm = config.get('cpm', 0.18)
        dollar = get_dollar_rate()
        revenue_brl = (hits / 1000) * cpm * dollar
        status = "SAUDÁVEL" if revenue_brl > (total_debt * 1.5) else "CRÍTICO"
        return {
            "revenue_brl": round(revenue_brl, 2),
            "total_debt": round(total_debt, 2),
            "net_profit_brl": round(revenue_brl - total_debt, 2),
            "roi_status": status,
            "health_status": status,
            "dollar_rate": dollar
        }
    except: return {"revenue_brl": 0, "total_debt": 0, "health_status": "ERRO"}

def tool_sync_monetag():
    health = tool_analyze_health()
    data = {
        "usd": health['revenue_brl'] / (health.get('dollar_rate') or 5.25),
        "brl": health['revenue_brl'],
        "rate": health.get('dollar_rate') or 5.25,
        "last_update": datetime.now().strftime('%H:%M:%S')
    }
    db.reference('stats/financial_realtime').set(data)
    return f"Sincronizado: R$ {health['revenue_brl']}"

def tool_send_push(target, message):
    try:
        if target == 'global':
            msg = messaging.Message(notification=messaging.Notification(title='CyberCore IA', body=message), topic='all_users')
        else:
            user = db.reference(f'users/{target}').get()
            if not user or 'fcmToken' not in user: return "Sem token"
            msg = messaging.Message(notification=messaging.Notification(title='CyberCore IA', body=message), token=user['fcmToken'])
        messaging.send(msg)
        return "Push enviado"
    except Exception as e: return str(e)

def tool_execute_ban(uid, reason):
    db.reference(f'users/{uid}').update({"status": "banido", "risk_score": 100, "ban_reason": reason})
    tool_send_push(uid, "Sua conta foi suspensa por violação de segurança.")
    return f"Usuário {uid} banido."

def tool_execute_unban(uid, reason):
    db.reference(f'users/{uid}').update({"status": "ativo", "risk_score": 0, "unban_reason": reason})
    tool_send_push(uid, "Sua conta foi reabilitada após análise.")
    return f"Usuário {uid} desbanido."

async def auto_approve_withdrawals(force=False):
    try:
        nodes = db.reference('neural/nodes').get() or {}
        global_config = db.reference('config').get() or {}
        global_asaas_key = global_config.get('asaasKey') or os.environ.get('ASAAS_API_KEY', '')

        users = db.reference('users').get() or {}
        total_debt = sum([float(u.get('balance', 0)) for u in users.values() if isinstance(u, dict)])
        hits = global_config.get('stats', {}).get('hits', 0)
        cpm = global_config.get('cpm', 0.18)
        dollar = get_dollar_rate()
        revenue = (hits / 1000) * cpm * dollar
        roi = ((revenue - total_debt) / revenue * 100) if revenue > 0 else 0

        # No modo force (via terminal), ignoramos o ROI mínimo
        if not force and roi < 30: return f"ROI {roi:.1f}% baixo do limiar (30%)"

        approved = 0
        all_withdrawals = db.reference('withdrawals').get() or {}

        for uid, ws in all_withdrawals.items():
            for wid, w in ws.items():
                if w.get('status') == 'pending':
                    # Determina qual chave usar (Projeto ou Global)
                    pid = w.get('projectId')
                    node = nodes.get(pid) if pid else None
                    api_key = (node.get('asaas_key') if node else None) or global_asaas_key

                    if not api_key:
                        print(f"Pulo saque {wid}: Nenhuma chave Asaas configurada.")
                        continue

                    amount = float(w.get('amount', 0))
                    # Limite de segurança para auto-payout
                    if not force and amount > 5.0: continue

                    pix_key = w.get('pixKey', '')

                    def detect_pix(t):
                        t = str(t).strip()
                        clean = "".join(filter(str.isdigit, t))
                        if '@' in t: return 'EMAIL'
                        if t.startswith('+') or (len(clean) >= 10 and len(clean) <= 11 and (t.startswith('(') or t.startswith('0'))): return 'PHONE'
                        if len(clean) == 11: return 'CPF'
                        if len(clean) == 14: return 'CNPJ'
                        return 'EVP'

                    # Prioriza o tipo salvo no banco, se não existir, tenta detectar
                    type_detected = w.get('pixType')
                    if not type_detected:
                        def detect_pix(t):
                            t = str(t).strip()
                            clean = "".join(filter(str.isdigit, t))
                            if '@' in t: return 'EMAIL'
                            if len(clean) == 11 and (t.startswith('85') or t.startswith('085') or not t.startswith('0')): return 'PHONE'
                            if len(clean) == 11: return 'CPF'
                            if len(clean) == 14: return 'CNPJ'
                            return 'EVP'
                        type_detected = detect_pix(pix_key)

                    final_pix_key = pix_key
                    if type_detected in ['CPF', 'CNPJ', 'PHONE']:
                        final_pix_key = "".join(filter(str.isdigit, pix_key))
                        if type_detected == 'PHONE' and not final_pix_key.startswith('55'):
                            if len(final_pix_key) <= 11: final_pix_key = "55" + final_pix_key

                    # Determina URL baseada na chave
                    is_sandbox = '_prod_' not in api_key.lower()
                    asaas_url = "https://www.asaas.com/api/v3/transfers" if not is_sandbox else "https://www.asaas.com/api/v3/transfers"
                    # Força produção se a chave for prod
                    if '_prod_' in api_key.lower():
                        asaas_url = "https://www.asaas.com/api/v3/transfers"
                    else:
                        asaas_url = "https://sandbox.asaas.com/api/v3/transfers"

                    headers = {"access_token": api_key.strip(), "Content-Type": "application/json"}
                    payload = {
                        "value": amount,
                        "pixAddressKey": final_pix_key,
                        "pixAddressKeyType": type_detected,
                        "description": f"CineCash Resgate Auto #{wid}"
                    }

                    try:
                        print(f"Tentando pagar {wid} (R$ {amount}) via Asaas...")
                        resp = requests.post(asaas_url, json=payload, headers=headers, timeout=25)
                        res_json = resp.json()

                        if resp.status_code == 200:
                            db.reference(f'withdrawals/{uid}/{wid}').update({
                                "status": "paid", "auto_approved": True,
                                "asaas_id": res_json.get('id'), "paid_at": datetime.now().isoformat()
                            })
                            # Remove da fila de pendentes se existir
                            db.reference(f'admin/pending_withdrawals/{wid}').delete()
                            approved += 1
                            print(f"OK {wid} pago com sucesso!")
                        else:
                            err = res_json.get('errors', [{}])[0].get('description', 'Erro desconhecido')
                            print(f"Falha no saque {wid}: {err}")
                    except Exception as e:
                        print(f"Erro crítico na conexão Asaas para {wid}: {e}")
        return f"Processamento concluído. Aprovados: {approved} | ROI: {roi:.1f}%"
    except Exception as e: return f"Auto-approve error: {e}"

# --- NÚCLEO IA (GEMINI) ---

def tool_sentinel_enforcement():
    try:
        config = db.reference('config').get() or {}
        block_vpn = config.get('blockVPN', False)
        block_root = config.get('blockRoot', False)
        device_lock = config.get('deviceLock', False)
        auto_ban = config.get('autoBan', False)

        users = db.reference('users').get() or {}
        banned = 0

        # Mapeia fingerprint -> lista de uids para detectar múltiplas contas
        fingerprint_map = {}
        for uid, user in users.items():
            if not isinstance(user, dict): continue
            fp = user.get('security', {}).get('fingerprint', '')
            if fp and len(fp) > 10:
                if fp not in fingerprint_map: fingerprint_map[fp] = []
                fingerprint_map[fp].append(uid)

        for uid, user in users.items():
            if not isinstance(user, dict): continue
            status = user.get('status', 'ativo')
            if status == 'banido': continue

            sec = user.get('security', {})
            fp = sec.get('fingerprint', '')
            fp_detail = sec.get('fp_detail', {}) or {}
            vpn = fp_detail.get('vpn', False)
            root_hints = fp_detail.get('root_hints', [])
            risk = user.get('risk_score', 0)
            balance = float(user.get('balance', 0))
            reason = None

            # 1. Bloqueio de Proxy/VPN
            if block_vpn and vpn:
                reason = "VPN/Proxy detectado (Política de Blindagem)"

            # 2. Detecção de Root/Jailbreak
            if block_root and root_hints and len(root_hints) > 0:
                if any(h not in ('no_plugins',) for h in root_hints):
                    reason = f"Root/Jailbreak detectado: {', '.join(root_hints)}"

            # 3. Score de risco
            if not reason and risk >= 100:
                reason = "Score de risco crítico (100+)"

            # 4. Saldo suspeito
            if not reason and balance > 1000 and user.get('videosWatched', 0) < 5:
                reason = "Saldo suspeito com baixa atividade"

            # 5. Auto-Ban (múltiplas contas no mesmo dispositivo)
            if auto_ban and not reason and fp and len(fp) > 10:
                accounts_on_device = fingerprint_map.get(fp, [])
                if len(accounts_on_device) > 1:
                    reason = f"Múltiplas contas no mesmo dispositivo ({len(accounts_on_device)} contas)"

            if reason:
                tool_execute_ban(uid, reason)
                banned += 1
                db.reference('logs/sentinel_alerts').push({
                    "uid": uid, "reason": reason,
                    "timestamp": {".sv": "timestamp"},
                    "policies": {
                        "blockVPN": block_vpn, "blockRoot": block_root,
                        "deviceLock": device_lock, "autoBan": auto_ban
                    }
                })

            # 6. Device Lock: apenas marca como suspeito, não bane (bloqueia login)
            if device_lock and not reason and fp and len(fp) > 10:
                accounts_on_device = fingerprint_map.get(fp, [])
                if len(accounts_on_device) > 1:
                    # Marca o usuário para bloqueio de login (não banimento)
                    db.reference(f'users/{uid}/security/device_lock_alert').set(True)
                    db.reference('logs/device_lock_alerts').push({
                        "uid": uid, "fingerprint": fp,
                        "accounts": accounts_on_device,
                        "timestamp": {".sv": "timestamp"}
                    })

        return f"Sentinel: {banned} banidos | VPN:{block_vpn} Root:{block_root} DevLock:{device_lock} AutoBan:{auto_ban}"
    except Exception as e: return f"Erro Sentinel: {str(e)}"

WORKSPACE_DIR = os.path.join(PROJECT_ROOT, "cybercore_workspace")
if not os.path.exists(WORKSPACE_DIR):
    os.makedirs(WORKSPACE_DIR)

def tool_write_studio_file(filename, content):
    try:
        # Sanitização básica para evitar Path Traversal
        filename = os.path.basename(filename)
        path = os.path.join(WORKSPACE_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Arquivo {filename} gerado com sucesso no workspace."
    except Exception as e:
        return f"Erro ao escrever arquivo: {e}"

def tool_list_studio_files():
    try:
        files = os.listdir(WORKSPACE_DIR)
        return {"files": files}
    except Exception as e:
        return f"Erro ao listar arquivos: {e}"

AVAILABLE_TOOLS = {
    "toggle_maintenance": lambda state: db.reference('config/maintenance').set(state) or f"Manutenção: {state}",
    "update_cpm": lambda value: db.reference('config/cpm').set(value) or f"CPM: {value}",
    "analyze_system_health": tool_analyze_health,
    "sync_monetag": tool_sync_monetag,
    "execute_ban": tool_execute_ban,
    "execute_unban": tool_execute_unban,
    "send_push_notification": tool_send_push,
    "get_user_data": lambda uid: db.reference(f'users/{uid}').get(),
    "check_frauds": lambda: db.reference('logs/frauds').get(),
    "process_all_payments": auto_approve_withdrawals,
    "sentinel_enforcement": tool_sentinel_enforcement,
    "write_studio_file": tool_write_studio_file,
    "list_studio_files": tool_list_studio_files
}

TOOLS_DEFINITION = [
    {
        "functionDeclarations": [
            {"name": "toggle_maintenance", "description": "Ativa/desativa manutenção.", "parameters": {"type": "object", "properties": {"state": {"type": "boolean"}}, "required": ["state"]}},
            {"name": "update_cpm", "description": "Ajusta o valor do CPM.", "parameters": {"type": "object", "properties": {"value": {"type": "number"}}, "required": ["value"]}},
            {"name": "analyze_system_health", "description": "Analisa ganhos, dívidas e CTR.", "parameters": {"type": "object", "properties": {}}},
            {"name": "execute_ban", "description": "Bane um usuário.", "parameters": {"type": "object", "properties": {"uid": {"type": "string"}, "reason": {"type": "string"}}, "required": ["uid", "reason"]}},
            {"name": "execute_unban", "description": "Desbane um usuário.", "parameters": {"type": "object", "properties": {"uid": {"type": "string"}, "reason": {"type": "string"}}, "required": ["uid", "reason"]}},
            {"name": "send_push_notification", "description": "Envia push via FCM.", "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "message": {"type": "string"}}, "required": ["target", "message"]}},
            {"name": "sync_monetag", "description": "Sincroniza lucros Monetag.", "parameters": {"type": "object", "properties": {}}},
            {"name": "get_user_data", "description": "Dados do usuário.", "parameters": {"type": "object", "properties": {"uid": {"type": "string"}}, "required": ["uid"]}},
            {"name": "check_frauds", "description": "Verifica logs de fraude.", "parameters": {"type": "object", "properties": {}}},
            {"name": "process_all_payments", "description": "Processa todos os saques pendentes.", "parameters": {"type": "object", "properties": {}}},
            {"name": "sentinel_enforcement", "description": "Executa varredura e banimento automático de fraudes.", "parameters": {"type": "object", "properties": {}}},
            {"name": "write_studio_file", "description": "Salva um arquivo ou script gerado no workspace do Studio.", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}}, "required": ["filename", "content"]}},
            {"name": "list_studio_files", "description": "Lista os arquivos gerados no workspace do Studio.", "parameters": {"type": "object", "properties": {}}}
        ]
    }
]

# --- GROQ (Nuvem Gratuita, Prioridade 1) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    try:
        groq_config = db.reference('config/groqKey').get()
        if groq_config: GROQ_API_KEY = str(groq_config).strip()
    except: pass
if not GROQ_API_KEY:
    try:
        config_data = db.reference('config').get() or {}
        GROQ_API_KEY = str(config_data.get('groqKey', '')).strip()
    except: pass
GROQ_AVAILABLE = bool(GROQ_API_KEY)
GROQ_MODEL_MAP = {
    "llama3:latest": "llama-3.3-70b-versatile",
    "llama3:8b": "llama3-8b-8192",
    "mixtral": "mixtral-8x7b-32768",
    "gemma2": "gemma2-9b-it",
}

def groq_generate(prompt, model="llama3:latest"):
    if not GROQ_AVAILABLE:
        return None
    try:
        groq_model = GROQ_MODEL_MAP.get(model, "llama-3.3-70b-versatile")
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": groq_model,
            "messages": [
                {"role": "system", "content": "Você é o CyberCore IA Elite. Responda em PT-BR de forma técnica e autoritária."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        return None
    except:
        return None

async def ask_ai(prompt: str, uid="admin_master"):
    try:
        # Prioridade 1: Groq (mais rápido, gratuito, sempre disponível)
        groq_result = groq_generate(prompt)
        if groq_result:
            try:
                history_ref = db.reference(f'ai_memory/{uid}')
                history = history_ref.get() or []
                history.append({"role": "user", "text": prompt})
                history.append({"role": "model", "text": groq_result})
                history_ref.set(history[-20:])
            except:
                pass
            return groq_result

        # Prioridade 2: Gemini (fallback)
        config = db.reference('config').get() or {}
        api_key = os.environ.get("GEMINI_API_KEY") or str(config.get('geminiKey', '')).strip()

        if api_key:
            history_ref = db.reference(f'ai_memory/{uid}')
            history = history_ref.get() or []
            contents = [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in history[-10:]]
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            system_prompt = "Você é o CyberCore IA Elite. Use ferramentas para gerir o sistema CineCash. Responda em PT-BR de forma técnica e autoritária."

            for model in ("gemini-2.0-flash", "gemini-1.5-flash"):
                api_ver = "v1beta" if model == "gemini-2.0-flash" else "v1"
                url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={api_key}"
                payload = {"contents": contents, "tools": TOOLS_DEFINITION}
                if api_ver == "v1beta": payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

                resp = requests.post(url, json=payload, timeout=60)
                res_data = resp.json()
                if resp.status_code == 200 and "candidates" in res_data:
                    part = res_data['candidates'][0]['content']['parts'][0]
                    if "functionCall" in part:
                        call = part["functionCall"]
                        f_name = call["name"]
                        f_args = call.get("args", {})
                        func = AVAILABLE_TOOLS[f_name]
                        if asyncio.iscoroutinefunction(func):
                            result = await func(**f_args) if f_name != "process_all_payments" else await func(force=True)
                        else:
                            result = func(**f_args)
                        return await ask_ai(f"Resultado {f_name}: {result}. Finalize sua resposta.", uid)

                    answer = part.get("text", "Comando processado.")
                    history.append({"role": "user", "text": prompt})
                    history.append({"role": "model", "text": answer})
                    history_ref.set(history[-20:])
                    return answer

        return "Nenhum motor de IA disponível. Configure GROQ_API_KEY ou GEMINI_API_KEY."
    except Exception as e:
        return f"Erro Núcleo: {str(e)}"

# --- OADA CYCLE ---

def memory_save(category: str, key: str, data: dict):
    data["_ts"] = datetime.now().isoformat()
    db.reference(f"{MEMORY_BASE}/{category}/{key}").set(data)

def compute_alert_level():
    health = tool_analyze_health()
    frauds = db.reference('logs/sentinel_alerts').get() or {}
    fraud_rate = len(frauds) / 100
    if fraud_rate > 0.1 or health['revenue_brl'] < (health['total_debt'] * 1.1): return "critical"
    if fraud_rate > 0.05: return "alert"
    return "normal"

async def oada_cycle():
    health = tool_analyze_health()
    level = compute_alert_level()
    decisions = []

    if level == "critical":
        new_cpm = round((db.reference('config/cpm').get() or 0.18) + 0.02, 3)
        db.reference('config/cpm').set(new_cpm)
        decisions.append(f"Ajuste emergencial CPM -> {new_cpm}")

    if level != "emergency":
        auto_result = await auto_approve_withdrawals()
        decisions.append(f"Auto-approve: {auto_result}")

    memory_save('decisions', f"cycle_{datetime.now().strftime('%Y%m%d%H%M')}", {
        "level": level, "health": health, "decisions": decisions
    })
    return {"level": level, "decisions": decisions}

async def monitor_connected_projects():
    """Monitora projetos conectados (neural/nodes) em tempo real."""
    try:
        nodes = db.reference('neural/nodes').get() or {}
        for node_id, node in nodes.items():
            identifier = node.get('identifier', '')
            ptype = node.get('type', 'website')
            if not identifier:
                continue

            health = {"last_checked": datetime.now().isoformat()}
            try:
                if ptype == 'website':
                    url = identifier if identifier.startswith('http') else 'https://' + identifier
                    start = time.time()
                    resp = requests.head(url, timeout=8, allow_redirects=True)
                    latency_ms = int((time.time() - start) * 1000)
                    health['status'] = 'online' if resp.status_code < 500 else 'degraded'
                    health['http_status'] = resp.status_code
                    health['latency_ms'] = latency_ms
                elif ptype == 'api':
                    url = identifier if identifier.startswith('http') else 'https://' + identifier
                    start = time.time()
                    resp = requests.get(url, timeout=8)
                    latency_ms = int((time.time() - start) * 1000)
                    health['status'] = 'online' if resp.status_code < 500 else 'degraded'
                    health['http_status'] = resp.status_code
                    health['latency_ms'] = latency_ms
                elif ptype == 'local':
                    from urllib.parse import urlparse
                    if ':' in identifier:
                        parts = identifier.split(':')
                        host = parts[0].strip()
                        port = parts[1].strip()
                        import socket
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(3)
                        result = sock.connect_ex((host, int(port)))
                        sock.close()
                        health['status'] = 'online' if result == 0 else 'offline'
                        health['tcp_port'] = int(port)
                    else:
                        health['status'] = 'unknown'
                else:
                    health['status'] = 'unknown'
            except Exception:
                health['status'] = 'offline'
                health['error'] = 'timeout_or_unreachable'

            db.reference(f'neural/nodes/{node_id}/health').update(health)
    except Exception as e:
        print(f"[MONITOR] Erro ao monitorar projetos: {e}")


async def cybercore_audit_loop():
    while True:
        try:
            # Registra o pulso específico do modo (USER ou ADMIN)
            node_name = f"pulse_{HUB_MODE.lower()}"
            db.reference(f'status/{node_name}').set({".sv": "timestamp"})

            if HUB_MODE == "ADMIN":
                # Sincroniza o sinal que o site (WWW) espera para mostrar "ONLINE"
                db.reference('status/auditor_last_pulse').set({".sv": "timestamp"})

                # Executa tarefas de auditoria
                tool_sync_monetag()
                sentinel_report = tool_sentinel_enforcement()
                await oada_cycle()
                await monitor_connected_projects()

                print(f"[ADMIN] Ciclo de Auditoria Completo: {datetime.now().strftime('%H:%M:%S')}")
            else:
                print(f"[USER] CineCash IA Ativo e Pulsando...")

        except Exception as e:
            print(f"Erro Loop {HUB_MODE}: {e}")

        # Aumentamos um pouco o delay para evitar sobrecarga no reload
        await asyncio.sleep(45)

# --- INICIALIZAÇÃO DO APP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia o loop de auditoria em segundo plano
    task = asyncio.create_task(cybercore_audit_loop())
    print("🚀 CyberCore IA: Loop de Auditoria Iniciado")

    # Imprime rotas para diagnóstico
    print("📌 Rotas registradas:")
    for route in app.routes:
        print(f"   {route.path} [{getattr(route, 'methods', 'ANY')}]")

    yield
    task.cancel()

app = FastAPI(
    title="CyberCore IA Hub",
    description="Núcleo de Inteligência e Gestão CineCash",
    version="2.0.0",
    lifespan=lifespan
)

# Middleware para logar todas as requisições (ajuda a debugar 404)
@app.middleware("http")
async def log_requests(request, call_next):
    print(f"🔍 Requisição recebida: {request.method} {request.url.path}")
    response = await call_next(request)
    print(f"📤 Resposta: {response.status_code}")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ROTAS API (OBRIGATORIAMENTE ANTES DOS STATIC MOUNTS) ---

@app.get("/health")
@app.get("/health/")
async def health_check():
    return {
        "status": "CyberCore IA Elite Online",
        "mode": HUB_MODE,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/sentinel/scan")
@app.post("/api/sentinel/scan/")
async def manual_sentinel_scan():
    """Executa a varredura do Sentinel sob demanda via painel admin"""
    try:
        result = tool_sentinel_enforcement()
        return {"status": "success", "msg": result}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/api/test/push")
async def test_push(data: dict = Body(...)):
    """Dispara um push de teste (Individual ou Global)"""
    target = data.get("target") or data.get("uid")
    message = data.get("message") or "🔔 Teste de Notificação CyberCore IA: Sua conexão está ativa!"

    if not target:
        return {"status": "error", "msg": "Target (uid ou 'global') não fornecido"}

    res = tool_send_push(target, message)
    if "enviado" in res.lower():
        return {"status": "success", "msg": res}
    return {"status": "error", "msg": res}

@app.post("/api/nexus/report")
async def nexus_report(data: dict = Body(...)):
    """Recebe dados do Agente Nexus e encaminha ao Painel via Firebase."""
    try:
        uid = data.get("uid")
        if not uid: return {"status": "ignored"}

        # Escreve no mesmo path que o Painel Gerenciamento lê
        db.reference(f'logs/nexus/{uid}').push({"report": data, "received_at": datetime.now().isoformat()})

        # Também escreve em agent_data para o dashboard neural do Painel
        db.reference('agent_data/incoming').push({"agent_id": "nexus_cinecash", "type": "telemetry", "payload": data, "received_at": datetime.now().isoformat()})

        # Fraude (mesma lógica anterior, mas agora loga no path do Painel)
        user_ref = db.reference(f'users/{uid}')
        user_data = user_ref.get()
        if user_data:
            real_ads = int(data.get("ads_watched", 0))
            balance = float(user_data.get('balance', 0))
            if balance > 50 and real_ads < 2:
                risk = user_data.get('risk_score', 0) + 30
                user_ref.update({"risk_score": risk, "last_fraud_attempt": "Manipulação detectada pelo Nexus"})
                db.reference('logs/sentinel_alerts').push({
                    "uid": uid, "type": "NEXUS_FRAUD",
                    "msg": f"Inconsistência: R$ {balance} com {real_ads} ads.",
                    "timestamp": {".sv": "timestamp"}
                })
        return {"status": "processed", "nexus_action": "monitoring"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/ai/recall")
async def ai_recall(data: dict = Body(...)):
    uid = data.get("uid", "admin_master")
    query = data.get("query", "")
    results = memory_recall(uid, query)
    return {"results": results, "count": len(results)}

@app.get("/ai/status")
async def ai_status():
    """Retorna o status detalhado da IA para o painel."""
    try:
        health = tool_analyze_health()

        # Determina o motor de IA prioritário disponível
        motor_ativo = "nenhum"
        if GROQ_AVAILABLE:
            motor_ativo = "groq"
        else:
            # Verifica se Gemini está configurado
            config = db.reference('config').get() or {}
            gemini_key = os.environ.get("GEMINI_API_KEY") or str(config.get('geminiKey', '')).strip()
            if gemini_key:
                motor_ativo = "gemini"

        return {
            "status": "online",
            "engine": "Groq/Gemini Hybrid",
            "motor_ativo": motor_ativo,
            "independente_de_api_paga": GROQ_AVAILABLE,  # Groq Cloud Free Tier
            "ambiente": "Produção" if HUB_MODE == "ADMIN" else "Desenvolvimento",
            "motores": {
                "groq": {"ativo": GROQ_AVAILABLE},
                "gemini": {"ativo": motor_ativo == "gemini" or (not GROQ_AVAILABLE and motor_ativo != "nenhum")},
                "ollama": {"ativo": False}
            },
            "alert_level": compute_alert_level(),
            "last_audit": datetime.now().isoformat(),
            "mode": HUB_MODE,
            "neural_sync": True,
            "system_health": health
        }
    except Exception as e:
        print(f"[AI STATUS] Erro: {e}")
        return {"status": "degraded", "error": str(e)}

@app.post("/ai/chat")
async def ai_chat(data: dict = Body(...)):
    prompt = data.get("prompt", "")
    uid = data.get("uid", "admin_master")
    history = data.get("history", [])
    answer = await ask_ai(prompt, uid)
    return {"answer": answer}

# --- STUDIO WORKSPACE API ---

@app.get("/api/studio/files")
async def studio_files():
    try:
        files = os.listdir(WORKSPACE_DIR)
        file_details = []
        for f in files:
            path = os.path.join(WORKSPACE_DIR, f)
            stat = os.stat(path)
            file_details.append({
                "name": f,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "ext": f.split('.')[-1] if '.' in f else 'txt'
            })
        return {"status": "success", "files": file_details}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/api/studio/read-file/{filename}")
async def studio_read_file(filename: str):
    try:
        # Sanitização
        filename = os.path.basename(filename)
        path = os.path.join(WORKSPACE_DIR, filename)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        with open(path, "r", encoding="utf-8") as f:
            return {"status": "success", "content": f.read()}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/api/studio/save-file")
async def studio_save_file(data: dict = Body(...)):
    filename = data.get("filename")
    content = data.get("content")
    if not filename or content is None:
        return {"status": "error", "msg": "Nome e conteúdo são obrigatórios"}

    result = tool_write_studio_file(filename, content)
    if "sucesso" in result:
        return {"status": "success", "msg": result}
    return {"status": "error", "msg": result}

@app.delete("/api/studio/delete-file/{filename}")
async def studio_delete_file(filename: str):
    try:
        filename = os.path.basename(filename)
        path = os.path.join(WORKSPACE_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
            return {"status": "success", "msg": f"Arquivo {filename} removido."}
        return {"status": "error", "msg": "Arquivo não encontrado."}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

# --- SERVE STATIC FILES ---
# As rotas estáticas manuais foram removidas em favor dos mounts automáticos.
# O site de usuários (WWW) será servido na raiz (/) e o admin em (/admin).

# --- API DE TELEMETRIA E SESSÃO ---
@app.post("/api/session/pulse")
async def session_pulse():
    return {"status": "online", "timestamp": time.time(), "core": "CyberCore-Nexus"}

# --- API: MÉTRICAS EM TEMPO REAL ---
@app.get("/api/metrics")
async def api_metrics():
    try:
        # Ping do Firebase (latência)
        t0 = time.time()
        db.reference('status/ping_test').set({"ts": time.time()})
        ping = round((time.time() - t0) * 1000, 1)
    except:
        ping = 0
    try:
        import psutil
        cpu = round(psutil.cpu_percent(interval=0.1), 1)
        ram = round(psutil.virtual_memory().used / 1024 / 1024, 0)
    except:
        cpu = 0
        ram = 0
    try:
        users = db.reference('users').get() or {}
        config = db.reference('config').get() or {}
        hits = config.get('stats', {}).get('hits', 0)
        cpm = config.get('cpm', 0.18)
        dollar = get_dollar_rate()
        revenue = (hits / 1000) * cpm * dollar
        total_debt = sum(float(u.get('balance', 0)) for u in users.values() if isinstance(u, dict))
        net = revenue - total_debt
    except:
        revenue, total_debt, net = 0, 0, 0
    return {
        "ping": ping, "cpu": cpu, "ram": str(int(ram)) + "MB",
        "revenue_brl": round(revenue, 2), "total_debt": round(total_debt, 2),
        "net_profit_brl": round(net, 2),
        "status": "online", "timestamp": datetime.now().isoformat()
    }

# --- API: APROVAR TODOS OS SAQUES ---
@app.post("/payments/approve-all")
async def approve_all_payments_route():
    try:
        result = await auto_approve_withdrawals(force=True)
        return {"status": "success", "msg": result}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/audit/financial")
def get_audit(): return tool_analyze_health()

@app.post("/user/claim-daily/{uid}")
@app.get("/user/claim-daily/{uid}")
@app.post("/user/claim-daily/{uid}/")
@app.get("/user/claim-daily/{uid}/")
async def claim_daily(uid: str):
    try:
        user_ref = db.reference(f'users/{uid}')
        user_data = user_ref.get()
        if not user_data:
            return {"status": "error", "message": "Usuário não encontrado"}

        # Trava de Segurança: Verificação de Data
        today = datetime.now().strftime('%Y-%m-%d')
        last_bonus = user_data.get('last_daily_bonus_date')

        if last_bonus == today:
            raise HTTPException(status_code=400, detail="Bônus já resgatado hoje.")

        # Bloqueio de Fim de Semana (Sábado/Domingo)
        weekday = datetime.now().weekday()  # 0=Seg, 6=Dom
        if weekday >= 5:
            raise HTTPException(status_code=400, detail="Bônus disponível apenas em dias úteis (Seg a Sex).")

        current_balance = float(user_data.get('balance', 0))
        new_balance = current_balance + 0.50

        user_ref.update({
            "balance": new_balance,
            "last_daily_bonus_date": today,
            "last_claim": datetime.now().isoformat()
        })

        return {"status": "success", "new_balance": new_balance, "message": "Bônus diário resgatado!"}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/video/start/{uid}")
@app.get("/video/start/{uid}")
async def video_start(uid: str):
    return {"status": "success", "session": "active", "timestamp": datetime.now().isoformat()}

@app.post("/video/complete/{uid}")
async def video_complete(uid: str):
    try:
        user_ref = db.reference(f'users/{uid}')
        user_data = user_ref.get()
        if not user_data:
            return {"status": "error", "message": "Usuário não encontrado"}

        # --- SEGURANÇA: COOLDOWN DE VÍDEO (30 segundos) ---
        last_video_at = user_data.get('last_video_at')
        if last_video_at:
            last_ts = datetime.fromisoformat(last_video_at)
            diff = (datetime.now() - last_ts).total_seconds()
            if diff < 28:  # 28s de margem para os 30s de frontend
                risk = user_data.get('risk_score', 0) + 10
                user_ref.update({"risk_score": risk})
                return {"status": "error", "message": "Processamento muito rápido. Aguarde o tempo da IA."}

        # Incrementa saldo (R$ 0.15) e contador de vídeos
        current_balance = float(user_data.get('balance', 0))
        current_videos = int(user_data.get('videosWatched', 0))

        new_balance = current_balance + 0.15
        new_videos = current_videos + 1

        # Promoção de Referência: Ao atingir 15 vídeos, o padrinho (sponsor) ganha +1 validReferral
        if new_videos == 15:
            sponsor_uid = user_data.get('referredBy')
            if sponsor_uid:
                sponsor_ref = db.reference(f'users/{sponsor_uid}')
                sponsor_data = sponsor_ref.get()
                if sponsor_data:
                    current_valid = sponsor_data.get('validReferrals', 0)
                    sponsor_ref.update({"validReferrals": current_valid + 1})
                    # Log da bonificação
                    db.reference('logs/referrals').push({
                        "sponsor": sponsor_uid,
                        "referral": uid,
                        "action": "BONUS_CONVERTED",
                        "timestamp": {".sv": "timestamp"}
                    })

        user_ref.update({
            "balance": new_balance,
            "videosWatched": new_videos,
            "last_video_at": datetime.now().isoformat()
        })

        return {"status": "success", "new_balance": new_balance, "videos_count": new_videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/payments/request/{uid}")
async def request_withdrawal(uid: str, data: dict = Body(...)):
    try:
        amount = float(data.get("amount", 0))
        pix_key = data.get("pixKey", "").strip()
        project_id = data.get("projectId") or data.get("nodeId")

        # --- SEGURANÇA: VALIDAÇÃO DE SALDO REAL ---
        user_ref = db.reference(f'users/{uid}')
        user_data = user_ref.get()

        if not user_data:
            return {"status": "error", "message": "Usuário não localizado."}

        current_balance = float(user_data.get('balance', 0))

        if current_balance < amount:
            return {"status": "error", "message": f"Saldo insuficiente. Você tem R$ {current_balance:.2f}"}

        # Ajustado para R$ 0.50 para permitir seus testes iniciais
        if amount < 0.50:
            return {"status": "error", "message": "Valor mínimo para saque é R$ 0,50"}

        if not pix_key:
            return {"status": "error", "message": "Chave PIX é obrigatória"}

        # --- SEGURANÇA: COOLDOWN DE SAQUE (1 por hora) ---
        last_withdraw = user_data.get('last_withdraw_at')
        if last_withdraw:
            lw_ts = datetime.fromisoformat(last_withdraw)
            if (datetime.now() - lw_ts).total_seconds() < 3600:
                 return {"status": "error", "message": "Limite de 1 resgate por hora. Proteção CyberCore."}

        # Gera ID de saque e timestamp numérico para o Frontend
        ts = int(datetime.now().timestamp() * 1000)
        wid = f"WID{ts}"

        withdraw_obj = {
            "amount": amount,
            "pixKey": pix_key,
            "pixType": data.get("pixType", "EVP"),
            "status": "pending",
            "timestamp": ts,
            "created_at": datetime.now().isoformat(),
            "uid": uid,
            "projectId": project_id,
            "fingerprint": data.get("fingerprint", "unknown"),
            "fp_detail": data.get("fp_detail", {})
        }

        # 1. Registra o saque
        db.reference(f'withdrawals/{uid}/{wid}').set(withdraw_obj)
        # 2. Adiciona à fila do admin
        db.reference(f'admin/pending_withdrawals/{wid}').set(withdraw_obj)
        # 3. Deduz o saldo e atualiza last_withdraw
        new_balance = current_balance - amount
        user_ref.update({
            "balance": new_balance,
            "last_withdraw_at": datetime.now().isoformat()
        })

        return {"status": "success", "message": "Solicitação de saque enviada!", "wid": wid}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/heartbeat/site")
@app.get("/heartbeat/site")
async def heartbeat(data: dict = Body(default={"source": "direct_access"})):
    try:
        db.reference(f'status/{data.get("source", "unknown")}_last_pulse').set({".sv": "timestamp"})
        return {"ok": True, "status": "pulsing"}
    except:
        return {"ok": False, "error": "Firebase logic failed"}

# --- PAINEL GERENCIAMENTO INTEGRATION ---
@app.post("/api/cybercore/heartbeat")
async def painel_heartbeat():
    """Endpoint para verificar status do Hub CyberCore."""
    db.reference('status/cybercore_last_pulse').set({".sv": "timestamp"})
    return {"status": "cybercore_online", "service": "CyberCore-Hub"}

@app.post("/api/cybercore/analyze_project")
async def analyze_project(data: dict = Body(...)):
    """Analisa uma URL para identificar tecnologias e nível de segurança."""
    url = data.get("url")
    if not url:
        return {"status": "error", "msg": "URL não fornecida"}

    try:
        if not url.startswith("http"):
            url = "https://" + url

        # Simulação de Scraping/Análise de Tecnologias
        # Em um cenário real, usaríamos BeautifulSoup ou Selenium
        response = requests.get(url, timeout=10)
        html = response.text.lower()

        techs = []
        if "react" in html or "_next" in html: techs.append("React/Next.js")
        if "vue" in html: techs.append("Vue.js")
        if "firebase" in html: techs.append("Firebase")
        if "service-worker.js" in html or "manifest.json" in html: techs.append("PWA")

        # Heurística de segurança
        security_score = 85
        if not url.startswith("https"): security_score -= 40
        if "eval(" in html: security_score -= 15

        project_data = {
            "name": url.split("//")[-1].split("/")[0],
            "url": url,
            "tech_stack": techs or ["Generic Web"],
            "security_score": max(0, security_score),
            "detected_at": datetime.now().isoformat(),
            "status": "ready_to_connect"
        }

        return {"status": "success", "data": project_data}

    except Exception as e:
        return {"status": "error", "msg": f"Falha ao escanear URL: {str(e)}"}


@app.post("/api/project/analyze")
async def project_analyze(data: dict = Body(...)):
    """Analisa projetos multi-tipo: website, android, api, local."""
    ptype = data.get("type", "website")
    identifier = data.get("identifier", "")

    if not identifier:
        return {"status": "error", "msg": "Identificador não fornecido"}

    result = {"status": "Conectado", "framework": "Desconhecido", "ambiente": "Produção", "monitoring": "Ativo"}

    try:
        if ptype == "website":
            url = identifier if identifier.startswith("http") else "https://" + identifier
            resp = requests.get(url, timeout=10)
            html = resp.text.lower()
            techs = []
            if "react" in html or "_next" in html: techs.append("React/Next.js")
            if "vue" in html or "nuxt" in html: techs.append("Vue.js/Nuxt")
            if "wordpress" in html or "wp-content" in html: techs.append("WordPress")
            if "laravel" in html or "livewire" in html: techs.append("Laravel")
            if "firebase" in html: techs.append("Firebase")
            result["framework"] = techs[0] if techs else "HTML / Estático"
            result["ambiente"] = "Produção" if "https" in url else "Desenvolvimento"

        elif ptype == "android":
            result["framework"] = "Android Native / Kotlin"
            result["ambiente"] = "APK Identificado"
            result["status"] = "Pronto para análise de dependências"

        elif ptype == "api":
            resp = requests.get(identifier, timeout=10)
            ct = resp.headers.get("content-type", "").lower()
            if "graphql" in ct: result["framework"] = "GraphQL"
            elif "json" in ct: result["framework"] = "REST API (JSON)"
            else: result["framework"] = f"API ({resp.status_code})"
            result["ambiente"] = "Produção"

        elif ptype == "local":
            result["framework"] = "Sistema Local"
            result["ambiente"] = identifier
            result["status"] = "Endpoint manual - verifique conectividade"

        return {"status": "success", "data": result}

    except requests.exceptions.RequestException:
        return {"status": "partial", "data": {"status": "Inacessível", "framework": "Não detectado (offline)", "ambiente": "Desconhecido", "monitoring": "Pendente"}}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


@app.post("/api/project/save")
async def project_save(data: dict = Body(...)):
    """Salva um projeto conectado no Firebase via admin SDK (burlas regras do client)."""
    project_id = data.get("id")
    project_data = data.get("data", {})
    if not project_id or not project_data:
        return {"status": "error", "msg": "id e data são obrigatórios"}
    try:
        db.reference(f'neural/nodes/{project_id}').set(project_data)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


@app.post("/api/project/remove")
async def project_remove(data: dict = Body(...)):
    """Remove um projeto conectado do Firebase via admin SDK."""
    project_id = data.get("id")
    if not project_id:
        return {"status": "error", "msg": "id é obrigatório"}
    try:
        db.reference(f'neural/nodes/{project_id}').delete()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


@app.get("/api/local/setup-script")
async def get_setup_script():
    """Retorna o script do agente local para instalação."""
    script_path = os.path.join(PROJECT_ROOT, "core", "local_agent.py")
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            return {"status": "success", "script": f.read()}
    return {"status": "error", "msg": "Script não encontrado"}


@app.get("/api/local/install-command")
async def get_install_command():
    """Retorna o comando de terminal para instalar o agente local."""
    # Assume que o servidor está rodando em um host acessível
    # Em ambiente local, usamos localhost:7860
    host = "http://localhost:7860" # Idealmente viria de uma config ou request.base_url
    cmd = f"python -c \"import requests; r = requests.get('{host}/api/local/setup-script'); open('cybercore_agent.py', 'w', encoding='utf-8').write(r.json()['script'])\" && python cybercore_agent.py --hub {host}"
    return {"status": "success", "command": cmd}


@app.post("/payments/approve/{wid}")
async def approve_payment(wid: str):
    try:
        nodes = db.reference('neural/nodes').get() or {}
        global_config = db.reference('config').get() or {}
        global_asaas_key = global_config.get('asaasKey') or os.environ.get('ASAAS_API_KEY', '')

        withdraw_data = None
        target_uid = None
        all_withdrawals = db.reference('withdrawals').get() or {}

        for uid, ws in all_withdrawals.items():
            if wid in ws:
                withdraw_data = ws[wid]
                target_uid = uid
                break

        if not withdraw_data or not target_uid:
            return {"status": "error", "msg": "Saque não localizado."}

        if withdraw_data.get('status') != 'pending':
            return {"status": "error", "msg": f"Saque já processado (Status: {withdraw_data.get('status')})"}

        # Seleciona chave Asaas baseada no projeto
        pid = withdraw_data.get('projectId')
        node = nodes.get(pid) if pid else None
        api_key = (node.get('asaas_key') if node else None) or global_asaas_key

        if not api_key:
            msg = "⚠️ Alerta CyberCore: Chave API ASAAS não configurada!"
            tool_send_push('global', msg)
            return {"status": "error", "msg": "ASAAS_API_KEY não configurada para este projeto."}

        amount = float(withdraw_data.get('amount', 0))
        pix_key = withdraw_data.get('pixKey', '')
        # Usa o tipo de chave que veio do banco de dados (enviado pelo frontend)
        type_detected = withdraw_data.get('pixType', 'EVP')

        # Extrai apenas o token se a chave estiver no formato composto (com ::)
        api_key = api_key.split('::')[0].strip() if '::' in api_key else api_key.strip()

        final_pix_key = pix_key
        if type_detected in ['CPF', 'CNPJ', 'PHONE']:
            final_pix_key = "".join(filter(str.isdigit, pix_key))
            if type_detected == 'PHONE' and not final_pix_key.startswith('55'):
                if len(final_pix_key) <= 11: final_pix_key = "55" + final_pix_key

        # Define a URL correta baseada na chave
        if '_prod_' in api_key.lower():
            asaas_url = "https://www.asaas.com/api/v3/transfers"
        else:
            asaas_url = "https://sandbox.asaas.com/api/v3/transfers"

        headers = {"access_token": api_key, "Content-Type": "application/json"}
        payload = {
            "value": amount,
            "pixAddressKey": final_pix_key,
            "pixAddressKeyType": type_detected,
            "description": f"CyberCore Resgate #{wid}"
        }

        resp = requests.post(asaas_url, json=payload, headers=headers, timeout=25)
        res_json = resp.json()

        if resp.status_code == 200:
            # ... (código de sucesso existente)
            return {"status": "success", "msg": f"Pagamento de R$ {amount} enviado com sucesso!"}
        else:
            error_msg = res_json.get('errors', [{}])[0].get('description', 'Erro no gateway Asaas')
            # DISPARA PUSH DE ALERTA PARA O ADMIN
            tool_send_push('global', f"🚨 Falha no Saque: {error_msg} (Valor: R$ {amount})")
            return {"status": "error", "msg": error_msg}

    except Exception as e:
        return {"status": "error", "msg": f"Erro interno: {str(e)}"}

# --- STATIC MOUNTS (Configuração para Opção B: Separados) ---
# HUB_MODE já definido no topo

from fastapi.responses import JSONResponse, FileResponse

@app.exception_handler(404)
async def not_found_handler(request, exc):
    if request.url.path.startswith("/api/") or request.url.path.startswith("/ai/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    if request.url.path == "/favicon.ico":
        return JSONResponse(status_code=204, content=None)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

# Diagnóstico de caminhos
print(f"[PATH] BACKEND_DIR={BACKEND_DIR}")
print(f"[PATH] PROJECT_ROOT={PROJECT_ROOT}")
print(f"[PATH] WWW_DIR={WWW_DIR} (exists={os.path.isdir(WWW_DIR)})")
print(f"[PATH] ADMIN_DIR={ADMIN_DIR} (exists={os.path.isdir(ADMIN_DIR)})")
print(f"[PATH] CWD={os.getcwd()}")
print(f"[PATH] HUB_MODE={HUB_MODE}")

if HUB_MODE == "ADMIN":
    # No Space CyberCore, o Admin é a raiz
    try:
        app.mount("/", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
        print(f"[MODO] CyberCore IA - Painel Admin na raiz => {ADMIN_DIR}")
    except Exception as e:
        print(f"[ERRO] Falha ao montar Admin: {e}")
else:
    # No Space CineCash, o Site é a raiz e o Admin é um caminho secreto (opcional)
    try:
        app.mount("/", StaticFiles(directory=WWW_DIR, html=True), name="www")
        print(f"[MODO] CineCash IA - Site na raiz => {WWW_DIR}")
    except Exception as e:
        print(f"[ERRO] Falha ao montar Site: {e}")
    try:
        app.mount("/admin", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")
        print(f"[OK] Admin montado em /admin => {ADMIN_DIR}")
    except Exception as e:
        print(f"[ERRO] Falha ao montar Admin: {e}")

if __name__ == "__main__":
    import uvicorn
    import os

    # Forma robusta: aponta o diretório base e o nome do módulo sem o prefixo da pasta
    # Isso garante que tanto o uvicorn quanto o reload encontrem o arquivo main.py
    app_module = "main:app"

    preferred_port = int(os.environ.get("PORT", 7860))

    print(f"🚀 Iniciando CyberCore Elite em http://localhost:{preferred_port}")
    print(f"🔄 Modo Auto-Reload Ativado")

    uvicorn.run(
        app_module,
        host="0.0.0.0",
        port=preferred_port,
        reload=True,
        app_dir=BACKEND_DIR, # Define explicitamente onde o código reside
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
