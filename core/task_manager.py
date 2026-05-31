import json, os, uuid, time
from datetime import datetime
from core.state import CyberCoreState

TASKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks")

class TaskManager:
    def __init__(self):
        self.state = CyberCoreState()
        os.makedirs(TASKS_DIR, exist_ok=True)

    def create(self, agent, prompt, uid, decision=None):
        task = {"id": f"task_{uuid.uuid4().hex[:8]}", "agent": agent, "prompt": prompt, "uid": uid, "decision": decision, "status": "running", "priority": decision.get("confidence") if decision else "medium", "created": datetime.now().isoformat(), "completed": None, "result": None}
        json.dump(task, open(os.path.join(TASKS_DIR, f"{task['id']}.json"), "w"), indent=2)
        running = self.state.get("running_tasks", [])
        running.append(task["id"])
        self.state.set("running_tasks", running)
        return task

    def complete(self, task_id, result):
        filepath = os.path.join(TASKS_DIR, f"{task_id}.json")
        if os.path.exists(filepath):
            task = json.load(open(filepath))
            task["status"] = "completed"
            task["completed"] = datetime.now().isoformat()
            task["result"] = result
            json.dump(task, open(filepath, "w"), indent=2)
        running = self.state.get("running_tasks", [])
        if task_id in running:
            running.remove(task_id)
            self.state.set("running_tasks", running)

    def list_active(self):
        return [f.replace(".json","") for f in os.listdir(TASKS_DIR) if f.endswith(".json")]
