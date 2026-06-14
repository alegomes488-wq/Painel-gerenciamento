import os
import sys
import json
import random
import asyncio
import requests
import psutil
from datetime import datetime
from contextlib import asynccontextmanager

import firebase_admin
from firebase_admin import credentials, db, messaging
from fastapi import FastAPI, Body, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

# --- CONFIGURA├ç├âO DE AMBIENTE ---
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Detecta caminhos para montagem de arquivos est├íticos
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
ADMIN_PATH = os.path.join(PROJECT_ROOT, "admin")
WWW_PATH = os.path.join(PROJECT_ROOT, "www")

# --- FIREBASE ---
cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if cred_json:
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
    print("[OK] Firebase iniciado via Vari├ível de Ambiente")
else:
    cred_path = os.path.join(BACKEND_DIR, "firebase-adminsdk.json")
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
        print("[OK] Firebase iniciado via arquivo JSON local")
    else:
        print("[AVISO] Credenciais Firebase nao encontradas! O sistema operara em modo degradado.")

# --- UTILIT├üRIOS ---

def tool_sentinel_enforcement():
    """
    Executa uma varredura de seguran├ºa imediata em todos os usu├írios.
    Utilizado pelo loop Sentinel e para testes de estresse.
    """
    try:
        users_data = db.reference('users').get() or {}
        config_data = db.reference('config').get() or {}
        block_vpn = config_data.get('blockVPN', False)
        block_root = config_data.get('blockRoot', False)
        auto_ban = config_data.get('autoBan', False)

        ban_count = 0
        action_count = 0

        for uid, u in users_data.items():
            if not isinstance(u, dict): continue
            risk = u.get('risk_score', 0)
            status_u = u.get('status', '')

            if status_u == 'banido': continue

            # 1. Risco Cr├¡tico (>100 ou autoBan ativo com risco alto)
            if risk >= 100:
                db.reference(f'users/{uid}').update({
                    "status": "banido",
                    "ban_reason": "Sentinel: Risco Cr├¡tico Detectado (>100)"
                })
                ban_count += 1
                continue

            # 2. VPN/Proxy
            if block_vpn:
                if u.get('vpnDetected') or u.get('proxyDetected'):
                    action_id = f"vpn_{uid}"
                    if not db.reference(f'security/pending_actions/{action_id}').get():
                        db.reference(f'security/pending_actions/{action_id}').set({
                            "type": "vpn_proxy", "uid": uid, "email": u.get('email', uid),
                            "risk_score": risk, "detected_at": datetime.now().isoformat(),
                            "status": "pending", "evidence": "Conex├úo via Proxy/VPN"
                        })
                        action_count += 1

            # 3. Root/Jailbreak
            if block_root:
                if u.get('rootDetected') or u.get('jailbreakDetected'):
                    action_id = f"root_{uid}"
                    if not db.reference(f'security/pending_actions/{action_id}').get():
                        db.reference(f'security/pending_actions/{action_id}').set({
                            "type": "root_jailbreak", "uid": uid, "email": u.get('email', uid),
                            "risk_score": risk, "detected_at": datetime.now().isoformat(),
                            "status": "pending", "evidence": "Dispositivo modificado (Root)"
                        })
                        action_count += 1

        return {"status": "success", "bans": ban_count, "actions": action_count}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

async def auto_approve_withdrawals(force=False):
    """
    Processa saques pendentes baseado no ROI e seguran├ºa CyberCore.
    """
    try:
        config = db.reference('config').get() or {}
        api_key = config.get('asaasKey') or config.get('asaas_key') or os.environ.get('ASAAS_API_KEY', '')
        if not api_key: return "ASAAS_API_KEY n├úo configurada"

        # C├ílculo de ROI para seguran├ºa financeira
        health = tool_analyze_health()
        roi = ((health['revenue_brl'] - health['total_debt']) / health['revenue_brl'] * 100) if health['revenue_brl'] > 0 else 0

        if not force and roi < 25:
            return f"ROI {roi:.1f}% insuficiente para auto-pagamento (Min: 25%)"

        approved = 0
        all_withdrawals = db.reference('withdrawals').get() or {}

        for uid, ws in all_withdrawals.items():
            if not isinstance(ws, dict): continue
            for wid, w in ws.items():
                if w.get('status') == 'pending':
                    amount = float(w.get('amount', 0))
                    # Limite de seguran├ºa para pagamentos autom├íticos (exceto se for├ºado)
                    if not force and amount > 10.0: continue

                    # Chamada interna para a rota de aprova├º├úo que j├í cont├®m a l├│gica de limpeza de PIX
                    res = await approve_payment(wid)
                    if res.get('status') == 'success':
                        approved += 1

        return f"Processamento conclu├¡do. Aprovados: {approved} | ROI: {roi:.1f}%"
    except Exception as e:
        return f"Erro no auto-approve: {str(e)}"

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
        status = "SAUD├üVEL" if revenue_brl > (total_debt * 1.5) else "CR├ìTICO"
        return {
            "revenue_brl": round(revenue_brl, 2),
            "total_debt": round(total_debt, 2),
            "net_profit_brl": round(revenue_brl - total_debt, 2),
            "roi_status": status,
            "health_status": status,
            "dollar_rate": dollar,
            "active_users": len(users)
        }
    except: return {"revenue_brl": 0, "total_debt": 0, "health_status": "OFFLINE"}

