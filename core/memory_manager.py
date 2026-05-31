import json, os, time
from datetime import datetime

MEMORY_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory")

class MemoryManager:
    def store(self, uid, prompt, result, decision=None):
        entry = {"uid": uid, "prompt": prompt, "result": result, "decision": decision, "timestamp": datetime.now().isoformat()}
        conv_dir = os.path.join(MEMORY_BASE, "conversations")
        os.makedirs(conv_dir, exist_ok=True)
        with open(os.path.join(conv_dir, f"{uid}_{int(time.time())}.json"), "w") as f:
            json.dump(entry, f, indent=2)
        lt_dir = os.path.join(MEMORY_BASE, "long_term")
        os.makedirs(lt_dir, exist_ok=True)
        lt_path = os.path.join(lt_dir, f"{uid}_resumo.json")
        summary = {"prompt": prompt[:100], "agent": decision.get("agent") if decision else None, "ts": entry["timestamp"]}
        existing = json.load(open(lt_path)) if os.path.exists(lt_path) else []
        existing.append(summary)
        json.dump(existing[-100:], open(lt_path, "w"), indent=2)

    def search(self, query, uid=None, limit=5):
        conv_dir = os.path.join(MEMORY_BASE, "conversations")
        if not os.path.exists(conv_dir): return []
        query_lower = query.lower(); results = []
        for f in sorted(os.listdir(conv_dir), reverse=True):
            if uid and not f.startswith(uid): continue
            try:
                entry = json.load(open(os.path.join(conv_dir, f)))
                if query_lower in entry.get("prompt","").lower():
                    results.append(entry)
                    if len(results) >= limit: break
            except: continue
        return results

    def load_project_context(self, name):
        proj_dir = os.path.join(MEMORY_BASE, "projects")
        if not os.path.exists(proj_dir): return None
        name_lower = name.lower()
        for f in os.listdir(proj_dir):
            if name_lower in f.lower():
                return json.load(open(os.path.join(proj_dir, f)))
        return None

    def save_project_context(self, name, data):
        proj_dir = os.path.join(MEMORY_BASE, "projects")
        os.makedirs(proj_dir, exist_ok=True)
        json.dump(data, open(os.path.join(proj_dir, f"{name.replace(' ','_')}.json"), "w"), indent=2)

    def recall(self, uid, limit=10):
        conv_dir = os.path.join(MEMORY_BASE, "conversations")
        if not os.path.exists(conv_dir): return []
        results = []
        for f in sorted([f for f in os.listdir(conv_dir) if f.startswith(uid)], reverse=True)[:limit]:
            try: results.append(json.load(open(os.path.join(conv_dir, f))))
            except: continue
        return results

    def stats(self):
        def count(d): return len(os.listdir(d)) if os.path.exists(d) else 0
        return {"conversations": count(os.path.join(MEMORY_BASE, "conversations")), "projects": count(os.path.join(MEMORY_BASE, "projects")), "long_term": count(os.path.join(MEMORY_BASE, "long_term"))}
