import os
import sys
import time
import requests
import json
import socket
import psutil
import platform
import subprocess
from datetime import datetime

class CyberCoreLocalAgent:
    def __init__(self, agent_id, hub_url="http://localhost:7860"):
        self.agent_id = agent_id
        self.hub_url = hub_url
        self.is_running = False
        self.telemetry_interval = 15 # Reduzido para maior precisão no "Watch"
        self.node_id = agent_id

    def get_system_metrics(self):
        try:
            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Detecção de rede
            net = psutil.net_io_counters()

            return {
                "status": "online",
                "cpu_usage": cpu,
                "ram_usage": memory.percent,
                "ram_total_gb": round(memory.total / (1024**3), 2),
                "disk_usage": disk.percent,
                "net_sent_mb": round(net.bytes_sent / (1024**2), 2),
                "net_recv_mb": round(net.bytes_recv / (1024**2), 2),
                "platform": platform.system(),
                "platform_release": platform.release(),
                "hostname": socket.gethostname(),
                "local_ip": socket.gethostbyname(socket.gethostname()),
                "uptime_seconds": time.time() - psutil.boot_time(),
                "timestamp": datetime.now().isoformat(),
                "latency_ms": self.measure_latency()
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def measure_latency(self):
        try:
            start = time.time()
            requests.get(f"{self.hub_url}/health", timeout=5)
            return int((time.time() - start) * 1000)
        except:
            return 999

    def report_telemetry(self):
        metrics = self.get_system_metrics()
        payload = {
            "uid": self.agent_id,
            "type": "local_agent_telemetry",
            "telemetry": metrics,
            "source": "local_node"
        }
        try:
            response = requests.post(f"{self.hub_url}/api/nexus/report", json=payload, timeout=10)
            if response.status_code == 200:
                # Se o Hub enviar comandos na resposta, podemos processá-los aqui
                data = response.json()
                if "command" in data:
                    self.execute_command(data["command"])
                return True
            return False
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Connection Error: {e}")
            return False

    def execute_command(self, cmd_data):
        print(f"📥 Executing Command: {cmd_data.get('action')}")
        # Lógica para executar scripts, restart, etc.
        pass

    def run(self):
        print("\n" + "="*50)
        print("   ⚛️  CYBERCORE LOCAL AGENT - NODE ACTIVE")
        print("="*50)
        print(f"   ID: {self.agent_id}")
        print(f"   HUB: {self.hub_url}")
        print(f"   INT: {self.telemetry_interval}s")
        print("="*50 + "\n")

        self.is_running = True

        # Registro inicial
        self.report_telemetry()

        while self.is_running:
            start_time = time.time()
            success = self.report_telemetry()

            if success:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📡 Heartbeat OK | Latency: {self.measure_latency()}ms")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Hub Unreachable. Retrying...")

            # Mantém o intervalo exato
            elapsed = time.time() - start_time
            sleep_time = max(0, self.telemetry_interval - elapsed)
            time.sleep(sleep_time)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='CyberCore Local Agent')
    parser.add_argument('--id', type=str, default=f"local_{socket.gethostname()}", help='Unique ID for this agent')
    parser.add_argument('--hub', type=str, default="http://localhost:7860", help='Hub URL')

    args = parser.parse_args()

    agent = CyberCoreLocalAgent(agent_id=args.id, hub_url=args.hub)
    agent.run()