# --- SENTINEL 2.0 & OADA CYCLE ---

async def sentinel_audit_loop():
    cycle_count = 0
    while True:
        try:
            cycle_count += 1

            # Pulso do sistema (escrita ├║nica por ciclo)
            pulse_data = {"python_core_pulse": {".sv": "timestamp"}, "auditor_last_pulse": {".sv": "timestamp"}}

            # Sincroniza├º├úo Monetag/Financeira ÔÇö carrega users + config uma ├║nica vez
            users_data = db.reference('users').get() or {}
            config_data = db.reference('config').get() or {}

            total_debt = sum([float(u.get('balance', 0)) for u in users_data.values() if isinstance(u, dict)])
            hits = config_data.get('stats', {}).get('hits', 0)
            cpm = config_data.get('cpm', 0.18)
            dollar = get_dollar_rate()
            revenue_brl = (hits / 1000) * cpm * dollar
            status_label = "SAUD├üVEL" if revenue_brl > (total_debt * 1.5) else "CR├ìTICO"

            pulse_data['financial_realtime'] = {
                "brl": round(revenue_brl, 2),
                "rate": dollar,
                "last_update": datetime.now().strftime('%H:%M:%S')
            }

            # Varredura de fraudes (mesmo users_data j├í carregado)
            ban_updates = {}
            pending_actions = {}
            config_data = db.reference('config').get() or {}
            block_vpn = config_data.get('blockVPN', False)
            block_root = config_data.get('blockRoot', False)

            for uid, u in users_data.items():
                if not isinstance(u, dict): continue
                risk = u.get('risk_score', 0)
                status_u = u.get('status', '')

                # Risco cr├¡tico: auto-ban imediato (n├úo precisa autoriza├º├úo)
                if risk >= 100 and status_u != 'banido':
                    ban_updates[uid] = {
                        "status": "banido",
                        "ban_reason": "Sentinel: Risco Cr├¡tico Detectado"
                    }
                    continue

                # VPN/Proxy detectado - cria a├º├úo pendente se flag ligado
                if block_vpn and status_u != 'banido':
                    vpn_flag = u.get('vpnDetected') or u.get('proxyDetected') or False
                    if vpn_flag:
                        action_id = f"vpn_{uid}"
                        if not db.reference(f'security/pending_actions/{action_id}').get():
                            pending_actions[action_id] = {
                                "type": "vpn_proxy",
                                "uid": uid,
                                "email": u.get('email', uid),
                                "risk_score": risk,
                                "detected_at": datetime.now().isoformat(),
                                "status": "pending",
                                "evidence": "Conex├úo via Proxy/VPN detectada"
                            }

                # Root/Jailbreak detectado - cria a├º├úo pendente se flag ligado
                if block_root and status_u != 'banido':
                    root_flag = u.get('rootDetected') or u.get('jailbreakDetected') or False
                    if root_flag:
                        action_id = f"root_{uid}"
                        if not db.reference(f'security/pending_actions/{action_id}').get():
                            pending_actions[action_id] = {
                                "type": "root_jailbreak",
                                "uid": uid,
                                "email": u.get('email', uid),
                                "risk_score": risk,
                                "detected_at": datetime.now().isoformat(),
                                "status": "pending",
                                "evidence": "Dispositivo modificado (Root/Jailbreak)"
                            }

            device_lock = config_data.get('deviceLock', False)
            device_id_security = config_data.get('deviceIdSecurity', False)

            if device_lock or device_id_security:
                device_map = {}
                for uid, u in users_data.items():
                    if not isinstance(u, dict): continue
                    did = u.get('deviceId') or u.get('uniqueDeviceId')
                    if did and u.get('status') != 'banido':
                        device_map.setdefault(did, []).append(uid)

                for did, uids in device_map.items():
                    if len(uids) > 1:
                        print(f"[SENTINEL] ID Unico duplicado: device={did[:16]}... usuarios={uids}")
                        db.reference('logs/sentinel_alerts').push({
                            "type": "device_clone", "deviceId": did, "users": uids,
                            "timestamp": datetime.now().isoformat()
                        })
                        # Cria a├º├úo pendente para cada duplicata (exceto o primeiro)
                        for uid in uids[1:]:
                            action_id = f"clone_{did[:8]}_{uid[:8]}"
                            if not db.reference(f'security/pending_actions/{action_id}').get():
                                u = users_data.get(uid, {})
                                pending_actions[action_id] = {
                                    "type": "device_clone",
                                    "uid": uid,
                                    "email": u.get('email', uid) if isinstance(u, dict) else uid,
                                    "deviceId": did,
                                    "risk_score": u.get('risk_score', 0) if isinstance(u, dict) else 0,
                                    "detected_at": datetime.now().isoformat(),
                                    "status": "pending",
                                    "evidence": f"M├║ltiplas contas no mesmo dispositivo ({len(uids)} contas)"
                                }

            # Persiste a├º├Áes pendentes
            for action_id, action_data in pending_actions.items():
                db.reference(f'security/pending_actions/{action_id}').set(action_data)

            for uid, updates in ban_updates.items():
                db.reference(f'users/{uid}').update(updates)

            # Grava pulso + financeiro em um update s├│
            db.reference('status').update(pulse_data)

            # Atividade Global (a cada 3 ciclos ~90s)
            if cycle_count % 3 == 0:
                active = len([u for u in users_data.values() if isinstance(u, dict) and u.get('status') != 'banido'])
                db.reference('logs/activity').push({
                    "user": "SISTEMA",
                    "action": f"Pulso do sistema ÔÇö {active} usu├írios ativos | D├¡vida: R${total_debt:.2f} | Revenue: R${revenue_brl:.2f}",
                    "timestamp": {".sv": "timestamp"}
                })

            # --- N├ÜCLEO NEURAL: an├ílise a cada 5 ciclos (5 min) ---
            if cycle_count % 5 == 0 or cycle_count == 1:
                try:
                    insights = {}
                    aggr = db.reference('agent_data/aggregated').get() or {}

                    total_hits = aggr.get('total_hits', 0)
                    total_conversions = aggr.get('total_conversions', 0)
                    total_revenue = aggr.get('total_revenue', 0)

                    if total_hits > 0:
                        insights['agent_ctr'] = round((total_conversions / total_hits) * 100, 2)
                        insights['total_hits'] = total_hits
                        insights['total_conversions'] = total_conversions
                        insights['total_revenue'] = round(total_revenue, 2)
                        insights['rpm'] = round((total_revenue / total_hits) * 1000, 4)
                        pages = aggr.get('pages', {})
                        if pages: insights['top_page'] = max(pages, key=pages.get)
                        sources = aggr.get('sources', {})
                        if sources: insights['top_source'] = max(sources, key=sources.get)

                    # Score r├ípido: usu├írios + hits
                    total_users = len([u for u in users_data.values() if isinstance(u, dict)])
                    learning_score = min(100, int(
                        total_users * 5 +
                        total_hits * 0.5 +
                        total_conversions * 5 +
                        total_revenue * 2
                    ))
                    insights['learning_score'] = learning_score

                    # --- ROI POR CANAL (a partir das fontes dos agentes) ---
                    sources = aggr.get('sources', {})
                    channel_map = {
                        'afiliados': ['facebook', 'instagram', 'whatsapp', 'telegram'],
                        'ads': ['google', 'monetag', 'taboola', 'outbrain'],
                        'organico': ['direct', 'organic', 'bing', 'yahoo']
                    }
                    channels_data = aggr.get('channels', {})
                    for ch, src_list in channel_map.items():
                        ch_hits = sum(sources.get(s, 0) for s in src_list)
                        ch_conv = channels_data.get(ch, {}).get('conversions', 0) if channels_data else 0
                        ch_rev = channels_data.get(ch, {}).get('revenue', 0) if channels_data else 0
                        insights[f'ch_{ch}_hits'] = ch_hits
                        insights[f'ch_{ch}_conv'] = ch_conv
                        insights[f'ch_{ch}_rev'] = round(ch_rev, 2)
                        if ch_hits > 0:
                            insights[f'ch_{ch}_roi'] = round((ch_conv / ch_hits) * 100, 1)
                        else:
                            insights[f'ch_{ch}_roi'] = 0

                    insights['last_updated'] = datetime.now().isoformat()
                    db.reference('neural/insights').update(insights)
                    db.reference('neural/preferences_count').set(learning_score)
                    print(f"[NEURAL] Score: {learning_score} | Hits: {total_hits} | CTR: {insights.get('agent_ctr', 0)}%")
                except Exception as neural_err:
                    print(f"[NEURAL] Erro: {neural_err}")

            # --- NEXUS: an├ílise de telemetria a cada ciclo ---
            try:
                nexus_insights = db.reference('nexus/insights').get() or {}
                total_nexus = len(nexus_insights)
                active_nexus = sum(1 for v in nexus_insights.values()
                                   if isinstance(v, dict) and v.get('engagement') == 'alto')
                suspicious = sum(1 for v in nexus_insights.values()
                                 if isinstance(v, dict) and v.get('financial_status') == 'suspeito')
                total_balance_nexus = sum(
                    float(v.get('balance', 0)) for v in nexus_insights.values() if isinstance(v, dict))

                # Alimenta o Neural com dados do Nexus
                db.reference('neural/insights').update({
                    "nexus_total_users": total_nexus,
                    "nexus_active_users": active_nexus,
                    "nexus_suspicious": suspicious,
                    "nexus_total_balance": round(total_balance_nexus, 2),
                    "nexus_last_scan": datetime.now().isoformat()
                })

                # Gera a├º├úo consolidada para o frontend se houver suspeitos
                if suspicious > 0:
                    action_id = f"nexus_sweep_{cycle_count}"
                    existing = db.reference(f'nexus/actions/{action_id}').get()
                    if not existing:
                        db.reference('nexus/actions').child(action_id).set({
                            "to": "cybercore", "level": "info",
                            "msg": f"NEXUS: Varredura conclu├¡da ÔÇö {suspicious} usu├írio(s) suspeito(s) entre {total_nexus} monitorados. Saldo total: R${total_balance_nexus:.2f}",
                            "timestamp": datetime.now().isoformat(),
                            "type": "sweep"
                        })
            except Exception as nexus_err:
                print(f"[NEXUS] Erro na an├ílise: {nexus_err}")

            # --- AUDITOR: Processamento Financeiro (a cada 2 ciclos ~60s) ---
            if cycle_count % 2 == 0:
                try:
                    auditor_res = await auto_approve_withdrawals()
                    print(f"[AUDITOR] {auditor_res}")
                except Exception as auditor_err:
                    print(f"[AUDITOR] Erro: {auditor_err}")

            print(f"[SENTINEL] Ciclo {cycle_count} - Saude: {status_label}")
        except Exception as e:
            print(f"[ERRO] Sentinel: {e}")

        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[CYBERCORE] v3.2 Ativando Nucleo e Sentinel...")

    # Pr├®-popula n├║cleo neural no startup
    try:
        users_ref = db.reference('users').get() or {}
        total_users = len([u for u in users_ref.values() if isinstance(u, dict)])
        initial_score = min(100, total_users * 5)
        db.reference('neural/insights').update({
            "learning_score": initial_score,
            "active_users_count": total_users,
            "total_sessions": 0,
            "completion_rate": 0,
            "trending": "estavel",
            "peak_hour": "--:--",
            "peak_label": "aguardando",
            "total_hits": 0,
            "total_conversions": 0,
            "agent_ctr": 0,
            "rpm": 0,
            "ch_afiliados_hits": 0,
            "ch_afiliados_conv": 0,
            "ch_afiliados_rev": 0,
            "ch_afiliados_roi": 0,
            "ch_ads_hits": 0,
            "ch_ads_conv": 0,
            "ch_ads_rev": 0,
            "ch_ads_roi": 0,
            "ch_organico_hits": 0,
            "ch_organico_conv": 0,
            "ch_organico_rev": 0,
            "ch_organico_roi": 0,
            "last_updated": datetime.now().isoformat(),
            "status": "inicializando"
        })
        db.reference('neural/preferences_count').set(initial_score)
        print(f"[NEURAL] Score inicial: {initial_score} ({total_users} usuarios)")
    except Exception as e:
        print(f"[NEURAL] Erro no startup: {e}")

    audit_task = asyncio.create_task(sentinel_audit_loop())
    yield
    audit_task.cancel()

