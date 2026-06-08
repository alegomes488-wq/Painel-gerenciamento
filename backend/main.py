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
from fastapi import FastAPI, Body, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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

# --- CONFIGURAÇÃO DE PROVEDORES IA ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OLLAMA_URL = "http://localhost:11434/api/generate"

# Mapeamento de Especialistas CyberCore
AGENT_MODELS = {
    "ORCHESTRATOR": {"provider": "google", "model": "gemini-2.0-pro-exp"},
    "BUILDER":      {"provider": "groq",   "model": "deepseek-v3"},
    "DESIGNER":     {"provider": "google", "model": "gemini-2.0-flash"},
    "FULLSTACK":    {"provider": "groq",   "model": "deepseek-v3"},
    "PYTHON":       {"provider": "groq",   "model": "deepseek-v3"},
    "JAVA":         {"provider": "google", "model": "gemini-2.0-flash"},
    "SOFTWARE":     {"provider": "google", "model": "gemini-2.0-flash"},
    "AUDITOR":      {"provider": "groq",   "model": "deepseek-v3"},
    "SECURITY":     {"provider": "groq",   "model": "deepseek-v3"}
}

async def ask_ai_specialized(agent: str, prompt: str, uid="admin_master"):
    # --- ORCHESTRATOR 2.5: PIPELINE & DELEGATION ---
    if agent == "ORCHESTRATOR":
        pipeline_prompt = f"""Analise a solicitação: "{prompt}"
Determine a sequência de especialistas CyberCore necessários para resolver isso 100%.
Responda APENAS uma lista separada por vírgula em ordem de execução.
Opções: BUILDER, PYTHON, JAVA, FULLSTACK, DESIGNER, SECURITY, AUDITOR, SOFTWARE.

Exemplo de resposta: DESIGNER, BUILDER, SECURITY"""

        plan_raw = await ask_ai(pipeline_prompt, uid="system_router")
        if plan_raw:
            agents_sequence = [a.strip().upper() for a in plan_raw.split(",") if a.strip().upper() in AGENT_MODELS]
            if agents_sequence:
                print(f"[ORCHESTRATOR] Plano de Ação: {' -> '.join(agents_sequence)}")
                final_output = f"🔮 **Plano CyberCore Ativado:** {' → '.join(agents_sequence)}\n\n"

                current_context = prompt
                for i, step_agent in enumerate(agents_sequence):
                    print(f"[PIPELINE] Executando Passo {i+1}: {step_agent}")

                    # Para o primeiro agente, usamos o prompt original.
                    # Para os seguintes, passamos o resultado anterior como contexto.
                    if i == 0:
                        step_prompt = prompt
                    else:
                        step_prompt = f"Com base no progresso anterior:\n{step_result}\n\nContinue a tarefa: {prompt}"

                    step_result = await execute_single_agent(step_agent, step_prompt, uid)
                    final_output += f"### Passo {i+1}: {step_agent}\n{step_result}\n\n---\n\n"

                return final_output

    return await execute_single_agent(agent, prompt, uid)

async def execute_single_agent(agent: str, prompt: str, uid: str):
    config = AGENT_MODELS.get(agent, AGENT_MODELS["ORCHESTRATOR"])
    provider = config.get("provider", "google")
    model_name = config.get("model", "gemini-2.0-pro-exp")

    try:
        if provider == "groq" and GROQ_AVAILABLE:
            system_msg = f"Você é o especialista {agent} do CyberCore IA. Use o modelo {model_name} para fornecer soluções técnicas de elite."
            return groq_generate(f"{system_msg}\n\nUsuário: {prompt}") or "Falha no Groq"

        elif provider == "google":
            system_msg = f"Você é o especialista {agent} do CyberCore IA. Responda de forma técnica e precisa."
            gemini_result = gemini_generate(f"{system_msg}\n\nUsuário: {prompt}", model=model_name)
            if not gemini_result.startswith("Erro Gemini"):
                return gemini_result
            return await ask_ai(f"Atuando como {agent}: {prompt}", uid)

        elif provider == "ollama":
            try:
                resp = requests.post(OLLAMA_URL, json={"model": model_name, "prompt": prompt, "stream": False}, timeout=60)
                if resp.status_code == 200:
                    return resp.json().get("response", "Erro na resposta Ollama")
            except:
                return "Ollama Local Offline. Tente iniciar o serviço."

        return await ask_ai(prompt, uid)
    except Exception as e:
        return f"Erro no Agente {agent}: {str(e)}"

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

def get_project_workspace(project="default"):
    """Retorna o diretório do workspace para um projeto específico, criando se necessário."""
    path = os.path.join(WORKSPACE_DIR, project)
    os.makedirs(path, exist_ok=True)
    return path

# --- CYBERCORE MEMÓRIA PERSISTENTE ---
MEMORY_DIR = os.path.join(PROJECT_ROOT, "cybercore-memory")
for sub in ["projects", "agents", "architecture", "logs"]:
    os.makedirs(os.path.join(MEMORY_DIR, sub), exist_ok=True)

