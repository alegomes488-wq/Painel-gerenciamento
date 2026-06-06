import json, os
from core.state import CyberCoreState

AGENT_KEYWORDS = [
    ("java_core",   ["java","spring","maven","gradle","android","jar","jvm","kotlin","hibernate","apk","sign","assinar"]),
    ("software",    ["software","desktop","programa","aplicativo","executavel","windows","linux","mac"]),
    ("fiscal",      ["imposto","nota","nf","nfe","fiscal","tributo","contabilidade","saque","retirada","extrato","financeiro"]),
    ("sentinel",    ["seguranca","segurança","varredura","scan","sentinel","ameaca","ameaça","invasao","invasão","virus","malware","firewall"]),
    ("auditor",     ["auditar","auditoria","verificar","logs","conferir","check","compliance","auditor"]),
    ("designer",    ["design","ui","ux","layout","interface","criativo","visual","tema","cores","logo","estilo"]),
    ("fullstack",   ["fullstack","completo","api","crud","rest","backend","frontend","web","react","vue","angular"]),
    ("python_core", ["criar","crie","cria","construir","construa","landing","site","pagina","página","html","css","js","app","sistema","gerar","gere","projeto","python","script","automacao","bot","django","flask","fastapi","scraping"]),
]

LEARNING_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "learning", "preferences.json")

class Router:
    def __init__(self):
        self.state = CyberCoreState()

    def analyze_intent(self, prompt):
        prompt_l = prompt.lower()
        if any(w in prompt_l for w in ["criar","crie","construir","gerar","fazer"]):
            return "criacao"
        if any(w in prompt_l for w in ["continuar","seguir","prosseguir","continue"]):
            return "continuacao"
        if any(w in prompt_l for w in ["analisar","analise","verificar","checar"]):
            return "analise"
        if any(w in prompt_l for w in ["monitor","status","saude","health"]):
            return "monitoramento"
        if any(w in prompt_l for w in ["corrigir","arrumar","consertar","fix"]):
            return "correcao"
        return "geral"

    def decide(self, prompt, uid=None, learning_engine=None):
        prompt_lower = prompt.lower()
        if learning_engine:
            learned = learning_engine.best_agent_for(prompt)
            if learned:
                return {"agent": learned, "confidence": "learned", "reason": "Aprendizado anterior"}

        best_agent = None
        best_score = 0
        best_matched = []
        for agent, keywords in AGENT_KEYWORDS:
            matched = [k for k in keywords if k in prompt_lower]
            if matched and len(matched) > best_score:
                best_score = len(matched)
                best_agent = agent
                best_matched = matched

        if best_agent:
            return {"agent": best_agent, "confidence": "high" if best_score >= 2 else "medium", "reason": f"Keywords: {best_matched}"}

        return {"agent": "python_core", "confidence": "low", "reason": "Fallback padrao"}