# --- APP FASTAPI ---

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- ROTAS API (RESTAURADAS) ---

@app.get("/health")
async def health_wake():
    return {"status": "awake", "service": "CyberCore IA"}

@app.get("/api/health")
def health():
    return {
        "status": "CyberCore IA v3.2 ONLINE",
        "system": "Sentinel 2.0",
        "admin_mounted": os.path.exists(ADMIN_PATH),
        "app_mounted": os.path.exists(WWW_PATH)
    }

@app.get("/api/news")
async def get_news():
    """Busca notícias recentes do Brasil via RSS"""
    import xml.etree.ElementTree as ET

    sources = [
        ("https://news.google.com/rss?hl=pt-BR&gl=BR&ceid=BR:pt-br", "Google News"),
        ("https://g1.globo.com/rss/g1/", "G1"),
        ("https://rss.uol.com.br/feed/noticias.xml", "UOL"),
    ]

    for url, name in sources:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            articles = []
            for item in root.iter("item"):
                title = (item.findtext("title") or "")
                link = (item.findtext("link") or "")
                desc = (item.findtext("description") or "")
                pub = (item.findtext("pubDate") or "")

                media = item.find(".//{http://search.yahoo.com/mrss/}content")
                img = media.get("url", "") if media is not None else ""

                articles.append({
                    "title": title,
                    "link": link,
                    "description": desc,
                    "pubDate": pub,
                    "image": img,
                    "source": name,
                })
            if articles:
                return {"status": "success", "articles": articles[:20]}
        except:
            continue
    return {"status": "error", "articles": [], "message": "Nenhuma fonte disponível"}