def memory_file_read(category: str, name: str):
    try:
        path = os.path.join(MEMORY_DIR, category, f"{name}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    except: return None

def memory_file_save(category: str, name: str, data: dict):
    try:
        path = os.path.join(MEMORY_DIR, category, f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except: return False

def memory_file_list(category: str):
    try:
        path = os.path.join(MEMORY_DIR, category)
        files = [f.replace(".json","") for f in os.listdir(path) if f.endswith(".json")]
        return sorted(files)
    except: return []

def memory_log(category: str, entry: dict):
    try:
        entry["timestamp"] = datetime.now().isoformat()
        logfile = os.path.join(MEMORY_DIR, "logs", f"{category}.jsonl")
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except: pass

def tool_write_studio_file(filename, content, project="default"):
    try:
        filename = os.path.basename(filename)
        path = os.path.join(get_project_workspace(project), filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Arquivo {filename} gerado com sucesso no projeto {project}."
    except Exception as e:
        return f"Erro ao escrever arquivo: {e}"

def tool_list_studio_files(project="default"):
    try:
        files = os.listdir(get_project_workspace(project))
        return {"files": files, "project": project}
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

def gemini_generate(prompt, model="gemini-2.0-flash"):
    """Call Google Gemini with a specific model directly."""
    config = db.reference('config').get() or {}
    api_key = os.environ.get("GEMINI_API_KEY") or str(config.get('geminiKey', '')).strip()
    if not api_key:
        return "Gemini não configurado. Configure GEMINI_API_KEY."
    try:
        api_ver = "v1beta" if "flash" in model or "pro" in model else "v1"
        url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        resp = requests.post(url, json=payload, timeout=60)
        data = resp.json()
        if resp.status_code == 200 and "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0].get("text", "Sem resposta.")
        return f"Erro Gemini: {data.get('error', {}).get('message', str(data))}"
    except Exception as e:
        return f"Erro ao chamar Gemini: {str(e)}"

# --- GPT MAKER API ---
GPTMAKER_BASE = "https://api.gptmaker.ai/v2"

def _get_gptmaker_token():
    config = db.reference('config').get() or {}
    token = os.environ.get("GPTMAKER_API_KEY") or str(config.get('gptmakerKey', '')).strip()
    return token

def _gptmaker_headers():
    token = _get_gptmaker_token()
    if not token:
        return None
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def gptmaker_list_workspaces():
    headers = _gptmaker_headers()
    if not headers:
        return {"status": "error", "msg": "GPT Maker token não configurado."}
    try:
        resp = requests.get(f"{GPTMAKER_BASE}/workspaces", headers=headers, timeout=15)
        if resp.status_code == 200:
            return {"status": "success", "workspaces": resp.json()}
        return {"status": "error", "msg": f"Erro GPT Maker: {resp.status_code} - {resp.text}"}
    except Exception as e:
        return {"status": "error", "msg": f"Falha ao conectar GPT Maker: {str(e)}"}

def gptmaker_list_agents(workspace_id: str):
    headers = _gptmaker_headers()
    if not headers:
        return {"status": "error", "msg": "GPT Maker token não configurado."}
    try:
        resp = requests.get(f"{GPTMAKER_BASE}/workspace/{workspace_id}/agents", headers=headers, timeout=15)
        if resp.status_code == 200:
            return {"status": "success", "agents": resp.json()}
        return {"status": "error", "msg": f"Erro GPT Maker: {resp.status_code} - {resp.text}"}
    except Exception as e:
        return {"status": "error", "msg": f"Falha ao conectar GPT Maker: {str(e)}"}

def gptmaker_conversation(agent_id: str, prompt: str, context_id: str = "cybercore_studio"):
    headers = _gptmaker_headers()
    if not headers:
        return {"status": "error", "msg": "GPT Maker token não configurado."}
    try:
        payload = {
            "contextId": context_id,
            "prompt": prompt
        }
        resp = requests.post(f"{GPTMAKER_BASE}/agent/{agent_id}/conversation", json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            return {"status": "success", "message": data.get("message", ""), "images": data.get("images", []), "audios": data.get("audios", []), "documents": data.get("documents", [])}
        return {"status": "error", "msg": f"Erro GPT Maker: {resp.status_code} - {resp.text}"}
    except Exception as e:
        return {"status": "error", "msg": f"Falha ao conversar com GPT Maker: {str(e)}"}

def groq_generate(prompt, system_extra="", uid="admin_master"):
    if not GROQ_AVAILABLE:
        return None
    try:
        groq_model = GROQ_MODEL_MAP.get(model := "llama3:latest", "llama-3.3-70b-versatile")

        # Busca dados do usuário para contexto
        user_context = ""
        if uid and uid != "admin_master" and uid != "guest":
            try:
                u = db.reference(f'users/{uid}').get()
                if u:
                    user_context = f"""CONTEXTO DO USUÁRIO:
- Nome: {u.get('fullname') or u.get('firstname') or u.get('username') or uid}
- Saldo: R$ {float(u.get('balance', 0)):.2f}
- Anúncios processados: {u.get('videosWatched', 0)}
- Status: {u.get('status', 'ativo')}
"""
            except:
                pass

        system_prompt = f"""Você é o Agente Nexus, um assistente virtual especializado no CineCash, uma plataforma que paga usuários para processar anúncios via IA.

REGRAS GERAIS:
1. Responda SEMPRE em português brasileiro, de forma amigável, didática e motivacional.
2. Trate o usuário com respeito e paciência, como um tutor.
3. NUNCA invente informações — se não souber, diga que vai verificar.
4. Pode usar [COMMAND:NAVIGATE:nome_da_aba] para sugerir navegação: inicio, intercambio, convites, historico.
5. Pode usar [COMMAND:START_TOUR] para iniciar o tour guiado.

PLATAFORMA CINECASH:
- 4 abas principais: Início (dashboard), Intercâmbio (saques), Convites (indicações), Histórico (transações)
- Anúncios: o usuário clica em "Processar Anúncios" no dashboard para validar campanhas via IA
- Saldo: exibido no topo, acumulado por anúncios, bônus diário e indicações
- Saque mínimo: R$ 0,50 via PIX
- Valores de saque: R$ 0,50 | R$ 3,00 | R$ 5,00 | R$ 10,00 | R$ 50,00

BÔNUS DIÁRIO:
- Valor: R$ 0,20
- Disponível apenas em finais de semana (sábado e domingo)
- 1 vez por dia, botão "COLETAR BÔNUS" na aba Início

METAS (progresso de anúncios → valor de saque liberado):
- 150 anúncios → R$ 0,50
- 900 anúncios → R$ 3,00
- 1500 anúncios → R$ 5,00
- 3000 anúncios → R$ 10,00
- 15000 anúncios → R$ 50,00

SISTEMA DE CONVITES (INDICAÇÕES):
- Cada amigo convidado que assistir 25 anúncios rende R$ 0,20
- A cada 5 amigos válidos, bônus extra de R$ 1,00
- O link de convite fica na aba Convites

TIPOS DE CHAVE PIX:
- CPF: 11 dígitos
- CNPJ: 14 dígitos
- E-mail: formato padrão
- Telefone: 10 a 13 dígitos (com DDD)
- Chave aleatória (EVP): formato UUID

PROCESSAMENTO DE PAGAMENTOS:
- Os saques são processados via gateway Asaas
- Status: Pendente → Pago ou Recusado
- Aprovação manual pelo administrador

{user_context}"""

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
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
        # Busca dados do usuário para contexto
        user_context = ""
        if uid and uid != "admin_master" and uid != "guest":
            try:
                u = db.reference(f'users/{uid}').get()
                if u:
                    user_context = f"""
DADOS DO USUÁRIO ATUAL:
- Nome: {u.get('fullname') or u.get('firstname') or u.get('username') or uid}
- Saldo: R$ {float(u.get('balance', 0)):.2f}
- Anúncios processados: {u.get('videosWatched', 0)}
- Status: {u.get('status', 'ativo')}
"""
            except:
                pass

        # Prioridade 1: Groq (mais rápido, gratuito, sempre disponível)
        groq_result = groq_generate(prompt, uid=uid)
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
            system_prompt = f"""Você é o Agente Nexus do CineCash, especialista na plataforma.

REGRAS:
- Responda em PT-BR de forma amigável, didática e motivacional.
- Use [COMMAND:NAVIGATE:inicio|intercambio|convites|historico] para sugerir navegação.
- Use [COMMAND:START_TOUR] para iniciar o tour guiado.

SOBRE O CINECASH:
- 4 abas: Início (dashboard/processar anúncios), Intercâmbio (saques PIX), Convites (indicações), Histórico (transações)
- Saque mínimo: R$ 0,50. Valores: R$ 0,50 | R$ 3,00 | R$ 5,00 | R$ 10,00 | R$ 50,00
- Bônus diário: R$ 0,20 apenas em fins de semana
- Metas: 150→R$0,50 | 900→R$3,00 | 1500→R$5,00 | 3000→R$10,00 | 15000→R$50,00
- Convites: R$ 0,20 por amigo válido (25 ads), +R$ 1,00 a cada 5 amigos

{user_context}"""

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

# --- CYBERCORE BRIDGE: ENDPOINTS ---
@app.post("/api/cybercore/chat")
async def cybercore_chat(data: dict = Body(...)):
    """Portal único: prompt -> CyberCore (GPT Maker) raciocina -> plano -> execução"""
    prompt = data.get("prompt", "")
    project = data.get("project", "default")
    uid = data.get("uid", "admin_cybercore")
    context_id = f"cybercore_{project}"

    if not prompt:
        return {"status": "error", "msg": "Prompt obrigatório"}

    project_memory = memory_file_read("projects", project) or {
        "name": project, "created": datetime.now().isoformat(),
        "tech_stack": [], "status": "desenvolvimento", "context": ""
    }
    agent_memories = {}
    for agent_name in ["BUILDER","DESIGNER","FULLSTACK","PYTHON","JAVA","SOFTWARE"]:
        am = memory_file_read("agents", agent_name.lower())
        if am: agent_memories[agent_name] = am

    memory_context = project_memory.get("context", "")
    agents_context = "\n".join([f"- {k}: {v.get('role','')} | status: {v.get('status','')}" for k,v in agent_memories.items()])

    gptmaker_agent_id = os.environ.get("CYBERCORE_GPTMAKER_AGENT")
    if not gptmaker_agent_id:
        config_ref = db.reference('config').get() or {}
        gptmaker_agent_id = config_ref.get('cybercoreGptmakerAgent', '')

    coordinator_prompt = f"""SISTEMA: Você é o CEO Digital da CyberCore IA.

MEMÓRIA DO PROJETO "{project}":
Status: {project_memory.get('status','desenvolvimento')}
Stack: {', '.join(project_memory.get('tech_stack',[])) or 'Indefinido'}
Contexto: {memory_context[:2000] if memory_context else 'Novo projeto'}

AGENTES DISPONÍVEIS:
{agents_context or 'Nenhum agente configurado ainda.'}

OBJETIVO DO USUÁRIO: {prompt}

INSTRUÇÕES:
1. Analise o objetivo e o contexto do projeto.
2. Crie um plano de ação detalhado.
3. Defina quais agentes CyberCore executarão cada parte.
4. Para cada tarefa, especifique o agente e a descrição.

Responda EXATAMENTE neste formato JSON (sem markdown):
{{
  "raciocinio": "seu raciocínio detalhado aqui",
  "plano": [
    {{"agente": "DESIGNER", "tarefa": "descrição clara da tarefa"}},
    {{"agente": "BUILDER", "tarefa": "descrição clara da tarefa"}}
  ],
  "mudancas_memoria": {{
    "project_status": "atualização do status se aplicável",
    "tech_stack": ["tecnologias identificadas"],
    "context_summary": "resumo do que foi feito"
  }}
}}"""

    answer = ""
    if gptmaker_agent_id:
        gpt_resp = gptmaker_conversation(gptmaker_agent_id, coordinator_prompt, context_id=context_id)
        if gpt_resp.get("status") == "success":
            answer = gpt_resp.get("message", "")
        else:
            answer = f"[GPT Maker fallback] {gpt_resp.get('msg', '')}"
    else:
        answer = await ask_ai(coordinator_prompt, uid=uid)

    plan = []
    raciocinio = ""
    memory_updates = {}
    try:
        json_str = answer
        if "```json" in answer:
            json_str = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            json_str = answer.split("```")[1].split("```")[0]
        parsed = json.loads(json_str.strip())
        raciocinio = parsed.get("raciocinio", answer[:500])
        plan = parsed.get("plano", [])
        memory_updates = parsed.get("mudancas_memoria", {})
    except:
        raciocinio = answer[:1000]
        plan = []

    if memory_updates:
        if memory_updates.get("project_status"):
            project_memory["status"] = memory_updates["project_status"]
        if memory_updates.get("tech_stack"):
            existing = set(project_memory.get("tech_stack", []))
            existing.update(memory_updates["tech_stack"])
            project_memory["tech_stack"] = list(existing)
        if memory_updates.get("context_summary"):
            old = project_memory.get("context", "")
            project_memory["context"] = f"{old}\n[{datetime.now().strftime('%d/%m/%Y %H:%M')}] {memory_updates['context_summary']}"[-5000:]
    project_memory["last_prompt"] = prompt
    project_memory["last_updated"] = datetime.now().isoformat()
    memory_file_save("projects", project, project_memory)

    memory_log("chat", {
        "project": project, "prompt": prompt,
        "agents_planned": [p.get("agente") for p in plan],
        "raciocinio": raciocinio[:200]
    })

    return {
        "status": "success",
        "raciocinio": raciocinio,
        "plano": plan,
        "projeto": project_memory,
        "raw": answer,
        "mensagem": f"🧠 **CyberCore analisou:**\n{raciocinio}\n\n**Plano:** {len(plan)} tarefas distribuídas."
    }

@app.post("/api/cybercore/execute")
async def cybercore_execute(data: dict = Body(...)):
    """Executa um plano da CyberCore: distribui tarefas para os agentes"""
    plan = data.get("plano", [])
    project = data.get("project", "default")
    uid = data.get("uid", "admin_cybercore")
    context_extra = data.get("contexto_extra", "")

    if not plan:
        return {"status": "error", "msg": "Plano vazio. Use /api/cybercore/chat primeiro."}

    ctx_resp = await studio_context(project)
    workspace_ctx = ctx_resp.get("context", "") if ctx_resp.get("status") == "success" else ""

    results = []
    for i, task in enumerate(plan):
        agent = task.get("agente", "").upper().strip()
        tarefa = task.get("tarefa", "")
        if agent not in AGENT_MODELS:
            results.append({"agente": agent, "status": "ignorado", "output": f"Agente {agent} não reconhecido"})
            continue

        agent_prompt = f"""CONTEXTO DO WORKSPACE:
{workspace_ctx[:3000] if workspace_ctx else 'Projeto novo'}

TAREFA ATUAL ({i+1}/{len(plan)}): {tarefa}

INSTRUÇÕES PARA {agent}:
{context_extra}

- Analise o contexto do workspace e execute APENAS sua tarefa específica.
- Para código: responda APENAS JSON bruto {{"arquivo": "conteudo"}} sem markdown.
- Se for análise/relatório: responda em markdown."""

        try:
            check_credits(agent) and deduct_credit(agent) if check_credits(agent) else None
            output = await execute_single_agent(agent, agent_prompt, uid)

            try:
                json_str = output
                if "```json" in output:
                    json_str = output.split("```json")[1].split("```")[0]
                elif "```" in output:
                    json_str = output.split("```")[0]
                files = json.loads(json_str.strip())
                if isinstance(files, dict) and len(files) > 0:
                    saved = []
                    for fn, fc in files.items():
                        tool_write_studio_file(fn, fc, project)
                        saved.append(fn)
                    results.append({"agente": agent, "status": "concluido", "output": f"Arquivos: {', '.join(saved)}", "arquivos": saved})
                    continue
            except:
                pass

            results.append({"agente": agent, "status": "concluido", "output": output[:2000]})
        except Exception as e:
            results.append({"agente": agent, "status": "erro", "output": str(e)})

        memory_log("execute", {"project": project, "agent": agent, "task": tarefa[:100], "status": results[-1]["status"]})

    return {
        "status": "success",
        "resultados": results,
        "total": len(results),
        "concluidos": sum(1 for r in results if r["status"] == "concluido"),
        "mensagem": f"**Execução concluída:** {sum(1 for r in results if r['status'] == 'concluido')}/{len(results)} tarefas."
    }

@app.get("/api/cybercore/memory/{category:path}")
async def cybercore_memory_list(category: str = ""):
    if not category or category.strip() == "":
        return {"status": "success", "categories": ["projects","agents","architecture","logs"]}
    category = category.strip("/")
    if category not in ["projects","agents","architecture","logs"]:
        return {"status": "error", "msg": "Categoria inválida"}
    items = memory_file_list(category)
    return {"status": "success", "category": category, "items": items}

@app.get("/api/cybercore/memory/{category}/{name}")
async def cybercore_memory_read(category: str, name: str):
    if category not in ["projects","agents","architecture","logs"]:
        return {"status": "error", "msg": "Categoria inválida"}
    data = memory_file_read(category, name)
    if data is None:
        return {"status": "error", "msg": "Item não encontrado"}
    return {"status": "success", "category": category, "name": name, "data": data}

@app.post("/api/cybercore/memory/{category}/{name}")
async def cybercore_memory_save(category: str, name: str, data: dict = Body(...)):
    if category not in ["projects","agents","architecture"]:
        return {"status": "error", "msg": "Categoria inválida para escrita"}
    ok = memory_file_save(category, name, data.get("data", data))
    if ok:
        memory_log("memory", {"action": "save", "category": category, "name": name})
        return {"status": "success", "msg": f"{category}/{name} salvo"}
    return {"status": "error", "msg": "Falha ao salvar"}

@app.get("/api/cybercore/logs/{category}")
async def cybercore_logs(category: str):
    try:
        path = os.path.join(MEMORY_DIR, "logs", f"{category}.jsonl")
        if not os.path.exists(path):
            return {"status": "success", "logs": []}
        logs = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    logs.append(json.loads(line))
        return {"status": "success", "logs": logs[-50:]}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

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
    """Recebe dados do Agente Nexus ou Local e encaminha ao Painel via Firebase."""
    try:
        uid = data.get("uid")
        if not uid: return {"status": "ignored"}

        source = data.get("source", "nexus")
        telemetry = data.get("telemetry", data) # Fallback para compatibilidade

        # 1. Se for Telemetria de Nó Local
        if source == "local_node":
            node_id = uid
            db.reference(f'neural/nodes/{node_id}/health').update({
                "status": telemetry.get("status", "online"),
                "latency_ms": telemetry.get("latency_ms", 0),
                "cpu": telemetry.get("cpu_usage", 0),
                "ram": telemetry.get("ram_usage", 0),
                "last_checked": datetime.now().isoformat(),
                "metrics": telemetry
            })
            return {"status": "processed", "node_sync": "active"}

        # 2. Lógica Original Nexus (Monitoramento de Usuário)
        db.reference(f'logs/nexus/{uid}').push({"report": data, "received_at": datetime.now().isoformat()})
        db.reference('agent_data/incoming').push({"agent_id": "nexus_cinecash", "type": "telemetry", "payload": data, "received_at": datetime.now().isoformat()})

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

        # Check for Gemini key even if Groq is primary
        gemini_config = db.reference('config').get() or {}
        gemini_key_available = bool(os.environ.get("GEMINI_API_KEY") or str(gemini_config.get('geminiKey', '')).strip())

        # Check if Ollama is running
        ollama_online = False
        try:
            oresp = requests.get(OLLAMA_URL.replace("/api/generate", "/api/tags"), timeout=3)
            ollama_online = oresp.status_code == 200
        except:
            pass

        # Check GPT Maker
        gptmaker_token = _get_gptmaker_token()
        gptmaker_available = bool(gptmaker_token)

        return {
            "status": "online",
            "engine": "Groq/Gemini Hybrid",
            "motor_ativo": motor_ativo,
            "independente_de_api_paga": GROQ_AVAILABLE,
            "ambiente": "Produção" if HUB_MODE == "ADMIN" else "Desenvolvimento",
            "motores": {
                "groq": {"ativo": GROQ_AVAILABLE},
                "gemini": {"ativo": gemini_key_available},
                "ollama": {"ativo": ollama_online},
                "gptmaker": {"ativo": gptmaker_available}
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

from core.agent_manager import AgentManager

# Inicializa o AgentManager Global
agent_manager = AgentManager()

@app.post("/api/ai/chat")
async def ai_chat_specialized(data: dict = Body(...)):
    prompt = data.get("prompt", "")
    agent = data.get("agent", "ORCHESTRATOR")
    uid = data.get("uid", "admin_master")

    # Primeiro, tentamos o AgentManager se o agente não for o ORCHESTRATOR
    if agent != "ORCHESTRATOR":
        res = agent_manager.execute({"agent": agent.lower() + "_core" if "core" not in agent.lower() else agent.lower(), "prompt": prompt, "id": uid})
        if res.get("status") == "success":
            return {"answer": res.get("answer"), "agent": agent}

    answer = await ask_ai_specialized(agent, prompt, uid)
    return {"answer": answer, "agent": agent}

# --- GPT MAKER API ENDPOINTS ---
@app.get("/api/ai/gptmaker/workspaces")
async def gptmaker_workspaces():
    return gptmaker_list_workspaces()

@app.get("/api/ai/gptmaker/agents/{workspace_id}")
async def gptmaker_agents(workspace_id: str):
    return gptmaker_list_agents(workspace_id)

@app.post("/api/ai/gptmaker/chat")
async def gptmaker_chat(data: dict = Body(...)):
    agent_id = data.get("agent_id", "")
    prompt = data.get("prompt", "")
    context_id = data.get("context_id", "cybercore_studio")
    if not agent_id or not prompt:
        return {"status": "error", "msg": "agent_id e prompt são obrigatórios."}
    return gptmaker_conversation(agent_id, prompt, context_id)

@app.post("/ai/chat")
async def ai_chat(data: dict = Body(...)):
    prompt = data.get("prompt", "")
    uid = data.get("uid", "admin_master")
    answer = await ask_ai(prompt, uid)
    return {"answer": answer}

# --- SENTINEL LOGS ---
@app.get("/api/sentinel/logs")
async def sentinel_logs():
    try:
        # Pega os últimos 20 logs reais do Firebase
        logs = db.reference('logs').order_by_key().limit_to_last(20).get() or {}
        log_list = []
        for lid, ldata in logs.items():
            if isinstance(ldata, dict):
                log_list.append({
                    "id": lid,
                    "time": ldata.get("timestamp", datetime.now().isoformat()),
                    "msg": ldata.get("message", "Sem descrição"),
                    "level": ldata.get("level", "INFO")
                })
        return {"logs": log_list[::-1]}
    except Exception as e:
        return {"logs": [{"time": "-", "msg": f"Erro Sentinel: {str(e)}", "level": "ERROR"}]}

@app.post("/api/sentinel/log")
async def add_sentinel_log(data: dict = Body(...)):
    msg = data.get("message")
    level = data.get("level", "INFO")
    if not msg: return {"status": "error"}
    db.reference('logs').push({
        "message": msg,
        "level": level,
        "timestamp": datetime.now().strftime('%H:%M:%S')
    })
    return {"status": "success"}

# --- CYBERCORE ORCHESTRATION & BRIDGE ---

@app.post("/api/cybercore/orchestrate")
async def cybercore_orchestrate(data: dict = Body(...)):
    """Orquestrador Central: Recebe comandos estratégicos e delega para agentes especializados."""
    prompt = data.get("prompt", "")
    uid = data.get("uid", "admin_master")

    # 1. Registro na Memória de Logs
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event": "orchestration_start",
        "prompt": prompt,
        "uid": uid
    }
    try:
        log_path = os.path.join(PROJECT_ROOT, "memory", "logs", f"log_{datetime.now().strftime('%Y%m%d')}.json")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except: pass

    # 2. Chamada para a "Mente" (GPT Maker ou Pipeline Local)
    # Aqui simulamos a inteligência que quebra o problema em tarefas para os agentes.
    plan_prompt = f"""Atue como CEO Digital da CyberCore IA.
Analise o pedido estratégico: "{prompt}"
Crie um plano de execução técnico detalhado.
Responda em formato JSON:
{{
  "project": "Nome do Projeto",
  "analysis": "Breve análise estratégica",
  "tasks": [
    {{ "agent": "DESIGNER", "task": "Descrição da tarefa UI/UX" }},
    {{ "agent": "BUILDER", "task": "Descrição da tarefa de construção" }},
    {{ "agent": "FULLSTACK", "task": "Descrição da tarefa de integração/API" }}
  ]
}}
Retorne APENAS o JSON."""

    plan_raw = await ask_ai_specialized("ORCHESTRATOR", plan_prompt, uid)

    try:
        # Tenta extrair e limpar o JSON da resposta
        json_start = plan_raw.find('{')
        json_end = plan_raw.rfind('}') + 1
        plan = json.loads(plan_raw[json_start:json_end])

        # 3. Distribuição Automática (Execução em Background ou Sequencial)
        execution_results = []
        for task in plan.get("tasks", []):
            agent = task.get("agent")
            task_desc = task.get("task")
            # Executa o agente especializado
            res = await execute_single_agent(agent, f"Executor da tarefa: {task_desc}. Contexto do Projeto: {plan.get('project')}", uid)
            execution_results.append({ "agent": agent, "status": "completed", "output": res[:100] + "..." })

        # 4. Salva o projeto na Memória
        project_name = plan.get("project", "Novo Projeto").lower().replace(" ", "_")
        project_memory_path = os.path.join(PROJECT_ROOT, "memory", "projects", f"{project_name}.json")
        with open(project_memory_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": plan.get("project"),
                "created_at": datetime.now().isoformat(),
                "original_prompt": prompt,
                "plan": plan,
                "results": execution_results
            }, f, indent=4)

        return {
            "status": "success",
            "answer": f"🔮 **Plano '{plan.get('project')}' Ativado!**\n\n{plan.get('analysis')}\n\n**Execução:**\n" +
                      "\n".join([f"✅ {r['agent']}: {r['output']}" for r in execution_results]),
            "plan": plan
        }
    except Exception as e:
        return {
            "status": "error",
            "answer": f"Falha na orquestração: {str(e)}\n\nResposta bruta da IA:\n{plan_raw}",
            "raw": plan_raw
        }

@app.get("/api/cybercore/memory/stats")
async def get_memory_stats():
    """Retorna estatísticas da estrutura de memória."""
    try:
        projects_dir = os.path.join(PROJECT_ROOT, "memory", "projects")
        projects = os.listdir(projects_dir) if os.path.exists(projects_dir) else []
        return {
            "projects_count": len(projects),
            "last_project": projects[-1].replace('.json', '') if projects else None,
            "memory_status": "synced"
        }
    except:
        return {"projects_count": 0, "memory_status": "error"}

@app.get("/api/cybercore/memory/list/{category}")
async def list_memory_items(category: str):
    """Lista itens de uma categoria específica da memória."""
    valid_categories = ["projects", "agents", "architecture", "logs"]
    if category not in valid_categories:
        return {"items": []}

    path = os.path.join(PROJECT_ROOT, "memory", category)
    if not os.path.exists(path):
        return {"items": []}

    items = os.listdir(path)
    return {"items": [i.replace('.json', '') for i in items if i.endswith('.json') or i.endswith('.log')]}

@app.get("/api/cybercore/memory/read/{category}/{name}")
async def read_memory_item(category: str, name: str):
    """Lê o conteúdo de um item da memória."""
    path = os.path.join(PROJECT_ROOT, "memory", category, f"{name}.json")
    if not os.path.exists(path):
        path = os.path.join(PROJECT_ROOT, "memory", category, f"{name}.log")
        if not os.path.exists(path):
            return {"content": "Arquivo não encontrado."}

    with open(path, "r", encoding="utf-8") as f:
        return {"content": f.read()}

@app.post("/api/node/register")
async def register_node(data: dict = Body(...)):
    try:
        name = data.get("name", "Novo Nó")
        ptype = data.get("type", "local")
        identifier = data.get("identifier", "localhost")

        node_id = f"node_{int(time.time())}"
        node_data = {
            "name": name,
            "type": ptype,
            "identifier": identifier,
            "connected_at": datetime.now().isoformat(),
            "health": {"status": "online", "last_checked": datetime.now().isoformat()}
        }
        db.reference(f'neural/nodes/{node_id}').set(node_data)

        # Log no Sentinel
        db.reference('logs').push({
            "message": f"Novo nó registrado: {name} ({ptype})",
            "level": "INFO",
            "timestamp": datetime.now().strftime('%H:%M:%S')
        })

        return {"status": "success", "node_id": node_id}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/api/node/heartbeat/{node_id}")
async def node_heartbeat(node_id: str, data: dict = Body(...)):
    try:
        stats = data.get("stats", {})
        db.reference(f'neural/nodes/{node_id}/health').update({
            "status": "online",
            "last_checked": datetime.now().isoformat(),
            "stats": stats
        })
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

# --- STUDIO WORKSPACE API ---

@app.get("/api/studio/projects")
async def studio_list_projects():
    """Lista todos os projetos (pastas) no workspace."""
    try:
        projects = [d for d in os.listdir(WORKSPACE_DIR) if os.path.isdir(os.path.join(WORKSPACE_DIR, d))]
        return {"status": "success", "projects": sorted(projects) or ["default"]}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/api/studio/projects")
async def studio_create_project(data: dict = Body(...)):
    """Cria um novo projeto."""
    name = data.get("name", "").strip()
    if not name:
        return {"status": "error", "msg": "Nome do projeto obrigatório"}
    name = name.replace(" ", "_").lower()
    try:
        path = get_project_workspace(name)
        return {"status": "success", "project": name, "path": path}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/api/studio/files")
async def studio_files(project: str = Query("default")):
    try:
        pdir = get_project_workspace(project)
        files = os.listdir(pdir)
        file_details = []
        for f in files:
            path = os.path.join(pdir, f)
            stat = os.stat(path)
            file_details.append({
                "name": f,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "ext": f.split('.')[-1] if '.' in f else 'txt'
            })
        return {"status": "success", "files": file_details, "project": project}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/api/studio/context")
async def studio_context(project: str = Query("default")):
    """Retorna o conteudo completo do workspace como contexto para a IA."""
    try:
        pdir = get_project_workspace(project)
        files = os.listdir(pdir)
        context_parts = []
        for f in sorted(files):
            if f.startswith('.'): continue
            path = os.path.join(pdir, f)
            if not os.path.isfile(path): continue
            ext = os.path.splitext(f)[1].lower()
            if ext in ('.png','.jpg','.jpeg','.gif','.ico','.apk'): continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                context_parts.append(f"=== {f} ===\n{content}")
            except:
                pass
        return {"status": "success", "context": "\n\n".join(context_parts), "files": [f for f in sorted(files) if not f.startswith('.')], "project": project}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/api/studio/orchestrate")
async def studio_orchestrate(data: dict = Body(...)):
    """Orquestrador: analisa o projeto existente + prompt, decide agentes, executa pipeline."""
    prompt = data.get("prompt", "")
    uid = data.get("uid", "admin_studio")
    project = data.get("project", "default")
    if not prompt:
        return {"status": "error", "msg": "Prompt obrigatório"}

    # Pega contexto do workspace do projeto
    ctx_resp = await studio_context(project)
    workspace_context = ctx_resp.get("context", "") if ctx_resp.get("status") == "success" else ""
    existing_files = ctx_resp.get("files", [])

    # Monta prompt para o Orchestrator com contexto
    orchestrator_prompt = f"""CONTEXTO DO PROJETO ATUAL:
Arquivos existentes: {', '.join(existing_files) if existing_files else 'Nenhum'}

{workspace_context[:3000] if workspace_context else ''}

SOLICITAÇÃO DO USUÁRIO: {prompt}

Com base no contexto acima, determine a sequência de especialistas CyberCore necessários.
Responda APENAS uma lista separada por vírgula em ordem de execução.
Opções: BUILDER, PYTHON, JAVA, FULLSTACK, DESIGNER, SECURITY, AUDITOR, SOFTWARE.
Se o projeto não tiver arquivos, use os agentes padrão: BUILDER, DESIGNER, FULLSTACK.

Exemplo: DESIGNER, BUILDER, FULLSTACK"""

    plan_raw = await ask_ai(orchestrator_prompt, uid="system_orchestrator")
    agents_sequence = []
    if plan_raw:
        agents_sequence = [a.strip().upper() for a in plan_raw.split(",") if a.strip().upper() in AGENT_MODELS]
    if not agents_sequence:
        agents_sequence = ["BUILDER", "DESIGNER", "FULLSTACK"]

    # Prepara o prompt final com contexto completo
    full_context_prompt = f"""CONTEXTO DO PROJETO ATUAL:
{workspace_context[:5000] if workspace_context else 'Projeto novo, sem arquivos ainda.'}

OBJETIVO: {prompt}

INSTRUÇÕES:
- Leia TODO o contexto acima antes de responder.
- Se o projeto já tem arquivos, analise-os e faça alterações ou acréscimos conforme solicitado.
- Se for um projeto novo, crie a estrutura completa do zero.
- Mantenha consistência com o que já existe.
- Para código: gere {', '.join(agents_sequence)} atuando como uma equipe unificada.
- IMPORTANTE: Responda APENAS JSON bruto {{"nome_arquivo": "conteudo"}} sem markdown."""

    # Executa o pipeline com contexto acumulado
    execution_results = []
    current_context = full_context_prompt
    for i, agent in enumerate(agents_sequence):
        try:
            step_prompt = current_context if i == 0 else f"{current_context}\n\nProgresso:\n{execution_results[-1]['output'][:2000]}"
            check_credits(agent) and deduct_credit(agent) if check_credits(agent) else None
            output = await execute_single_agent(agent, step_prompt, uid)
            # Tenta extrair e salvar arquivos do JSON na resposta do agente
            try:
                json_str = output
                if "```json" in output:
                    json_str = output.split("```json")[1].split("```")[0]
                elif "```" in output:
                    json_str = output.split("```")[0]
                parsed = json.loads(json_str.strip())
                if isinstance(parsed, dict) and len(parsed) > 0:
                    saved = []
                    for fn, fc in parsed.items():
                        tool_write_studio_file(fn, fc, project)
                        saved.append(fn)
                    output = f"Arquivos salvos: {', '.join(saved)}"
            except:
                pass
            execution_results.append({"agent": agent, "output": output[:3000] if output else "Sem resposta"})
        except Exception as e:
            execution_results.append({"agent": agent, "output": f"Erro: {str(e)}"})

    return {
        "status": "success",
        "plan": agents_sequence,
        "results": execution_results,
        "context": existing_files,
        "project": project,
        "answer": f"🔮 **Pipeline CyberCore Ativado:** {' → '.join(agents_sequence)}\n\n" +
                  "\n\n".join([f"### Passo {i+1}: {r['agent']}\n{r['output']}" for i, r in enumerate(execution_results)])
    }

@app.get("/api/studio/read-file/{filename}")
async def studio_read_file(filename: str, project: str = Query("default")):
    try:
        filename = os.path.basename(filename)
        path = os.path.join(get_project_workspace(project), filename)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        with open(path, "r", encoding="utf-8") as f:
            return {"status": "success", "content": f.read(), "project": project}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/api/studio/save-file")
async def studio_save_file(data: dict = Body(...)):
    filename = data.get("filename")
    content = data.get("content")
    project = data.get("project", "default")
    if not filename or content is None:
        return {"status": "error", "msg": "Nome e conteúdo são obrigatórios"}

    result = tool_write_studio_file(filename, content, project)
    if "sucesso" in result:
        return {"status": "success", "msg": result, "project": project}
    return {"status": "error", "msg": result}

@app.delete("/api/studio/delete-file/{filename}")
async def studio_delete_file(filename: str, project: str = Query("default")):
    try:
        filename = os.path.basename(filename)
        path = os.path.join(get_project_workspace(project), filename)
        if os.path.exists(path):
            os.remove(path)
            return {"status": "success", "msg": f"Arquivo {filename} removido do projeto {project}."}
        return {"status": "error", "msg": "Arquivo não encontrado."}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

# --- STUDIO PREVIEW ---
@app.get("/api/studio/preview/{filename:path}")
async def studio_preview_file(filename: str, project: str = Query("default")):
    """Serve workspace files for live preview."""
    try:
        safe = os.path.basename(filename) if '/' not in filename else filename
        pdir = get_project_workspace(project)
        path = os.path.join(pdir, safe)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        ext = os.path.splitext(path)[1].lower()
        media_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        return FileResponse(path, media_type=media_types.get(ext, "text/plain; charset=utf-8"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/studio/preview")
async def studio_preview_site(project: str = Query("default")):
    """Serve the complete workspace site as a preview page with iframe."""
    try:
        pdir = get_project_workspace(project)
        files = os.listdir(pdir)
        html = """<!DOCTYPE html><html lang="pt-br"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>CyberCore Studio - Preview</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif}
body{background:#0a0a0f;color:#fff;display:flex;flex-direction:column;height:100vh}
.toolbar{display:flex;align-items:center;gap:10px;padding:10px 16px;background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.06);flex-wrap:wrap}
.toolbar h3{font-size:12px;color:#e8b830;letter-spacing:1px;font-weight:800}
.toolbar a{color:#64748b;text-decoration:none;font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.06);transition:.2s}
.toolbar a:hover{color:#e8b830;border-color:rgba(232,184,48,0.3)}
.toolbar .active{color:#e8b830;border-color:rgba(232,184,48,0.3);background:rgba(232,184,48,0.06)}
iframe{flex:1;border:none;background:#fff;width:100%}
.empty{flex:1;display:flex;align-items:center;justify-content:center;color:#333;font-size:14px}
</style></head><body>
<div class="toolbar">
<h3>🖥️ CYBERCORE PREVIEW</h3>
"""
        has_html = False
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in ('.html','.htm'):
                has_html = True
                is_active = f == "index.html"
                cls = ' active' if is_active else ''
                html += f'<a href="/api/studio/preview/{f}?project={project}" target="preview" class="{cls}">🌐 {f}</a>'
            elif ext in ('.css','.js'):
                pass
        if not has_html:
            html += '<span style="color:#666;font-size:12px">Nenhum arquivo HTML no workspace</span>'
        html += '</div>'
        if has_html:
            html += f'<iframe name="preview" src="/api/studio/preview/index.html?project={project}"></iframe>'
        else:
            html += '<div class="empty">Nenhum arquivo HTML para exibir</div>'
        html += '</body></html>'
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f"<pre>Erro: {e}</pre>", status_code=500)

# --- PROJECT MANAGER & CREDIT SYSTEM ---

DESKTOP_DIR = os.path.expanduser("~/Desktop")

def get_agent_credits():
    """Get credit limits and usage from Firebase."""
    try:
        data = db.reference('config/agent_credits').get() or {}
        return {
            "BUILDER":  {"limit": data.get("BUILDER", {}).get("limit", 50), "used": data.get("BUILDER", {}).get("used", 0)},
            "DESIGNER": {"limit": data.get("DESIGNER", {}).get("limit", 50), "used": data.get("DESIGNER", {}).get("used", 0)},
            "FULLSTACK": {"limit": data.get("FULLSTACK", {}).get("limit", 50), "used": data.get("FULLSTACK", {}).get("used", 0)},
            "PYTHON":   {"limit": data.get("PYTHON", {}).get("limit", 50), "used": data.get("PYTHON", {}).get("used", 0)},
            "JAVA":     {"limit": data.get("JAVA", {}).get("limit", 50), "used": data.get("JAVA", {}).get("used", 0)},
            "SOFTWARE": {"limit": data.get("SOFTWARE", {}).get("limit", 50), "used": data.get("SOFTWARE", {}).get("used", 0)},
        }
    except:
        return {a: {"limit": 50, "used": 0} for a in ["BUILDER","DESIGNER","FULLSTACK","PYTHON","JAVA","SOFTWARE"]}

def deduct_credit(agent):
    """Deduct one credit for an agent usage."""
    try:
        ref = db.reference(f'config/agent_credits/{agent}')
        data = ref.get() or {"used": 0, "limit": 50}
        data["used"] = data.get("used", 0) + 1
        ref.set(data)
        return data["used"] <= data.get("limit", 50)
    except:
        return True

def check_credits(agent):
    """Check if agent has credits remaining."""
    data = get_agent_credits()
    a = data.get(agent, {"limit": 50, "used": 0})
    return a["used"] < a["limit"]

@app.get("/api/studio/credits")
async def studio_credits():
    return {"status": "success", "credits": get_agent_credits()}

@app.post("/api/studio/credits/set-limit")
async def studio_set_limit(data: dict = Body(...)):
    agent = data.get("agent", "")
    limit = data.get("limit", 50)
    if agent not in ["BUILDER","DESIGNER","FULLSTACK","PYTHON","JAVA","SOFTWARE"]:
        return {"status": "error", "msg": "Agente inválido"}
    try:
        ref = db.reference(f'config/agent_credits/{agent}')
        current = ref.get() or {"used": 0}
        current["limit"] = max(1, int(limit))
        ref.set(current)
        return {"status": "success", "msg": f"Limite do {agent} atualizado para {limit}"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

# --- DECIDE ENGINE: escolhe Groq ou Ollama com base na complexidade ---
def decide_engine(question):
    """Retorna 'groq' para perguntas complexas, 'ollama' para simples."""
    complex_keywords = [
        "criar", "gerar", "desenvolver", "arquitetura", "estrutura",
        "banco de dados", "api", "autenticação", "segurança",
        "como implementar", "melhor prática", "design pattern",
        "refatorar", "otimizar", "escalar", "deploy"
    ]
    q = question.lower()
    score = sum(1 for kw in complex_keywords if kw in q)
    return "groq" if score >= 2 else "ollama"

# Store PM conversation history in memory (per-session)
pm_sessions = {}

@app.post("/api/studio/project-manager/chat")
async def pm_chat(data: dict = Body(...)):
    session_id = data.get("session_id", "default")
    message = data.get("message", "")
    mode = data.get("mode", "auto")  # auto | groq | ollama

    if session_id not in pm_sessions:
        pm_sessions[session_id] = {
            "history": [],
            "project": {"name": "", "path": "", "type": "", "existing": False}
        }

    session = pm_sessions[session_id]

    # Decide engine
    engine = mode if mode != "auto" else decide_engine(message)

    system_prompt = """Você é o Project Manager da CyberCore IA, um assistente especializado em planejar projetos de software.

SUA FUNÇÃO:
- Faça perguntas objetivas e diretas sobre o projeto (nome, tipo, onde salvar)
- Dê sugestões e exemplos práticos
- Detecte se o usuário já tem um projeto iniciado
- NÃO gere código completo — apenas planos, sugestões e direcionamentos
- Quando o projeto estiver bem definido, avise que pode chamar os agentes especializados

REGRAS:
- Seja curto e objetivo (máx 3 parágrafos)
- Responda em português brasileiro
- Use tom amigável e didático
- Se o usuário mencionar um projeto existente, pergunte o caminho da pasta"""

    user_context = f"""Contexto atual do projeto:
- Nome: {session['project']['name'] or 'não definido'}
- Tipo: {session['project']['type'] or 'não definido'}
- Caminho: {session['project']['path'] or 'não definido'}
- Projeto existente: {'Sim' if session['project']['existing'] else 'Não'}

Últimas mensagens:
{chr(10).join([f"{m['role']}: {m['content'][:100]}" for m in session['history'][-6:]])}"""

    full_prompt = f"{system_prompt}\n\n{user_context}\n\nUsuário: {message}"

    try:
        if engine == "groq" and GROQ_AVAILABLE:
            answer = groq_generate(full_prompt, uid="pm_session")
            if not answer:
                answer = "Desculpe, não consegui processar sua solicitação no momento."
        else:
            # Ollama (mais leve)
            resp = requests.post(OLLAMA_URL, json={
                "model": "deepseek-coder:latest",
                "prompt": full_prompt,
                "stream": False
            }, timeout=30)
            if resp.status_code == 200:
                answer = resp.json().get("response", "Sem resposta.")
            else:
                answer = "Não consegui processar. Vou usar o Groq como fallback."
                if GROQ_AVAILABLE:
                    answer = groq_generate(full_prompt, uid="pm_session") or answer
    except Exception as e:
        answer = f"Erro na comunicação: {str(e)}"

    # Save to history
    session["history"].append({"role": "user", "content": message})
    session["history"].append({"role": "assistant", "content": answer})
    if len(session["history"]) > 20:
        session["history"] = session["history"][-20:]

    return {
        "status": "success",
        "answer": answer,
        "engine": engine,
        "project": session["project"]
    }

@app.post("/api/studio/project-manager/update")
async def pm_update(data: dict = Body(...)):
    session_id = data.get("session_id", "default")
    updates = data.get("project", {})
    if session_id not in pm_sessions:
        pm_sessions[session_id] = {"history": [], "project": {"name": "", "path": "", "type": "", "existing": False}}
    pm_sessions[session_id]["project"].update(updates)
    return {"status": "success", "project": pm_sessions[session_id]["project"]}

@app.post("/api/studio/project-manager/dispatch")
async def pm_dispatch(data: dict = Body(...)):
    session_id = data.get("session_id", "default")
    agent = data.get("agent", "BUILDER")
    prompt = data.get("prompt", "")

    if not check_credits(agent):
        return {"status": "error", "msg": f"Agente {agent} sem créditos. Aumente o limite em Configurações."}

    try:
        resp = await execute_single_agent(agent, prompt, "admin_studio")
        deduct_credit(agent)
        return {"status": "success", "answer": resp, "agent": agent}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.get("/api/studio/detect")
async def studio_detect(path: str = ""):
    """Detecta projetos existentes no Desktop ou em path específico."""
    try:
        base = path if path else DESKTOP_DIR
        if not os.path.exists(base):
            return {"status": "error", "msg": "Caminho não encontrado"}
        items = []
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if os.path.isdir(full):
                # Detecta se parece um projeto
                has_files = any(os.path.isfile(os.path.join(full, f)) for f in os.listdir(full)[:50])
                if has_files:
                    items.append({
                        "name": entry,
                        "path": full,
                        "type": detect_project_type(full)
                    })
        return {"status": "success", "projects": items, "base": base}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def detect_project_type(folder):
    """Tenta detectar o tipo de projeto."""
    files = os.listdir(folder)
    if any(f.endswith('.html') for f in files): return "website"
    if any(f.endswith('.py') for f in files): return "python"
    if any(f.endswith('.java') or f.endswith('.apk') for f in files): return "android"
    if any(f.endswith('.js') or f.endswith('.ts') for f in files): return "website"
    return "unknown"

@app.get("/api/studio/detect/check-path")
async def studio_check_path(path: str = ""):
    """Verifica se um caminho existe."""
    return {"exists": os.path.exists(path), "path": path}

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
        new_balance = current_balance + 0.20

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

        # Sistema de Indicação: Ao atingir 25 anúncios, o padrinho ganha R$ 0,20 + bônus a cada 5 indicados
        if new_videos == 25:
            sponsor_uid = user_data.get('referredBy')
            if sponsor_uid:
                sponsor_ref = db.reference(f'users/{sponsor_uid}')
                sponsor_data = sponsor_ref.get()
                if sponsor_data:
                    current_valid = int(sponsor_data.get('validReferrals', 0))
                    new_valid = current_valid + 1
                    sponsor_balance = float(sponsor_data.get('balance', 0))
                    current_bonus = float(sponsor_data.get('referralBonus', 0))

                    # Bônus base de R$ 0,20 por indicado
                    bonus_amount = 0.20
                    extra_bonus = 0

                    # Bônus extra de R$ 1,00 a cada 5 indicados
                    if new_valid % 5 == 0:
                        extra_bonus = 1.00

                    total_bonus = bonus_amount + extra_bonus

                    sponsor_ref.update({
                        "validReferrals": new_valid,
                        "balance": sponsor_balance + total_bonus,
                        "referralBonus": current_bonus + total_bonus
                    })

                    # Log da bonificação
                    log_data = {
                        "sponsor": sponsor_uid,
                        "referral": uid,
                        "action": "BONUS_CONVERTED",
                        "bonus": bonus_amount,
                        "extra_bonus": extra_bonus,
                        "total_bonus": total_bonus,
                        "timestamp": {".sv": "timestamp"}
                    }
                    db.reference('logs/referrals').push(log_data)

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
        if amount > 50.0:
            return {"status": "error", "message": "Valor máximo por saque é R$ 50,00"}

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
