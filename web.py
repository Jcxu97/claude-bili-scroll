"""The web page. serve runs it in a thread; it reads files in the data folder and queues actions for serve.

Standard library only. Log in with the password in [web]. Bind it to a private address (a Tailscale IP or
127.0.0.1), not to a public one.
"""
import hmac
import json
import os
import re
import secrets
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).resolve().parent / "web"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".webp": "image/webp", ".svg": "image/svg+xml"}
FOLDERS = ("journal", "out", "inbox", "digest")
ACTIONS = {"browse", "inbox", "pause", "resume", "dryrun", "doctor", "daily"}
NAME = re.compile(r"^[\w.-]+\.md$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def start(srv, app, web_cfg):
    sessions, fails = {}, []
    ws = srv.ws

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, ctype="application/json; charset=utf-8", headers=()):
            data = body if isinstance(body, bytes) else (
                body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8"))
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def authed(self):
            m = re.search(r"(?:^|;\s*)cbs=([\w-]+)", self.headers.get("Cookie", ""))
            return bool(m) and sessions.get(m.group(1), 0) > time.time()

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(min(n, 1 << 20)).decode("utf-8") if n else ""

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PUT(self):
            self.route("PUT")

        def route(self, method):
            url = urlparse(self.path)
            path, q = url.path, parse_qs(url.query)
            try:
                if not path.startswith("/api/"):
                    return self.static(path) if method == "GET" else self.send(405, {"error": "method"})
                # A page on another site cannot add this header without a CORS preflight, which we never allow.
                if method != "GET" and self.headers.get("X-CBS") != "1":
                    return self.send(403, {"error": "missing header"})
                if path == "/api/login" and method == "POST":
                    return self.login()
                if not self.authed():
                    return self.send(401, {"error": "login"})
                return self.api(method, path, q)
            except Exception as e:
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})

        def static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (STATIC / rel).resolve()
            if STATIC not in f.parents or not f.is_file() or f.suffix not in TYPES:
                return self.send(404, "not found", "text/plain; charset=utf-8")
            self.send(200, f.read_bytes(), TYPES[f.suffix])

        def login(self):
            now = time.time()
            fails[:] = [t for t in fails if now - t < 600]
            if len(fails) >= 5:
                return self.send(429, {"error": "试错太多次了，十分钟后再来"})
            given = str((json.loads(self.body() or "{}")).get("password", ""))
            password = app.load_config(srv.config)["web"]["password"]
            if not password or not hmac.compare_digest(given.encode("utf-8"), str(password).encode("utf-8")):
                fails.append(now)
                return self.send(403, {"error": "密码不对"})
            token = secrets.token_urlsafe(32)
            sessions[token] = now + 30 * 86400
            self.send(200, {"ok": True}, headers=[(
                "Set-Cookie", f"cbs={token}; Path=/; Max-Age={30 * 86400}; HttpOnly; SameSite=Strict")])

        def api(self, method, path, q):
            parts = path.split("/")[2:]
            if path == "/api/logout" and method == "POST":
                m = re.search(r"(?:^|;\s*)cbs=([\w-]+)", self.headers.get("Cookie", ""))
                sessions.pop(m.group(1) if m else "", None)
                return self.send(200, {"ok": True})
            if path == "/api/status":
                return self.send(200, srv.snapshot())
            if path == "/api/chat":
                days = int((q.get("days") or ["14"])[0])
                return self.send(200, app.life.read_chat(ws / "chat.jsonl", min(max(days, 1), 365)))
            if parts[0] == "files" and len(parts) in (2, 3) and parts[1] in FOLDERS:
                folder = ws / parts[1]
                if len(parts) == 2:
                    names = sorted((p.name for p in folder.glob("*.md")), reverse=True) if folder.exists() else []
                    return self.send(200, names)
                if not NAME.match(parts[2]) or not (folder / parts[2]).is_file():
                    return self.send(404, {"error": "没有这个文件"})
                return self.send(200, {"text": (folder / parts[2]).read_text(encoding="utf-8")})
            if parts[0] == "memory":
                if method == "GET" and len(parts) == 1:
                    mem = ws / "memory"
                    return self.send(200, {n: (mem / n).read_text(encoding="utf-8") if (mem / n).exists() else ""
                                           for n in app.MEMORY_FILES})
                if method == "PUT" and len(parts) == 2 and parts[1] in app.MEMORY_FILES:
                    (ws / "memory").mkdir(exist_ok=True)
                    write_text(ws / "memory" / parts[1], json.loads(self.body())["text"])
                    return self.send(200, {"ok": True})
            if path == "/api/config":
                cfg_file = Path(srv.config)
                if method == "GET":
                    return self.send(200, {"text": cfg_file.read_text(encoding="utf-8") if cfg_file.exists() else ""})
                if method == "PUT":
                    text = json.loads(self.body())["text"]
                    try:
                        tomllib.loads(text)
                    except tomllib.TOMLDecodeError as e:
                        return self.send(400, {"error": f"格式不对，没有保存：{e}"})
                    write_text(cfg_file, text)
                    return self.send(200, {"ok": True})
            if path == "/api/logs":
                logs = ws / "logs"
                days = sorted((p.stem for p in logs.glob("*.log") if DAY.match(p.stem)), reverse=True)
                day = (q.get("day") or [days[0] if days else ""])[0]
                f = logs / f"{day}.log"
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-600:] if DAY.match(day) and f.exists() else []
                return self.send(200, {"days": days[:30], "day": day, "lines": lines})
            if path == "/api/action" and method == "POST":
                action = json.loads(self.body()).get("action")
                if action not in ACTIONS:
                    return self.send(400, {"error": "不认识的操作"})
                srv.request(action)
                return self.send(200, {"ok": True})
            if path == "/api/qr/start" and method == "POST":
                import qrcode
                from qrcode.image.svg import SvgPathImage
                url, key = app.login_start()
                svg = qrcode.make(url, image_factory=SvgPathImage, border=2).to_string().decode("utf-8")
                return self.send(200, {"key": key, "svg": svg})
            if path == "/api/qr/poll" and method == "POST":
                key = str(json.loads(self.body()).get("key", ""))
                return self.send(200, {"result": app.login_poll(app.load_config(srv.config), key)})
            return self.send(404, {"error": "没有这个接口"})

    httpd = ThreadingHTTPServer((web_cfg["host"], int(web_cfg["port"])), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def write_text(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