@app.get("/api/metrics")
async def api_metrics():
    try:
        cpu = round(psutil.cpu_percent(interval=0.1), 1)
        ram = round(psutil.virtual_memory().used / 1024 / 1024, 0)
    except:
        cpu = random.uniform(0.5, 8)
        ram = random.randint(80, 200)
    health = tool_analyze_health()
    return {
        "ping": f"{random.randint(5, 30)}ms",
        "ping_raw": random.randint(5, 30),
        "cpu_load": f"{cpu}%",
        "cpu_raw": cpu,
        "cache_mb": int(ram),
        "profit_usd": round(health['revenue_brl'] / health.get('dollar_rate', 5.25), 2),
        "profit_brl": health['revenue_brl'],
        "core_online": True,
        "production": db.reference('config/production').get() or False
    }

@app.post("/ai/chat")
async def ai_chat(data: dict = Body(...)):
    # Simula├º├úo r├ípida ou integra├º├úo real com Gemini se houver key
    prompt = data.get("prompt", "").lower()
    if "status" in prompt:
        health = tool_analyze_health()
        return {"answer": f"O sistema est├í {health['health_status']}. ROI atual projetado em {health['revenue_brl']} BRL."}
    return {"answer": "CyberCore IA processando... O n├║cleo est├í em modo de prontid├úo."}

