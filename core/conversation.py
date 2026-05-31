import json, os
from datetime import datetime

CONV_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "conversations")

class ConversationManager:
    def __init__(self):
        os.makedirs(CONV_DIR, exist_ok=True)
        self._context = {}

    def add_message(self, uid, role, content):
        if uid not in self._context:
            self._context[uid] = []
        self._context[uid].append({"role": role, "content": content, "ts": datetime.now().isoformat()})
        if len(self._context[uid]) > 50:
            self._context[uid] = self._context[uid][-50:]
        json.dump(self._context[uid], open(os.path.join(CONV_DIR, f"session_{uid}.json"), "w"), indent=2)

    def get_history(self, uid, limit=15):
        filepath = os.path.join(CONV_DIR, f"session_{uid}.json")
        if os.path.exists(filepath):
            return json.load(open(filepath))[-limit:]
        return self._context.get(uid, [])[-limit:]

    def clear(self, uid):
        self._context[uid] = []
        filepath = os.path.join(CONV_DIR, f"session_{uid}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
