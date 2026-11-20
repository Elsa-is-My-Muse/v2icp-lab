import argparse
import hmac
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .lab import LabController
from .protocol import BACKEND_SIGNALS, VEHICLE_SIGNALS, ProtocolError


STATIC = Path(__file__).with_name("static")
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8")}


def signal_schema():
    return {group: {name: {"minimum": signal.minimum, "maximum": signal.maximum,
                           "sna": signal.sna, "resolution": signal.resolution}
                    for name, signal in signals.items()}
            for group, signals in (("vehicle", VEHICLE_SIGNALS), ("backend", BACKEND_SIGNALS))}


class LabHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, port=8765, controller=None):
        self.controller = controller or LabController()
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), LabHandler)
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}


class LabHandler(BaseHTTPRequestHandler):
    server_version = "V2ICPLab/0.1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_arguments):
        pass

    def reply(self, status, body, content_type="application/json; charset=utf-8", download=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self'; img-src 'self'; connect-src 'self'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="v2icp-lab-report.json"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted_host(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self.reply(403, {"error": "untrusted Host"})
            return False
        return True

    def do_GET(self):
        if not self.trusted_host():
            return
        if self.path in ASSETS:
            filename, content_type = ASSETS[self.path]
            body = (STATIC / filename).read_bytes()
            if self.path == "/":
                body = body.replace(b"__CSRF_TOKEN__", self.server.token.encode("ascii"))
            self.reply(200, body, content_type)
        elif self.path == "/api/state":
            self.reply(200, self.server.controller.snapshot())
        elif self.path == "/api/schema":
            self.reply(200, signal_schema())
        elif self.path == "/api/report":
            self.reply(200, self.server.controller.report(), download=True)
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.trusted_host():
            return
        origin = self.headers.get("Origin")
        allowed_origins = {"http://" + host for host in self.server.allowed_hosts}
        token = self.headers.get("X-Lab-Token", "")
        if (origin is not None and origin not in allowed_origins) or not hmac.compare_digest(
                token.encode("utf-8"), self.server.token.encode("ascii")):
            self.reply(403, {"error": "invalid origin or session token; reload the local page"})
            return
        length = self.headers.get("Content-Length", "")
        if (self.headers.get("Transfer-Encoding") or not length.isascii()
                or not length.isdecimal() or int(length) > 8192):
            self.reply(413, {"error": "expected Content-Length <= 8192"})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.reply(415, {"error": "expected application/json"})
            return
        controller = self.server.controller
        try:
            body = json.loads(self.rfile.read(int(length)))
            if not isinstance(body, dict):
                raise ProtocolError("JSON body must be an object")
            if self.path == "/api/start":
                controller.start(body)
            elif self.path == "/api/step":
                controller.step(body)
            elif self.path == "/api/stop":
                if body:
                    raise ProtocolError("stop expects an empty object")
                controller.stop()
            elif self.path == "/api/vehicle":
                controller.update_vehicle(body)
            elif self.path == "/api/backend":
                controller.update_backend(body)
            elif self.path == "/api/fault":
                if set(body) != {"fault"}:
                    raise ProtocolError("expected a fault name")
                controller.inject(body["fault"])
            else:
                self.reply(404, {"error": "not found"})
                return
            self.reply(200, controller.snapshot())
        except (ValueError, TypeError, KeyError) as exc:
            self.reply(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.reply(409, {"error": str(exc)})
        except OSError:
            self.reply(408, {"error": "local request timed out or disconnected"})

    def do_OPTIONS(self):
        self.reply(405, {"error": "cross-origin access is not supported"})


def main():
    parser = argparse.ArgumentParser(description="Local V2ICP Lab dashboard (loopback only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the local dashboard in a browser")
    arguments = parser.parse_args()
    if not 0 <= arguments.port <= 65535:
        parser.error("port must be in 0..65535")
    server = LabHTTPServer(arguments.port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"V2ICP Lab: {url}\nLocal simulation only. Press Ctrl+C to stop.", flush=True)
    if arguments.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.controller.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