@app.post("/payments/request/{uid}")
async def request_payment(uid: str, data: dict = Body(...)):
    try:
        amount = float(data.get("amount", 0))
        pix_key = data.get("pixKey", "")
        pix_type = data.get("pixType", "")
        fingerprint = data.get("fingerprint", {})

        if amount <= 0:
            raise HTTPException(status_code=400, detail="Valor de saque inv├ílido.")

        user_ref = db.reference(f'users/{uid}')
        user = user_ref.get()

        if not user:
            raise HTTPException(status_code=404, detail="Usu├írio n├úo localizado.")

        if user.get('status') == 'banido':
            raise HTTPException(status_code=403, detail="Conta bloqueada pelo Sentinel 2.0.")

        balance = float(user.get('balance', 0))
        if balance < amount:
            raise HTTPException(status_code=400, detail="Saldo insuficiente para esta opera├º├úo.")

        # Valida├º├úo de Seguran├ºa Sentinel
        risk_score = user.get('risk_score', 0)
        if risk_score > 85:
            raise HTTPException(status_code=403, detail="Saque retido para an├ílise de seguran├ºa neural.")

        # Gera ID ├║nico para o saque
        wid = f"WID_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}"

        withdrawal_entry = {
            "amount": amount,
            "pixKey": pix_key,
            "pixType": pix_type,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "fingerprint": fingerprint,
            "email": user.get('email', 'N/A'),
            "id": wid,
            "uid": uid
        }

        # Registra a solicita├º├úo
        db.reference(f'withdrawals/{uid}/{wid}').set(withdrawal_entry)

        # Deduz o saldo do usu├írio
        new_balance = round(balance - amount, 2)
        user_ref.update({"balance": new_balance})

        # Log financeiro
        db.reference(f'logs/financial/{uid}').push({
            "type": "withdrawal_requested",
            "amount": amount,
            "wid": wid,
            "timestamp": datetime.now().isoformat()
        })

        print(f"[FINANCEIRO] Novo pedido de saque: {uid} | R$ {amount}")
        return {"status": "success", "wid": wid, "new_balance": new_balance}

    except HTTPException as he: raise he
    except Exception as e:
        print(f"[ERRO] Falha ao processar saque: {e}")
        raise HTTPException(status_code=500, detail="Erro interno no processador de pagamentos.")

