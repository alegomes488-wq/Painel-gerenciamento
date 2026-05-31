import json, os
from datetime import datetime
from collections import defaultdict

LEARN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "learning")
OUTCOMES_FILE = os.path.join(LEARN_DIR, "learning_logs.json")
PREFS_FILE = os.path.join(LEARN_DIR, "preferences.json")

class LearningEngine:
    def __init__(self):
        os.makedirs(LEARN_DIR, exist_ok=True)
        self._patterns = defaultdict(lambda: {"total": 0, "success": 0})
        self._load()

    def _load(self):
        if os.path.exists(OUTCOMES_FILE):
            try:
                for entry in json.load(open(OUTCOMES_FILE)):
                    key = f"{entry.get('agent','?')}:{entry.get('prompt','')[:30]}"
                    self._patterns[key]["total"] += 1
                    if entry.get("success"):
                        self._patterns[key]["success"] += 1
            except: pass

    def register_outcome(self, prompt, agent, success, meta=None):
        entry = {"prompt": prompt[:200], "agent": agent, "success": success, "timestamp": datetime.now().isoformat(), "meta": meta or {}}
        outcomes = json.load(open(OUTCOMES_FILE)) if os.path.exists(OUTCOMES_FILE) else []
        outcomes.append(entry)
        json.dump(outcomes, open(OUTCOMES_FILE, "w"), indent=2)
        key = f"{agent}:{prompt[:30]}"
        self._patterns[key]["total"] += 1
        if success: self._patterns[key]["success"] += 1

    def best_agent_for(self, prompt):
        prompt_lower = prompt.lower()
        candidates = []
        for key, stats in self._patterns.items():
            try: agent, keyword = key.split(":", 1)
            except: continue
            if keyword.lower() in prompt_lower and stats["total"] >= 2:
                candidates.append((agent, stats["success"] / stats["total"]))
        return max(candidates, key=lambda x: x[1])[0] if candidates else None

    def get_stats(self):
        return {"total_patterns": len(self._patterns), "logs_exist": os.path.exists(OUTCOMES_FILE)}
