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
        self.telemetry_interval = 30 # seconds
        self.node_id = None # Set by hub if needed

    def get_system_metrics(self):
        try:
            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                "cpu_usage": cpu,
                "ram_usage": memory.percent,
                "ram_total_gb": round(memory.total / (1024**3), 2),
                "disk_usage": disk.percent,
                "platform": platform.system(),
                "platform_release": platform.release(),
                "hostname": socket.gethostname(),
                "local_ip": socket.gethostbyname(socket.gethostname()),
                "uptime_seconds": time.time() - psutil.boot_time(),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}

    def report_telemetry(self):
        metrics = self.get_system_metrics()
        payload = {
            "agent_id": self.agent_id,
            "type": "local_telemetry",
            "payload": metrics
        }
        try:
            # We reuse the nexus/report logic or a dedicated endpoint
            requests.post(f"{self.hub_url}/api/nexus/report", json={
                "uid": f"agent_{self.agent_id}",
                "telemetry": metrics,
                "source": "local_agent"
            }, timeout=10)
            return True
        except Exception as e:
            print(f"Error reporting telemetry: {e}")
            return False

    def check_commands(self):
        """Check for pending commands from the hub (long polling or dedicated endpoint)"""
        # Placeholder for command execution logic
        pass

    def run(self):
        print(f"🚀 CyberCore Local Agent '{self.agent_id}' started.")
        print(f"🔗 Connected to Hub: {self.hub_url}")
        self.is_running = True

        while self.is_running:
            success = self.report_telemetry()
            if success:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Telemetry reported.")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Failed to report telemetry.")

            time.sleep(self.telemetry_interval)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='CyberCore Local Agent')
    parser.add_argument('--id', type=str, default=f"local_{socket.gethostname()}", help='Unique ID for this agent')
    parser.add_argument('--hub', type=str, default="http://localhost:7860", help='Hub URL')

    args = parser.parse_args()

    agent = CyberCoreLocalAgent(agent_id=args.id, hub_url=args.hub)
    agent.run()
