import os
import sys
import json
import secrets
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import time

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials, db
from fastapi import FastAPI, Body, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import httpx

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
WWW_DIR = os.path.join(PROJECT_ROOT, "www")

os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.stdout: sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr: sys.stderr.reconfigure(encoding='utf-8')

# ─── Firebase Admin SDK ───
cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if cred_json:
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
    print("Firebase iniciado via variável de ambiente")
else:
    for fname in ("serviceAccountKey.json", "firebase-adminsdk.json"):
        fpath = os.path.join(BACKEND_DIR, fname)
        if os.path.exists(fpath):
            cred = credentials.Certificate(fpath)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
            print(f"Firebase iniciado com {fname}")
            break
    else:
        bak = os.path.join(BACKEND_DIR, "firebase-adminsdk.json.bak")
        if os.path.exists(bak):
            with open(bak) as f:
                cred = credentials.Certificate(json.load(f))
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {'databaseURL': 'https://playearn-b001b-default-rtdb.firebaseio.com'})
            print("Firebase iniciado via .bak (dev)")
        else:
            print("AVISO: Nenhuma credencial Firebase encontrada. Endpoints que usam banco falharão.")

ADMIN_EMAIL = "alegomes488@gmail.com"
_token_cache = {}

# ─── FastAPI App ───
app = FastAPI(title="CineCash API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_ROUTES = {"/health", "/", "/docs", "/openapi.json", "/favicon.ico", "/api/nexus/report", "/api/metrics"}

def is_public(path: str) -> bool:
    if path in PUBLIC_ROUTES: return True
    if path.startswith("/api/referral/resolve/"): return True
    if path.startswith("/api/memory/"): return True
    return False

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Capture Client IP
    request.state.client_ip = request.headers.get("X-Forwarded-For", request.client.host)

    # Bypass auth for static files and public routes
    if not path.startswith(("/api/", "/video/", "/payments/")) or is_public(path):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Token não fornecido"})

    token = auth_header.split(" ", 1)[1]
    cached = _token_cache.get(token)

    if cached and (datetime.now() - cached["at"]).total_seconds() < 10:
        if cached.get("banned"):
            return JSONResponse(status_code=403, content={"detail": "Conta suspensa pelo sistema VAR (Atividade Suspeita)"})
        request.state.user_uid = cached["uid"]
    else:
        try:
            decoded = firebase_auth.verify_id_token(token, check_revoked=False)
            uid = decoded.get("uid", "")

            # Verificação rápida de ban no RTDB
            user_status = db.reference(f"users/{uid}/banned").get()
            if user_status:
                _token_cache[token] = {"uid": uid, "at": datetime.now(), "banned": True}
                return JSONResponse(status_code=403, content={"detail": "Conta suspensa pelo sistema VAR (Atividade Suspeita)"})

            request.state.user_uid = uid
            _token_cache[token] = {"uid": uid, "at": datetime.now(), "banned": False}
        except Exception as e:
            return JSONResponse(status_code=401, content={"detail": f"Token inválido: {str(e)}"})

    response = await call_next(request)
    return response

# ─── VAR Security System (Canarinho) ───
def run_var_check(uid: str, ip: str, action: str, current_data: dict):
    """
    Sistema de Assistente de Vídeo (VAR) para detecção de fraudes.
    """
    risk_delta = 0
    reasons = []

    # 1. IP Consistency
    last_ip = current_data.get("last_ip")
    if last_ip and last_ip != ip:
        risk_delta += 10
        reasons.append(f"Troca de IP: {last_ip} -> {ip}")

    # 2. Velocity Check
    if action == "video_complete":
        last_video = current_data.get("last_video_at")
        if last_video:
            elapsed = (datetime.now() - datetime.fromisoformat(last_video)).total_seconds()
            if elapsed < 25:
                risk_delta += 30
                reasons.append(f"Velocidade impossível: {elapsed}s entre vídeos")

    # 3. Multi-Account Check (Simulado)
    # Se muitos UIDs usam o mesmo IP em pouco tempo (Pode ser implementado com um cache global)

    if risk_delta > 0:
        new_risk = int(current_data.get("risk_score", 0)) + risk_delta
        db.reference(f"logs/security/{uid}").push({
            "action": action,
            "ip": ip,
            "risk_added": risk_delta,
            "reasons": reasons,
            "timestamp": datetime.now().isoformat()
        })
        return new_risk

    return int(current_data.get("risk_score", 0))

# ─── Health ───
@app.get("/health")
@app.get("/health/")
async def health():
    return {"status": "online", "timestamp": datetime.now().isoformat()}

# ─── Metrics ───
@app.get("/api/metrics")
async def metrics():
    try:
        t0 = time.time()
        db.reference("status/ping_test").set({"ts": time.time()})
        ping = round((time.time() - t0) * 1000, 1)
    except:
        ping = 0
    return {
        "ping": ping,
        "status": "online",
        "timestamp": datetime.now().isoformat()
    }

# ─── Nexus Telemetry ───
@app.post("/api/nexus/report")
async def nexus_report(data: dict = Body({})):
    uid = data.get("uid", "unknown")
    try:
        db.reference(f"logs/nexus/{uid}").push({
            "report": data,
            "received_at": datetime.now().isoformat()
        })
    except Exception as e:
        print(f"[NEXUS] Erro: {e}")
    return {"status": "received", "uid": uid}

# ─── Video Start ───
@app.post("/video/start/{uid}")
@app.get("/video/start/{uid}")
async def video_start(uid: str, request: Request):
    if request.state.user_uid != uid:
        raise HTTPException(status_code=403, detail="Acesso negado")
    try:
        db.reference(f"users/{uid}/video_session").set({
            "start_at": datetime.now().isoformat(),
            "valid": True
        })
        return {"status": "success", "session": "active", "timestamp": datetime.now().isoformat()}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Video Complete ───
@app.post("/video/complete/{uid}")
async def video_complete(uid: str, request: Request):
    if request.state.user_uid != uid:
        raise HTTPException(status_code=403, detail="Acesso negado")

    client_ip = request.state.client_ip

    try:
        user_ref = db.reference(f"users/{uid}")

        def trans(current):
            if current is None: return current
            cd = current if isinstance(current, dict) else {}

            # Rodar VAR (Segurança)
            new_risk = run_var_check(uid, client_ip, "video_complete", cd)
            cd["risk_score"] = new_risk
            cd["last_ip"] = client_ip

            if new_risk >= 100:
                cd["banned"] = True
                cd["_error"] = "Sua conta foi suspensa por atividade suspeita (VAR)."
                return cd

            session = cd.get("video_session")
            if not session or not session.get("valid"):
                cd["_error"] = "Sessão inválida. Use o botão oficial."
                return cd

            start_ts = datetime.fromisoformat(session.get("start_at"))
            elapsed = (datetime.now() - start_ts).total_seconds()
            if elapsed < 29:
                risk = int(cd.get("risk_score", 0)) + 15
                cd["risk_score"] = risk
                if risk > 50:
                    cd["soft_ban_until"] = (datetime.now() + timedelta(hours=2)).isoformat()
                    cd["_error"] = "Atividade suspeita. Suspensão de 2h."
                else:
                    cd["_error"] = f"Análise muito rápida ({int(elapsed)}s)."
                return cd

            last_video = cd.get("last_video_at")
            if last_video:
                diff = (datetime.now() - datetime.fromisoformat(last_video)).total_seconds()
                if diff < 28:
                    cd["risk_score"] = int(cd.get("risk_score", 0)) + 5
                    cd["_error"] = "Aguarde o processamento."
                    return cd

            cd["video_session"] = {"valid": False}
            current_videos = int(cd.get("videosWatched", 0))
            new_videos = current_videos + 1
            current_balance = float(cd.get("balance", 0))

            milestones = [200, 800, 1000, 2000, 10000]
            rewards = [0.50, 3.00, 5.00, 10.00, 50.00]
            claimed = dict(cd.get("milestones", {}))
            reward_total = 0
            for i, m in enumerate(milestones):
                mk = str(m)
                if new_videos >= m and not claimed.get(mk):
                    reward_total += rewards[i]
                    claimed[mk] = True

            cd["balance"] = current_balance + reward_total
            cd["videosWatched"] = new_videos
            cd["last_video_at"] = datetime.now().isoformat()
            if reward_total > 0:
                cd["milestones"] = claimed

            # Increment global hits for telemetry
            try:
                stats_ref = db.reference("config/stats")
                stats_ref.child("hits").transaction(lambda current: (current or 0) + 1)

                # Update daily profit history
                config = db.reference("config").get() or {}
                cpm = float(config.get("cpm", 0.18))
                rate = float(db.reference("status/financial_realtime/rate").get() or 5.25)
                profit_per_hit = (cpm * rate) / 1000

                history_ref = db.reference("config/profit_history")
                def update_history(current):
                    if not current or not isinstance(current, list):
                        return [{"t": int(time.time()), "v": profit_per_hit}]
                    current.append({"t": int(time.time()), "v": profit_per_hit})
                    if len(current) > 2000:
                        return current[-2000:]
                    return current

                history_ref.transaction(update_history)
            except:
                pass

            cd["_reward_total"] = reward_total
            cd["_new_videos"] = new_videos
            return cd

        result = user_ref.transaction(trans)
        if result is None:
            return {"status": "error", "message": "Usuário não encontrado"}
        if result.get("_error"):
            return {"status": "error", "message": result["_error"]}

        reward_total = result.pop("_reward_total", 0)
        new_videos = result.pop("_new_videos", 0)

        if new_videos == 50:
            sponsor = result.get("referredBy")
            if sponsor:
                try:
                    sref = db.reference(f"users/{sponsor}")
                    def st(sp):
                        if sp is None: return None
                        sd = sp if isinstance(sp, dict) else {}
                        vrefs = int(sd.get("validReferrals", 0)) + 1
                        sd["balance"] = float(sd.get("balance", 0)) + 0.20
                        sd["validReferrals"] = vrefs
                        sd["referralBonus"] = float(sd.get("referralBonus", 0)) + 0.20
                        if vrefs % 7 == 0:
                            sd["balance"] = float(sd["balance"]) + 1.50
                            sd["referralBonus"] = float(sd["referralBonus"]) + 1.50
                        return sd
                    sref.transaction(st)
                except:
                    pass

        return {
            "status": "success",
            "new_balance": result.get("balance", 0),
            "videos_count": new_videos,
            "milestone_reward": reward_total
        }
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Referral Create ───
@app.post("/api/referral/create/{uid}")
async def create_referral(uid: str, request: Request):
    if request.state.user_uid != uid:
        raise HTTPException(status_code=403, detail="Acesso negado")
    try:
        user_ref = db.reference(f"users/{uid}")
        if not user_ref.get():
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        slug = secrets.token_urlsafe(8)
        expires_at = (datetime.now() + timedelta(days=30)).isoformat()

        db.reference(f"referrals/{slug}").set({
            "uid": uid, "expires_at": expires_at, "created_at": datetime.now().isoformat()
        })
        user_ref.update({
            "active_referral_slug": slug,
            "referral_slug_expires": expires_at
        })

        return {"status": "success", "slug": slug, "expires_at": expires_at}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Referral Resolve ───
@app.get("/api/referral/resolve/{slug}")
async def resolve_referral(slug: str):
    try:
        ref_data = db.reference(f"referrals/{slug}").get()
        if not ref_data:
            return {"status": "error", "message": "Link inválido."}
        expires = ref_data.get("expires_at")
        if expires and datetime.now() > datetime.fromisoformat(expires):
            return {"status": "error", "message": "Link expirado (30 dias)."}
        return {"status": "success", "uid": ref_data.get("uid")}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ─── Payments Request ───
@app.post("/payments/request/{uid}")
async def request_withdrawal(uid: str, data: dict = Body(...), request: Request = None):
    if request.state.user_uid != uid:
        raise HTTPException(status_code=403, detail="Acesso negado")
    try:
        amount = float(data.get("amount", 0))
        pix_key = data.get("pixKey", "").strip()
        pix_type = data.get("pixType", "EVP").upper()
        project_id = data.get("projectId")

        if amount < 0.50:
            return {"status": "error", "message": "Mínimo R$ 0,50"}
        if amount > 50.0:
            return {"status": "error", "message": "Máximo R$ 50,00"}
        if not pix_key:
            return {"status": "error", "message": "Chave PIX obrigatória"}
        valid_types = {"CPF", "CNPJ", "EMAIL", "PHONE", "EVP"}
        if pix_type not in valid_types:
            return {"status": "error", "message": "Tipo de chave inválido"}

        user_ref = db.reference(f"users/{uid}")

        def trans(current):
            if current is None: return {"_error": "Usuário não encontrado"}
            cd = current if isinstance(current, dict) else {}

            if float(cd.get("balance", 0)) < amount:
                cd["_error"] = f"Saldo insuficiente. Você tem R$ {float(cd.get('balance', 0)):.2f}"
                return cd
            last_wd = cd.get("last_withdraw_at")
            if last_wd:
                if (datetime.now() - datetime.fromisoformat(last_wd)).total_seconds() < 3600:
                    cd["_error"] = "Limite de 1 saque por hora."
                    return cd
            cd["balance"] = float(cd.get("balance", 0)) - amount
            cd["last_withdraw_at"] = datetime.now().isoformat()
            cd["_success"] = True
            return cd

        result = user_ref.transaction(trans)
        if result is None:
            return {"status": "error", "message": "Usuário não encontrado"}
        if result.get("_error"):
            return {"status": "error", "message": result["_error"]}

        ts = int(datetime.now().timestamp() * 1000)
        wid = f"WID{ts}"
        user_data = user_ref.get() or {}
        withdraw_obj = {
            "amount": amount, "pixKey": pix_key, "pixType": pix_type,
            "status": "pending", "timestamp": ts,
            "created_at": datetime.now().isoformat(), "uid": uid,
            "fullname": user_data.get("fullname", "Usuário"),
            "projectId": project_id,
            "fingerprint": data.get("fingerprint", "unknown"),
        }
        db.reference(f"withdrawals/{uid}/{wid}").set(withdraw_obj)
        db.reference(f"admin/pending_withdrawals/{wid}").set(withdraw_obj)

        return {"status": "success", "message": "Saque solicitado!", "wid": wid}
    except HTTPException: raise
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ─── Payments Approval (Asaas Integration) ───

async def process_asaas_pix(asaas_key: str, amount: float, pix_key: str, pix_type: str, description: str):
    url = "https://www.asaas.com/api/v3/transfers"
    # Mapping Pix types to Asaas format
    pix_mapping = {
        "CPF": "CPF",
        "CNPJ": "CNPJ",
        "EMAIL": "EMAIL",
        "PHONE": "PHONE",
        "EVP": "RANDOM_KEY"
    }

    headers = {
        "access_token": asaas_key,
        "Content-Type": "application/json"
    }

    payload = {
        "value": amount,
        "pixAddressKey": pix_key,
        "pixAddressKeyType": pix_mapping.get(pix_type, "RANDOM_KEY"),
        "description": description
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=30.0)
            return resp.json()
        except Exception as e:
            return {"errors": [{"description": f"Erro de conexão com Asaas: {str(e)}"}]}

@app.post("/payments/approve/{wid}")
async def approve_payment(wid: str, request: Request):
    # Security: Verify if the request comes from the admin
    user_uid = getattr(request.state, "user_uid", "")
    try:
        user_data = firebase_auth.get_user(user_uid)
        if user_data.email != ADMIN_EMAIL:
             raise HTTPException(status_code=403, detail="Acesso administrativo exigido")
    except:
        raise HTTPException(status_code=403, detail="Acesso administrativo exigido")

    try:
        # Get withdrawal data
        wd_ref = db.reference(f"admin/pending_withdrawals/{wid}")
        wd = wd_ref.get()
        if not wd:
            return {"status": "error", "message": "Saque não encontrado na fila pendente"}

        # Get Asaas Key from config
        config = db.reference("config").get() or {}
        asaas_key = config.get("asaasKey") or config.get("asaas_key")

        if not asaas_key:
            return {"status": "error", "message": "Chave API Asaas não configurada"}

        # Process via Asaas
        result = await process_asaas_pix(
            asaas_key,
            wd["amount"],
            wd["pixKey"],
            wd["pixType"],
            f"CineCash - Resgate {wid}"
        )

        if "errors" in result:
             return {"status": "error", "message": result["errors"][0]["description"]}

        # Update status in Firebase
        uid = wd["uid"]
        asaas_id = result.get("id")
        update_data = {"status": "processing", "sent_at": datetime.now().isoformat(), "asaas_id": asaas_id}

        db.reference(f"withdrawals/{uid}/{wid}").update(update_data)

        # Mapeamento para o Webhook encontrar o saque depois
        db.reference(f"admin/asaas_mappings/{asaas_id}").set({"uid": uid, "wid": wid})

        wd_ref.delete() # Remove from pending

        # Log to financial logs
        db.reference("logs/financial").push({
            "type": "withdrawal_paid",
            "wid": wid,
            "uid": uid,
            "amount": wd["amount"],
            "timestamp": int(time.time() * 1000),
            "description": f"Saque de R${wd['amount']} pago para {wd.get('fullname')}"
        })

        return {"status": "success", "message": "Saque pago com sucesso via Asaas!"}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/process-all-payments")
async def process_all_payments(request: Request):
    # Security: Verify if the request comes from the admin
    user_uid = getattr(request.state, "user_uid", "")
    try:
        user_data = firebase_auth.get_user(user_uid)
        if user_data.email != ADMIN_EMAIL:
             raise HTTPException(status_code=403, detail="Acesso administrativo exigido")
    except:
        raise HTTPException(status_code=403, detail="Acesso administrativo exigido")

    pending = db.reference("admin/pending_withdrawals").get()
    if not pending:
        return {"status": "success", "message": "Nenhum saque pendente"}

    results = []
    for wid in pending.keys():
        # Ideally, this should be tasks in a queue, but for small volumes we can loop
        # Note: In a production environment with many payments, use a background task
        res = await approve_payment(wid, request)
        results.append({"wid": wid, "result": res})

    return {"status": "success", "processed": len(results), "details": results}

@app.post("/payments/webhook")
async def asaas_webhook(data: dict = Body(...)):
    """
    Recebe notificações do Asaas sobre o status das transferências.
    Eventos: TRANSFER_PAID, TRANSFER_FAILED, TRANSFER_CANCELLED
    """
    event = data.get("event")
    transfer = data.get("transfer")

    if not transfer or not event:
        return {"status": "ignored"}

    asaas_id = transfer.get("id")
    mapping = db.reference(f"admin/asaas_mappings/{asaas_id}").get()

    if not mapping:
        print(f"[Webhook] Mapeamento não encontrado para Asaas ID: {asaas_id}")
        return {"status": "not_found"}

    uid = mapping.get("uid")
    wid = mapping.get("wid")

    if event == "TRANSFER_PAID":
        db.reference(f"withdrawals/{uid}/{wid}").update({
            "status": "paid",
            "paid_at": datetime.now().isoformat(),
            "asaas_details": transfer
        })
        # Log final
        db.reference("logs/financial").push({
            "type": "webhook_confirmed",
            "wid": wid,
            "uid": uid,
            "status": "paid",
            "timestamp": int(time.time() * 1000)
        })
    elif event in ["TRANSFER_FAILED", "TRANSFER_CANCELLED"]:
        # Se falhar, devolvemos o saldo ao usuário (opcional, mas recomendado)
        fail_reason = transfer.get("failReason") or "Cancelado pelo Asaas"

        def refund_trans(current):
            if not current: return current
            cd = current if isinstance(current, dict) else {}
            # O valor do saque original precisa ser recuperado
            # Para simplificar este MVP, apenas marcamos como erro
            return cd

        db.reference(f"withdrawals/{uid}/{wid}").update({
            "status": "error",
            "error_msg": fail_reason,
            "failed_at": datetime.now().isoformat()
        })

        # Opcional: Re-adicionar à fila de admin para revisão
        withdraw_data = db.reference(f"withdrawals/{uid}/{wid}").get()
        db.reference(f"admin/failed_withdrawals/{wid}").set(withdraw_data)

    return {"status": "processed"}

# ─── Game Reward ───
@app.post("/api/game/reward/{uid}")
async def game_reward(uid: str, data: dict = Body(...), request: Request = None):
    if request.state.user_uid != uid:
        raise HTTPException(status_code=403, detail="Acesso negado")

    game_id = data.get("gameId", "")
    score = int(data.get("score", 0))

    valid_games = {"flappy", "memory"}
    if game_id not in valid_games:
        return {"status": "error", "message": "Jogo inválido"}

    if game_id == "flappy":
        reward = 0.03 if score >= 30 else (0.01 if score >= 10 else 0)
    elif game_id == "memory":
        time_taken = float(data.get("time", 999))
        reward = 0.05 if time_taken < 30 else (0.03 if time_taken < 60 else 0)
    else:
        reward = 0

    if reward <= 0:
        return {"status": "error", "message": "Pontuação insuficiente"}

    try:
        user_ref = db.reference(f"users/{uid}")

        def trans(current):
            if current is None: return {"_error": "Usuário não encontrado"}
            cd = current if isinstance(current, dict) else {}

            # Rodar VAR (Segurança)
            new_risk = run_var_check(uid, request.state.client_ip, f"game_reward_{game_id}", cd)
            cd["risk_score"] = new_risk
            if new_risk >= 100:
                cd["banned"] = True
                cd["_error"] = "Sua conta foi suspensa por atividade suspeita (VAR)."
                return cd

            today = datetime.now().strftime("%Y-%m-%d")
            game_data = dict(cd.get("games", {}).get(game_id, {}))
            last_date = game_data.get("lastDate", "")
            plays_today = game_data.get("playsToday", 0) if last_date == today else 0

            max_plays = {"flappy": 10, "memory": 5}
            max_play = max_plays.get(game_id, 10)

            if plays_today >= max_play:
                cd["_error"] = f"Limite diário de {max_play} partidas atingido"
                return cd

            cd["balance"] = float(cd.get("balance", 0)) + reward
            if "games" not in cd or not isinstance(cd["games"], dict):
                cd["games"] = {}
            if game_id not in cd["games"] or not isinstance(cd["games"][game_id], dict):
                cd["games"][game_id] = {}

            if last_date != today:
                cd["games"][game_id]["totalEarned"] = 0
                plays_today = 0

            cd["games"][game_id]["playsToday"] = plays_today + 1
            cd["games"][game_id]["lastDate"] = today
            cd["games"][game_id]["totalEarned"] = float(cd["games"][game_id].get("totalEarned", 0)) + reward
            cd["games"][game_id]["lastScore"] = score

            return cd

        result = user_ref.transaction(trans)
        if result is None:
            return {"status": "error", "message": "Usuário não encontrado"}
        if result.get("_error"):
            return {"status": "error", "message": result["_error"]}

        return {"status": "success", "reward": reward, "balance": result.get("balance", 0)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ─── Memory FAQ (Aprendizado do Canarinho) ───
MEMORY_DIR = os.path.join(PROJECT_ROOT, "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "faq.json")
os.makedirs(MEMORY_DIR, exist_ok=True)

def load_faq():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_faq(faq):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(faq, f, ensure_ascii=False, indent=2)

def tokenize(text):
    import re
    words = re.findall(r'[a-záéíóúãõâêîôûç]+', text.lower())
    return set(words)

def similarity(text1, text2):
    t1 = tokenize(text1)
    t2 = tokenize(text2)
    if not t1 or not t2:
        return 0
    intersection = t1 & t2
    union = t1 | t2
    return len(intersection) / len(union) if union else 0

@app.post("/api/memory/search")
async def memory_search(data: dict = Body(...)):
    query = data.get("query", "").strip()
    threshold = float(data.get("threshold", 0.35))
    if not query:
        return {"status": "error", "message": "Query vazia"}
    faq = load_faq()
    best_score = 0
    best_match = None
    for entry in faq:
        score = similarity(query, entry["question"])
        if score > best_score:
            best_score = score
            best_match = entry
    if best_match and best_score >= threshold:
        return {
            "status": "success",
            "found": True,
            "answer": best_match["answer"],
            "question": best_match["question"],
            "score": round(best_score, 3),
            "frequency": best_match.get("frequency", 1)
        }
    return {"status": "success", "found": False, "score": 0}

@app.post("/api/memory/store")
async def memory_store(data: dict = Body(...)):
    question = data.get("question", "").strip()
    answer = data.get("answer", "").strip()
    if not question or not answer:
        return {"status": "error", "message": "Pergunta e resposta obrigatórias"}
    faq = load_faq()
    for entry in faq:
        if similarity(question, entry["question"]) > 0.8:
            entry["frequency"] = entry.get("frequency", 1) + 1
            save_faq(faq)
            return {"status": "success", "updated": True, "id": entry.get("id")}
    new_id = (max((e.get("id", 0) for e in faq), default=0) + 1)
    faq.append({
        "id": new_id,
        "question": question,
        "answer": answer,
        "frequency": 1,
        "created_at": datetime.now().isoformat()
    })
    save_faq(faq)
    return {"status": "success", "id": new_id}

# ─── Static Files ───
app.mount("/", StaticFiles(directory=WWW_DIR, html=True), name="www")

if __name__ == "__main__":
    print(f"[+] Servindo site de: {WWW_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=7860)