@app.post("/payments/approve/{wid}")
async def approve_payment(wid: str):
    try:
        config = db.reference('config').get() or {}
        api_key = config.get('asaasKey') or config.get('asaas_key') or os.environ.get('ASAAS_API_KEY', '')
        if not api_key: return {"status": "error", "msg": "Chave Asaas n├úo encontrada."}

        # Bloqueia saques se Ambiente de Produ├º├úo estiver desligado
        if not config.get('production', False):
            return {"status": "error", "msg": "Ambiente de Producao desativado. Saques bloqueados."}

        # Busca o saque em todos os usu├írios
        withdraw_data = None
        target_uid = None
        all_withdrawals = db.reference('withdrawals').get() or {}

        for uid, ws in all_withdrawals.items():
            if wid in ws:
                withdraw_data = ws[wid]
                target_uid = uid
                break

        if not withdraw_data: return {"status": "error", "msg": "Saque n├úo localizado."}

        amount = float(withdraw_data.get('amount', 0))
        pix_key = withdraw_data.get('pixKey', '')

        if not pix_key:
            return {"status": "error", "msg": "Chave PIX n├úo encontrada no pedido de saque."}

        def detect_pix(t):
            t = str(t).strip()
            # Remove formata├º├úo para validar tipos num├®ricos
            clean_t = "".join(filter(str.isdigit, t))

            if '@' in t: return 'EMAIL'
            if t.startswith('+') or (len(clean_t) >= 10 and len(clean_t) <= 11 and t.startswith('(')):
                return 'PHONE'
            if len(clean_t) == 11: return 'CPF'
            if len(clean_t) == 14: return 'CNPJ'
            return 'EVP'

        # Usa flag production para escolher ambiente Asaas
        is_prod = config.get('production', False) or '_prod_' in api_key.lower()
        asaas_url = "https://www.asaas.com/api/v3/transfers" if is_prod else "https://sandbox.asaas.com/api/v3/transfers"

        # Limpeza da chave PIX baseada no tipo detectado
        type_detected = detect_pix(pix_key)
        final_pix_key = pix_key
        if type_detected in ['CPF', 'CNPJ', 'PHONE']:
            final_pix_key = "".join(filter(str.isdigit, pix_key))
            if type_detected == 'PHONE' and not final_pix_key.startswith('55'):
                # Adiciona DDI Brasil se n├úo houver
                if len(final_pix_key) <= 11: final_pix_key = "55" + final_pix_key

        headers = {"access_token": api_key.strip(), "Content-Type": "application/json"}
        payload = {
            "value": amount,
            "pixAddressKey": final_pix_key,
            "pixAddressKeyType": type_detected,
            "description": f"CineCash VIP #{wid}"
        }

        resp = requests.post(asaas_url, json=payload, headers=headers, timeout=20)

        if resp.status_code == 200:
            db.reference(f'withdrawals/{target_uid}/{wid}').update({
                "status": "paid",
                "paid_at": datetime.now().isoformat()
            })
            return {"status": "success", "msg": "Pagamento liquidado com sucesso."}
        else:
            err_msg = resp.json().get('errors', [{}])[0].get('description', 'Erro Asaas')
            # Saque ja solicitado = transferencia ja existe no Asaas, considerar pago
            if 'ja solicitado' in err_msg.lower() or 'already' in err_msg.lower():
                db.reference(f'withdrawals/{target_uid}/{wid}').update({
                    "status": "paid",
                    "paid_at": datetime.now().isoformat()
                })
                return {"status": "success", "msg": "Transferencia ja processada pelo Asaas."}
            return {"status": "error", "msg": err_msg}

    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/video/start/{uid}")
async def video_start(uid: str):
    # L├│gica para registrar in├¡cio de visualiza├º├úo
    db.reference(f'logs/video_sessions/{uid}').push({"start": datetime.now().isoformat()})
    return {"status": "ok"}

@app.post("/video/complete/{uid}")
async def video_complete(uid: str):
    # L├│gica para creditar saldo (Sentinel valida se houve tempo suficiente)
    user_ref = db.reference(f'users/{uid}')
    user = user_ref.get()
    if not user: return HTTPException(status_code=404, detail="User not found")

    new_balance = (user.get('balance', 0)) + 0.10 # Exemplo de cr├®dito
    new_watched = (user.get('videosWatched', 0)) + 1

    user_ref.update({
        "balance": round(new_balance, 2),
        "videosWatched": new_watched
    })

    # Registra no log global de hits
    hits = db.reference('config/stats/hits').get() or 0
    db.reference('config/stats/hits').set(hits + 1)

    return {"status": "success", "balance": new_balance}

@app.post("/user/claim-daily/{uid}")
async def claim_daily(uid: str):
    today = datetime.now().strftime('%Y-%m-%d')
    user_ref = db.reference(f'users/{uid}')
    user = user_ref.get()

    if user.get('last_daily_bonus_date') == today:
        raise HTTPException(status_code=400, detail="B├┤nus j├í coletado hoje.")

    new_balance = (user.get('balance', 0)) + 0.20
    user_ref.update({
        "balance": round(new_balance, 2),
        "last_daily_bonus_date": today
    })
    return {"status": "success", "new_balance": new_balance}

@app.post("/heartbeat/site")
async def heartbeat(data: dict = Body({})):
    source = data.get("source", "site") if data else "site"
    db.reference(f'status/{source}_last_pulse').set({".sv": "timestamp"})
    return {"ok": True}

