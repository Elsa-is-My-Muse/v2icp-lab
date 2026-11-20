import base64
import hmac
import http.client
import selectors
import socket
import socketserver
import ssl
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .protocol import (BACKEND_SIGNALS, CONTENT_TYPE, MAX_PAYLOAD, USER_AGENT,
                       ProtocolError, backend_values, decode_payload,
                       encode_payload, validate_request, validate_response)


CIPHER = "ECDHE-ECDSA-AES128-SHA256"


def tls_context(server=False, certificate=None, private_key=None, ca=None):
    purpose = ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH
    context = ssl.create_default_context(purpose, cafile=None if server else str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(CIPHER)
    if server:
        context.load_cert_chain(str(certificate), str(private_key))
    return context


class BackendState:
    def __init__(self, config):
        self.config = config
        self.vehicles = {}
        self.received = []
        self.events = []
        self.last_response = None
        self.drop_next = 0
        self.corrupt_seq_next = False
        self.corrupt_vin_next = False
        self.status_next = 200
        self.oversize_next = False
        self.fragment_response = False
        self.lock = threading.Lock()
        departure = config.get("departure_in_minutes")
        if departure is not None and (type(departure) not in (int, float)
                                      or not 0 <= departure <= 1440):
            raise ProtocolError("departure_in_minutes must be in 0..1440")
        self.departure = None if departure is None else time.monotonic() + departure * 60
        backend_values(config.get("backend", {}), self.departure, time.monotonic())

    def update_plan(self, values, departure_minutes):
        if departure_minutes is not None and (type(departure_minutes) not in (int, float)
                                              or not 0 <= departure_minutes <= 1440):
            raise ProtocolError("departure minutes must be in 0..1440 or null")
        unknown = set(values) - set(BACKEND_SIGNALS)
        if unknown:
            raise ProtocolError(f"unknown backend signals: {sorted(unknown)}")
        backend_values(values, None, time.monotonic())
        with self.lock:
            self.config["backend"] = dict(values)
            self.config["departure_in_minutes"] = departure_minutes
            self.departure = (None if departure_minutes is None
                              else time.monotonic() + departure_minutes * 60)

    def inject(self, fault):
        with self.lock:
            if fault == "drop":
                self.drop_next += 1
            elif fault == "wrong_seq":
                self.corrupt_seq_next = True
            elif fault == "wrong_vin":
                self.corrupt_vin_next = True
            elif fault == "http_503":
                self.status_next = 503
            elif fault == "oversize":
                self.oversize_next = True
            else:
                raise ProtocolError("unsupported fault")

    def answer(self, request, payload):
        with self.lock:
            self.received.append(payload)
            del self.received[:-400]
            snapshot = self.vehicles.setdefault(request["vin"], {})
            snapshot.update(request)
            if self.drop_next:
                self.drop_next -= 1
                return None
            response = {"seq": request["seq"], "vin": request["vin"]}
            response.update(backend_values(self.config.get("backend", {}), self.departure,
                                           time.monotonic()))
            if self.corrupt_seq_next:
                response["seq"] = (request["seq"] + 1) % 256
                self.corrupt_seq_next = False
            if self.corrupt_vin_next:
                response["vin"] = "WVWZZZ1JZXW000002"
                self.corrupt_vin_next = False
            status, self.status_next = self.status_next, 200
            body = encode_payload(response)
            if self.oversize_next:
                body = b" " * (MAX_PAYLOAD + 1)
                self.oversize_next = False
            self.last_response = response
            return status, body


class BackendHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *arguments):
        pass

    def reply(self, status, body=b"", close=False):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", CONTENT_TYPE)
        if status == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="v2icp-demo"')
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.server.state.fragment_response and body:
            for offset in range(0, len(body), 11):
                self.wfile.write(body[offset:offset + 11])
                self.wfile.flush()
        else:
            self.wfile.write(body)

    def do_POST(self):
        config = self.server.state.config
        if self.path != config["path"]:
            self.reply(404, close=True)
            return
        length = self.headers.get("Content-Length", "")
        if self.headers.get("Transfer-Encoding") or not length.isascii() or not length.isdecimal():
            self.reply(400, close=True)
            return
        length = int(length)
        if length > MAX_PAYLOAD:
            self.reply(413, close=True)
            return
        if self.headers.get("Content-Type", "").lower() != CONTENT_TYPE.lower():
            self.reply(415, close=True)
            return
        if config["password"]:
            expected = b"Basic " + base64.b64encode(
                (config["vin"] + ":" + config["password"]).encode("ascii"))
            actual = self.headers.get("Authorization", "").encode("ascii", errors="replace")
            if not hmac.compare_digest(actual, expected):
                self.reply(401, close=True)
                return
        payload = self.rfile.read(length)
        try:
            request = decode_payload(payload)
            validate_request(request)
            if request["vin"] != config["vin"]:
                raise ProtocolError("VIN is not registered in this demo backend")
        except ProtocolError:
            self.reply(400, close=True)
            return
        self.server.state.events.append({"tls": self.connection.version(),
                                         "cipher": self.connection.cipher()[0]})
        del self.server.state.events[:-400]
        result = self.server.state.answer(request, payload)
        if result is not None:
            self.reply(*result)


class BackendServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def __init__(self, address, state, context):
        self.state = state
        self.tls = context
        super().__init__(address, BackendHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(61)
        try:
            return self.tls.wrap_socket(connection, server_side=True), address
        except BaseException:
            connection.close()
            raise


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            upstream = socket.create_connection(self.server.target, timeout=5)
        except OSError:
            return
        with upstream, selectors.DefaultSelector() as selector:
            self.request.setblocking(False)
            upstream.setblocking(False)
            peers = {self.request: upstream, upstream: self.request}
            pending = {self.request: bytearray(), upstream: bytearray()}
            for stream in peers:
                selector.register(stream, selectors.EVENT_READ)
            last_io = time.monotonic()
            draining = False
            while not self.server.stopping.is_set():
                if time.monotonic() - last_io > 61:
                    return
                for key, mask in selector.select(timeout=0.1):
                    stream = key.fileobj
                    try:
                        if mask & selectors.EVENT_READ:
                            received = stream.recv(16384)
                            if not received:
                                draining = True
                            else:
                                pending[peers[stream]].extend(received)
                                direction = "to_backend" if stream is self.request else "to_vehicle"
                                with self.server.lock:
                                    self.server.transferred[direction] += len(received)
                            last_io = time.monotonic()
                        if mask & selectors.EVENT_WRITE and pending[stream]:
                            count = stream.send(pending[stream])
                            del pending[stream][:count]
                            last_io = time.monotonic()
                    except BlockingIOError:
                        continue
                    except OSError:
                        return
                    for candidate in peers:
                        events = 0
                        if not draining and len(pending[peers[candidate]]) < 65536:
                            events |= selectors.EVENT_READ
                        if pending[candidate]:
                            events |= selectors.EVENT_WRITE
                        registered = candidate in selector.get_map()
                        if events and registered:
                            selector.modify(candidate, events)
                        elif events:
                            selector.register(candidate, events)
                        elif registered:
                            selector.unregister(candidate)
                    if draining and not any(pending.values()):
                        return


class RelayServer(socketserver.ThreadingTCPServer):
    address_family = socket.AF_INET6
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, target):
        self.target = target
        self.stopping = threading.Event()
        self.transferred = {"to_backend": 0, "to_vehicle": 0}
        self.lock = threading.Lock()
        super().__init__(address, RelayHandler)


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    try:
        yield server
    finally:
        if isinstance(server, RelayServer):
            server.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class RoutedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, target, context, timeout=15, server_name="localhost"):
        self.target = target
        super().__init__(server_name, port=443, context=context, timeout=timeout)

    def connect(self):
        raw = socket.create_connection(self.target, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class EVCCClient:
    def __init__(self, config, target, ca, timeout=15, server_name="localhost", emit=None):
        self.config = config
        self.connection = RoutedHTTPSConnection(target, tls_context(ca=ca), timeout, server_name)
        self.emit = emit or (lambda event, **fields: None)
        self.inflight = None
        self.payload = None
        self.wire_request = None
        self.headers = None
        self.attempts = 0
        self.tls = None
        self.backend = {}

    def connect(self):
        self.connection.connect()
        self.tls = {"version": self.connection.sock.version(),
                    "cipher": self.connection.sock.cipher()[0]}
        self.emit("TLS_CONNECTED", **self.tls)

    def transmit(self, request):
        if self.inflight is not None:
            raise RuntimeError("one request is already outstanding")
        validate_request(request)
        payload = encode_payload(request)
        if self.connection.sock is None:
            self.connect()
        self.inflight = dict(request)
        self.payload = payload
        self.headers = {"Host": self.connection.host, "Accept-Encoding": "identity",
                        "Content-Length": str(len(payload)), "Content-Type": CONTENT_TYPE,
                        "User-Agent": USER_AGENT, "Connection": "keep-alive"}
        if self.config["password"]:
            credentials = (self.config["vin"] + ":" + self.config["password"]).encode("ascii")
            self.headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
        lines = [f"POST {self.config['path']} HTTP/1.1"]
        lines.extend(f"{name}: {value}" for name, value in self.headers.items())
        self.wire_request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + payload
        self.attempts = 0
        self.retransmit()

    def retransmit(self):
        if self.inflight is None:
            raise RuntimeError("nothing to retransmit")
        if self.attempts >= 3:
            raise TimeoutError("three unanswered attempts; close V2ICP connection")
        if self.attempts == 0:
            self.connection.request("POST", self.config["path"], self.payload, self.headers)
        else:
            self.connection.send(self.wire_request)
        self.attempts += 1
        self.emit("TX", attempt=self.attempts, payload=self.inflight)

    def receive(self):
        if self.inflight is None:
            raise RuntimeError("no outstanding request")
        try:
            response = self.connection.getresponse()
        except socket.timeout:
            self.emit("TIMEOUT", attempt=self.attempts)
            raise
        body = response.read(MAX_PAYLOAD + 1)
        request = self.inflight
        self.inflight = None
        if len(body) > MAX_PAYLOAD:
            self.close()
            raise ProtocolError("response payload exceeds 512 bytes")
        if response.status != 200:
            raise ProtocolError(f"HTTP status {response.status}, expected 200")
        message = decode_payload(body)
        validate_response(message, request)
        self.backend.update({name: message[name] for name in BACKEND_SIGNALS if name in message})
        self.emit("RX", payload=message)
        return message

    def exchange(self, request):
        self.transmit(request)
        return self.receive()

    def close(self):
        self.connection.close()
        self.inflight = None
