"""
Servidor HTTP de desenvolvimento para o Painel Admin CyberCore IA
Inclui headers CORS para permitir comunicação com backend em porta diferente
"""
import http.server
import socketserver
import os
import sys

PORT = int(os.environ.get("ADMIN_PORT", 8080))
ADMIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www", "admin")

if not os.path.isdir(ADMIN_DIR):
    print(f"[ERRO] Pasta admin não encontrada em: {ADMIN_DIR}")
    sys.exit(1)

os.chdir(ADMIN_DIR)

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    """Handler com suporte a CORS para desenvolvimento local"""

    def end_headers(self):
        # Headers CORS para permitir requisições do backend (porta 7861)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def do_OPTIONS(self):
        """Responde a requisições OPTIONS (CORS preflight)"""
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        """Serve arquivos estáticos com logging"""
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok","service":"admin-panel"}')
            return
        super().do_GET()

    def log_message(self, format, *args):
        print(f"[Admin:{PORT}] {args[0]} {args[1]} {args[2]}")

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), CORSHandler) as httpd:
        print(f"[+] Admin Panel servindo em http://localhost:{PORT}")
        print(f"[+] Pasta: {ADMIN_DIR}")
        print(f"[+] Health check: http://localhost:{PORT}/health")
        print(f"[+] CORS habilitado para desenvolvimento")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[+] Servidor encerrado.")