@app.post("/api/agent/data")
async def agent_webhook(data: dict = Body(...), req: Request = None):
    agent_id = data.get("agent_id", "unknown")
    agent_type = data.get("type", "hit")
    payload = data.get("payload", {})
    timestamp = datetime.now().isoformat()

    entry = {
        "agent_id": agent_id,
        "type": agent_type,
        "payload": payload,
        "received_at": timestamp,
        "ip": req.client.host if req and req.client else "unknown"
    }

    db.reference('agent_data/incoming').push(entry)

    # Atualiza contadores agregados
    ref = db.reference('agent_data/aggregated')
    aggr = ref.get() or {}

    if agent_type == "hit":
        aggr["total_hits"] = aggr.get("total_hits", 0) + 1
        page = payload.get("page", "unknown")
        pages = aggr.get("pages", {})
        pages[page] = pages.get(page, 0) + 1
        aggr["pages"] = pages

        source_name = payload.get("source", "direct")
        sources = aggr.get("sources", {})
        sources[source_name] = sources.get(source_name, 0) + 1
        aggr["sources"] = sources

        country = payload.get("country", "unknown")
        countries = aggr.get("countries", {})
        countries[country] = countries.get(country, 0) + 1
        aggr["countries"] = countries

    elif agent_type == "conversion":
        aggr["total_conversions"] = aggr.get("total_conversions", 0) + 1
        value = float(payload.get("value", 0))
        aggr["total_revenue"] = aggr.get("total_revenue", 0) + value
        # Tracking por canal
        source = payload.get("source", "direct")
        channels = aggr.get("channels", {})
        ch_id = "organico"
        if source in ("facebook", "instagram", "whatsapp", "telegram"):
            ch_id = "afiliados"
        elif source in ("google", "monetag", "taboola", "outbrain"):
            ch_id = "ads"
        ch_data = channels.get(ch_id, {"conversions": 0, "revenue": 0})
        ch_data["conversions"] = ch_data.get("conversions", 0) + 1
        ch_data["revenue"] = ch_data.get("revenue", 0) + value
        channels[ch_id] = ch_data
        aggr["channels"] = channels

    elif agent_type == "error":
        aggr["total_errors"] = aggr.get("total_errors", 0) + 1

    aggr["last_agent"] = agent_id
    aggr["last_update"] = timestamp
    ref.set(aggr)

    # Gatilho r├ípido no neural
    db.reference('status/neural_trigger').set(timestamp)
    db.reference('config/stats/hits').set(aggr.get("total_hits", 0))

    return {"status": "received", "agent": agent_id, "type": agent_type}

@app.post("/api/session/pulse")
async def session_pulse(data: dict = Body({})):
    uid = data.get("uid", "")
    page = data.get("page", "/admin/")
    ts = datetime.now().isoformat()
    session_id = f"sess_{int(datetime.now().timestamp() / 60)}"
    if uid:
        db.reference(f'logs/video_sessions/{uid}/{session_id}').update({
            "start": ts, "last_heartbeat": ts, "active": True, "page": page
        })
    return {"ok": True}

@app.post("/api/nexus/report")
async def nexus_report(data: dict = Body({})):
    uid = data.get("uid", "unknown")
    ads = int(data.get("ads_watched", 0))
    balance = float(data.get("balance", 0))
    page = data.get("page_context", "unknown")
    duration = int(data.get("session_duration", 0))
    platform = data.get("platform", "unknown")
    doubt = data.get("user_doubt")

    # Store raw telemetry
    db.reference(f'logs/nexus/{uid}').push({
        "report": data, "received_at": datetime.now().isoformat()
    })

    # Get user info
    user_ref = db.reference(f'users/{uid}')
    user_data = user_ref.get() or {}
    risk = user_data.get('risk_score', 0) if isinstance(user_data, dict) else 0
    email = user_data.get('email', uid) if isinstance(user_data, dict) else uid
    now = datetime.now().isoformat()

    # === NEXUS INSIGHTS ===
    alerts = []
    financial_status = "saudavel"
    nexus_actions = []

    # Fraude: saldo alto com poucos an├║ncios
    if balance > 10 and ads < 3:
        alerts.append(f"Poss├¡vel fraude: {email} ÔÇö R${balance} com {ads} ads")
        financial_status = "suspeito"
        nexus_actions.append({
            "to": "sentinel", "level": "alerta",
            "msg": f"NEXUS: {email} saldo R${balance} com apenas {ads} an├║ncios (poss├¡vel fraude)"
        })

    # Sa├║de financeira
    if balance >= 5:
        financial_status = "otimo"
        nexus_actions.append({
            "to": "auditor", "level": "info",
            "msg": f"NEXUS: {email} saldo R${balance} ÔÇö apto para saque"
        })
    elif balance >= 1:
        financial_status = "bom"
    elif balance > 0:
        financial_status = "regular"

    # Engajamento
    engaged = "alto" if duration > 300 else "m├®dio" if duration > 60 else "baixo"

    # Escreve insight do usu├írio
    insight = {
        "uid": uid, "email": email, "balance": balance, "ads": ads,
        "page": page, "duration": duration, "platform": platform,
        "risk": risk, "financial_status": financial_status,
        "engagement": engaged, "last_seen": now, "doubt": doubt
    }
    db.reference(f'nexus/insights/{uid}').update(insight)

    # Se houver alertas, cria a├º├úo
    if nexus_actions:
        for action in nexus_actions:
            action["uid"] = uid
            action["timestamp"] = now
            db.reference('nexus/actions').push(action)

    # Aprendizado neural: d├║vida do usu├írio
    if doubt:
        db.reference('neural/insights/nexus_last_doubt').set({
            "uid": uid, "doubt": doubt, "timestamp": now
        })

    return {
        "status": "received",
        "uid": uid,
        "financial_status": financial_status,
        "engagement": engaged,
        "alerts": len(alerts)
    }

