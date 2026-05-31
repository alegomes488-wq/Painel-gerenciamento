import os, sys, subprocess
from core.state import CyberCoreState

AGENT_REGISTRY = {
    "python_core": {"path": r"C:\Users\Alegomes\cybercore\agents\python_core", "port": 5008, "build_script": "build.py"},
    "fiscal":     {"port": 5001}, "sentinel": {"port": 5002}, "auditor": {"port": 5003},
    "designer":   {"port": 5004}, "software": {"port": 5006}, "fullstack": {"port": 5007},
    "java_core":  {"port": 5009},
}

class AgentManager:
    def __init__(self):
        self.state = CyberCoreState()

    def execute(self, task):
        agent_name = task.get("agent", "python_core")
        prompt = task.get("prompt", "")
        registry = AGENT_REGISTRY.get(agent_name)
        if not registry:
            return {"answer": f"Agente '{agent_name}' não encontrado.", "status": "error"}
        self.state.set("active_agent", agent_name)

        try:
            import requests
            port = registry.get("port")
            if port:
                resp = requests.post(f"http://localhost:{port}/execute", json={"task_id": task.get("id"), "action": "process_prompt", "payload": {"prompt": prompt}}, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    return {"answer": data.get("result", "OK"), "status": "success", "agent": agent_name}
        except:
            pass

        if agent_name == "python_core":
            return self._run_build(prompt)
        return {"agent": agent_name, "status": "fallback", "answer": f"Agente {agent_name} offline."}

    def _run_build(self, prompt):
        agent_path = r"C:\Users\Alegomes\cybercore\agents\python_core"
        script = os.path.join(agent_path, "build.py")
        if not os.path.exists(script):
            return {"agent": "python_core", "status": "error", "answer": "build.py não encontrado."}
        try:
            result = subprocess.run([sys.executable, script, prompt], capture_output=True, text=True, timeout=600, encoding='utf-8', errors='replace', cwd=agent_path)
            output = (result.stdout + result.stderr).strip()
            return {"agent": "python_core", "status": "ok" if result.returncode == 0 else "error", "answer": output or "Concluído."}
        except subprocess.TimeoutExpired:
            return {"agent": "python_core", "status": "error", "answer": "Tempo limite excedido (600s)."}
        except Exception as e:
            return {"agent": "python_core", "status": "error", "answer": f"Erro: {str(e)}"}
