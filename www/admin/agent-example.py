import requests
import random
import time

# === CONFIGURE AQUI ===
AGENT_ID = "bot_visitas_01"
SERVER_URL = "http://localhost:7860"  # Troque pela URL do seu servidor em produção

def send_hit(page="/", source="direct", country="BR"):
    return requests.post(f"{SERVER_URL}/api/agent/data", json={
        "agent_id": AGENT_ID,
        "type": "hit",
        "payload": {
            "page": page,
            "source": source,
            "country": country,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    }, timeout=5)

def send_conversion(value=5.0, page="/checkout"):
    return requests.post(f"{SERVER_URL}/api/agent/data", json={
        "agent_id": AGENT_ID,
        "type": "conversion",
        "payload": {
            "value": value,
            "page": page,
            "product": "Plano VIP"
        }
    }, timeout=5)

def send_error(page="/erro", code=500):
    return requests.post(f"{SERVER_URL}/api/agent/data", json={
        "agent_id": AGENT_ID,
        "type": "error",
        "payload": {
            "page": page,
            "error_code": code,
            "message": "Erro simulado"
        }
    }, timeout=5)

print(f"Agente {AGENT_ID} enviando dados para {SERVER_URL}...\n")

pages = ["/", "/videos", "/dashboard", "/premium", "/checkout", "/login"]
sources = ["direct", "google", "facebook", "instagram", "whatsapp", "monetag"]
countries = ["BR", "US", "PT", "ES", "AR", "MX"]

for i in range(50):
    page = random.choice(pages)
    source = random.choice(sources)
    country = random.choice(countries)

    r = send_hit(page, source, country)
    print(f"[{i+1}] Hit enviado: {page} | {source} | {country} -> {r.json()}")

    # 10% chance de conversão
    if random.random() < 0.1:
        value = round(random.uniform(5, 50), 2)
        r2 = send_conversion(value, page)
        print(f"  -> CONVERSÃO R${value} -> {r2.json()}")

    # 5% chance de erro
    if random.random() < 0.05:
        r3 = send_error(page, random.choice([400, 500, 403]))
        print(f"  -> ERRO -> {r3.json()}")

    time.sleep(0.5)

print("\nConcluído! Confira o painel -> Memory Bank IA")
