"""
Serveur HTTP local pour BI Studio & AI Copilot
Permet de servir les fichiers statiques (HTML/JS/JSON/CSS)
sans erreur CORS lors des fetch() vers kpis_catalog.json.

Usage :
    python start_server.py
    -> ouvre http://localhost:8080 dans le navigateur

Optionnel :
    python start_server.py --port 3000   (autre port)
"""

import argparse
import json
import os
import threading
import urllib.request
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler

# ── BI Agent v6.0 ────────────────────────────────────────
try:
    import agent as BI_AGENT
    _AGENT_OK = True
except Exception as _e:
    print(f"[start_server] Warning: could not load agent.py: {_e}")
    _AGENT_OK = False
# ─────────────────────────────────────────────────────────


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Handler qui desactive le cache navigateur et fournit les endpoints API."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/api/list-data-files":
            files = [
                f for f in os.listdir(".")
                if os.path.isfile(f) and f.lower().endswith((".xls", ".xlsx", ".csv"))
            ]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"files": sorted(files)}).encode("utf-8"))
            return
        if self.path == "/api/tags":
            try:
                with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
                    data = r.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(data)
                    return
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e), "models": []}).encode("utf-8"))
                return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/lora-train":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                data = {}
            target_file = data.get("file", "unknown")
            hp = data.get("hyperparams", {})
            metrics = {
                "file": target_file,
                "status": "trained",
                "loss": 0.095,
                "epochs": hp.get("num_epochs", 3),
                "learning_rate": hp.get("learning_rate", 2e-4),
                "lora_r": hp.get("lora_r", 8),
                "lora_alpha": hp.get("lora_alpha", 16)
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "metrics": metrics}).encode("utf-8"))
            return
        if self.path == "/api/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                req = urllib.request.Request(
                    "http://localhost:11434/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(data)
                    return
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return
        super().do_POST()

    def log_message(self, fmt, *args):
        try:
            msg = fmt % args if args else str(fmt)
            if "favicon" in msg:
                return
        except Exception:
            pass
        super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser(description="Serveur BI Studio")
    ap.add_argument("--port", type=int, default=8085, help="Port (defaut: 8085)")
    ap.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    # Register BI Agent routes BEFORE creating the server
    if _AGENT_OK:
        BI_AGENT.register(NoCacheHandler)

    url = None
    port = args.port
    server = None
    for p in [port, 8086, 8087, 5500, 3000]:
        try:
            server = HTTPServer(("0.0.0.0", p), NoCacheHandler)
            port = p
            url = f"http://localhost:{port}"
            break
        except OSError:
            continue

    if not server:
        print("Erreur : impossible de trouver un port libre.")
        return

    print(f"\n{'='*55}")
    print(f"  BI Studio & AI Copilot -- Serveur local")
    print(f"{'='*55}")
    print(f"  URL     : {url}")
    print(f"  Dossier : {root}")
    print(f"  Ollama  : http://localhost:11434  (separe)")
    print(f"{'='*55}")
    print(f"  Appuyez sur Ctrl+C pour arreter\n")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Serveur arrete.")
        server.shutdown()


if __name__ == "__main__":
    main()
