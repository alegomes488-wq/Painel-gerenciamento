import json, os, threading

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "state.json")

class CyberCoreState:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data = {
            "current_project": None,
            "active_agent": None,
            "running_tasks": [],
            "system_status": "idle",
            "mode": "USER",
            "last_activity": None,
            "agents_online": [],
        }
        self._load()

    def _load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    self._data.update(json.load(f))
            except:
                pass

    def _save(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._save()

    def update(self, data):
        self._data.update(data)
        self._save()

    @property
    def all(self):
        return dict(self._data)
