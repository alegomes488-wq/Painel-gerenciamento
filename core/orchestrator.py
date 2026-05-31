from datetime import datetime
from core.state import CyberCoreState
from core.router import Router
from core.memory_manager import MemoryManager
from core.task_manager import TaskManager
from core.agent_manager import AgentManager
from core.conversation import ConversationManager
from core.learning import LearningEngine

class Orchestrator:
    def __init__(self):
        self.state = CyberCoreState()
        self.router = Router()
        self.memory = MemoryManager()
        self.tasks = TaskManager()
        self.agents = AgentManager()
        self.conversation = ConversationManager()
        self.learning = LearningEngine()

    def dispatch(self, prompt, uid="admin", context=None):
        self.state.set("system_status", "processing")
        self.state.set("last_activity", datetime.now().isoformat())

        intent = self.router.analyze_intent(prompt)
        history = self.conversation.get_history(uid)
        similar = self.memory.search(prompt, uid)
        decision = self.router.decide(prompt, uid, self.learning)

        task = self.tasks.create(decision["agent"], prompt, uid, decision)
        self.conversation.add_message(uid, "user", prompt)
        self.state.set("active_agent", decision["agent"])

        result = self.agents.execute(task)
        success = result.get("status") in ("ok", "success")
        self.tasks.complete(task["id"], result)
        self.learning.register_outcome(prompt, decision["agent"], success, {"intent": intent, "similar_found": len(similar), "confidence": decision.get("confidence")})

        self.memory.store(uid, prompt, result, decision)
        self.conversation.add_message(uid, "agent", result.get("answer", ""))
        self.state.set("system_status", "idle")
        self.state.set("active_agent", None)

        return {"answer": result.get("answer", ""), "agent": decision["agent"], "task_id": task["id"], "status": "ok" if success else "error"}

    def status(self):
        return {"status": self.state.get("system_status"), "active_agent": self.state.get("active_agent"), "running_tasks": len(self.state.get("running_tasks", [])), "mode": self.state.get("mode"), "last_activity": self.state.get("last_activity")}