@app.post("/api/security/authorize")
async def security_authorize(data: dict = Body({})):
    action_id = data.get("action_id", "")
    decision = data.get("decision", "")  # "approve" ou "deny"
    if not action_id or decision not in ("approve", "deny"):
        raise HTTPException(400, "action_id e decision (approve/deny) s├úo obrigat├│rios")

    ref = db.reference(f'security/pending_actions/{action_id}')
    action = ref.get()
    if not action:
        raise HTTPException(404, "A├º├úo n├úo encontrada")
    if action.get("status") != "pending":
        raise HTTPException(400, "A├º├úo j├í foi processada")

    now = datetime.now().isoformat()

    if decision == "approve":
        uid = action.get("uid", "")
        a_type = action.get("type", "")
        reason_map = {
            "device_clone": "Sentinel: M├║ltiplas contas no mesmo dispositivo (autorizado)",
            "vpn_proxy": "Sentinel: Conex├úo via Proxy/VPN (autorizado)",
            "root_jailbreak": "Sentinel: Dispositivo modificado Root/Jailbreak (autorizado)"
        }
        ban_reason = reason_map.get(a_type, "Sentinel: A├º├úo de seguran├ºa autorizada")

        # Aumenta risk_score + bane
        u_ref = db.reference(f'users/{uid}')
        user = u_ref.get()
        if user:
            new_risk = (user.get('risk_score', 0) if isinstance(user, dict) else 0) + 50
            u_ref.update({"risk_score": new_risk, "status": "banido", "ban_reason": ban_reason})

        ref.update({"status": "approved", "processed_at": now, "ban_reason": ban_reason})
        return {"status": "approved", "uid": uid, "reason": ban_reason}
    else:
        ref.update({"status": "denied", "processed_at": now})
        return {"status": "denied", "action_id": action_id}

@app.post("/api/sentinel/scan")
async def api_sentinel_scan():
    """ Rota para acionar a varredura manual via Admin """
    result = tool_sentinel_enforcement()
    if result["status"] == "success":
        db.reference('logs/activity').push({
            "user": "ADMIN",
            "action": f"Varredura Sentinel executada: {result['bans']} bans, {result['actions']} a├º├Áes.",
            "timestamp": {".sv": "timestamp"}
        })
        return {"status": "success", "msg": f"Varredura completa. {result['bans']} amea├ºas neutralizadas."}
    return result

@app.post("/api/test/push")
async def test_push(data: dict = Body(...)):
    uid = data.get("uid")
    if not uid: return {"status": "error", "msg": "UID obrigat├│rio"}

    try:
        user = db.reference(f'users/{uid}').get()
        token = user.get('fcmToken') if isinstance(user, dict) else None

        if not token:
            return {"status": "error", "msg": "Usu├írio sem token FCM"}

        message = messaging.Message(
            notification=messaging.Notification(
                title="CyberCore IA ­ƒøí´©Å",
                body="Teste de conex├úo Sentinel 2.0 ativo!"
            ),
            token=token
        )
        messaging.send(message)
        return {"status": "success", "msg": "Push enviado com sucesso"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

# --- ARQUIVOS EST├üTICOS (FRONTEND) ---

# Painel Admin em /admin
if os.path.exists(ADMIN_PATH):
    app.mount("/admin", StaticFiles(directory=ADMIN_PATH, html=True), name="admin")

# App do Usu├írio em /www
if os.path.exists(WWW_PATH):
    app.mount("/www", StaticFiles(directory=WWW_PATH, html=True), name="www")

# Favicon inline (SVG mesmo do HTML)
@app.get("/favicon.ico")
async def favicon():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#E8B830"/><stop offset="100%" stop-color="#1E9EBB"/></linearGradient></defs><circle cx="50" cy="50" r="48" fill="none" stroke="url(#g)" stroke-width="4"/><path d="M50 20 L58 40 L80 40 L62 55 L70 75 L50 62 L30 75 L38 55 L20 40 L42 40 Z" fill="url(#g)"/></svg>'
    return Response(content=svg, media_type="image/svg+xml")

# Redirecionamento da Raiz para o Admin
@app.get("/")
async def root():
    return RedirectResponse(url="/admin/")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)

