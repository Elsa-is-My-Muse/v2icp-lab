import copy
import json
import math
import socket
import threading
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from .certificates import generate
from .network import BackendServer, BackendState, EVCCClient, RelayServer, running, tls_context
from .protocol import BACKEND_SIGNALS, ProtocolError, VehicleSnapshot


ROOT = Path(__file__).resolve().parents[1]


def _redact(value, identities=()):
    if isinstance(value, dict):
        return {name: ("DEMO_VIN_REDACTED" if name == "vin" else
                       "MAC_REDACTED" if name == "evccid" else _redact(content, identities))
                for name, content in value.items() if name not in ("password", "authorization")}
    if isinstance(value, list):
        return [_redact(content, identities) for content in value]
    if isinstance(value, str):
        for identity in identities:
            if identity:
                value = value.replace(identity, "REDACTED")
    return value


class LabController:
    def __init__(self, config_path=None, cert_dir=None):
        self.config = json.loads(Path(config_path or ROOT / "demo" / "config.json")
                                 .read_text(encoding="utf-8-sig"))
        self.cert_dir = Path(cert_dir or ROOT / ".demo_certs")
        self.lock = threading.RLock()
        self.lifecycle = threading.Lock()
        self.stop_event = threading.Event()
        self.step_event = threading.Event()
        self.thread = None
        self.client = None
        self.backend = None
        self.relay = None
        self.events = deque(maxlen=400)
        self.event_id = 0
        self._reset()

    def _reset(self):
        self.client = self.backend = self.relay = None
        self.status = "idle"
        self.error = None
        self.sequence = 0
        self.interval = 1.0
        self.timeout = 2.0
        self.automatic = True
        self.tx_count = self.rx_count = self.retries = self.rejected = 0
        self.last_tx = self.last_rx = self.latency_ms = None
        self.last_send = None
        self.physical = {}
        self.tls = None
        self.topology = {}
        self.started = None
        self.retained = {}

    def _emit(self, event, **fields):
        with self.lock:
            self.event_id += 1
            self.events.append({"id": self.event_id, "event": event,
                                "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                                **copy.deepcopy(fields)})
            if event == "TLS_CONNECTED":
                self.tls = fields
            elif event == "TX":
                self.tx_count += 1
                self.retries += int(fields["attempt"] > 1)
                self.last_tx = copy.deepcopy(fields["payload"])
                self.last_send = time.monotonic()
            elif event == "RX":
                self.rx_count += 1
                self.last_rx = copy.deepcopy(fields["payload"])
                self.latency_ms = round((time.monotonic() - self.last_send) * 1000, 1)

    def start(self, options=None):
        options = options or {}
        if not isinstance(options, dict) or set(options) - {"interval", "timeout", "automatic"}:
            raise ProtocolError("unsupported start options")
        interval = options.get("interval", 1)
        timeout = options.get("timeout", 2)
        automatic = options.get("automatic", True)
        for name, value, low, high in (("interval", interval, 0.1, 60),
                                       ("timeout", timeout, 0.1, 30)):
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ProtocolError(f"{name} must be in {low}..{high}")
        if type(automatic) is not bool:
            raise ProtocolError("automatic must be boolean")
        with self.lifecycle:
            if self.thread and self.thread.is_alive():
                raise ProtocolError("the lab is already active; stop it before restarting")
            with self.lock:
                self._reset()
                self.events.clear()
                self.interval, self.timeout, self.automatic = interval, timeout, automatic
                self.status = "starting"
                self.started = time.monotonic()
                self.stop_event.clear()
                self.step_event.clear()
            self.thread = threading.Thread(target=self._run, name="v2icp-lab", daemon=True)
            self.thread.start()
        return self.snapshot()

    def step(self, options=None):
        with self.lock:
            active = self.status in ("starting", "running")
            automatic = self.automatic
        if not active:
            self.start({**(options or {}), "automatic": False})
        elif automatic:
            raise ProtocolError("stop automatic mode before using single-step")
        self.step_event.set()

    def stop(self):
        with self.lifecycle:
            self.stop_event.set()
            self.step_event.set()
            with self.lock:
                if self.status in ("starting", "running"):
                    self.status = "stopping"
                client = self.client
            if client and client.connection.sock:
                try:
                    client.connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if self.thread:
                self.thread.join(timeout=8)
            if self.thread and self.thread.is_alive():
                raise RuntimeError("lab is still stopping; wait before restarting")
        return self.snapshot()

    def update_vehicle(self, values):
        if not isinstance(values, dict):
            raise ProtocolError("vehicle update must be an object")
        with self.lock:
            vehicle = VehicleSnapshot(self.config["vin"], self.config["evccid"],
                                      self.config.get("vehicle"))
            vehicle.update(values)
            self.config["vehicle"] = vehicle.values
        self._emit("VEHICLE_UPDATED", values=values)

    def update_backend(self, body):
        if not isinstance(body, dict) or set(body) - {"values", "departure_in_minutes"}:
            raise ProtocolError("invalid backend update")
        values = body.get("values", {})
        if not isinstance(values, dict) or set(values) - (set(BACKEND_SIGNALS) - {"driveoff"}):
            raise ProtocolError("use departure_in_minutes instead of raw driveoff")
        with self.lock:
            plan = {**self.config["backend"], **values}
            departure = body.get("departure_in_minutes", self.config["departure_in_minutes"])
            candidate = copy.deepcopy(self.config)
            candidate["backend"], candidate["departure_in_minutes"] = plan, departure
            BackendState(candidate)
            self.config.update(backend=plan, departure_in_minutes=departure)
            if self.backend:
                self.backend.update_plan(plan, departure)
        self._emit("BACKEND_UPDATED", values=values, departure_in_minutes=departure)

    def inject(self, fault):
        with self.lock:
            if self.backend is None or self.status != "running":
                raise ProtocolError("start the lab before injecting a fault")
            self.backend.inject(fault)
        self._emit("FAULT_ARMED", fault=fault)

    def _run(self):
        try:
            certificates = generate(self.cert_dir)
            if self.stop_event.is_set():
                return
            context = tls_context(server=True, certificate=certificates / "server.pem",
                                  private_key=certificates / "server.key")
            with ExitStack() as resources:
                with self.lock:
                    backend_state = BackendState(copy.deepcopy(self.config))
                    self.backend = backend_state
                backend = resources.enter_context(running(BackendServer(("::1", 0), backend_state, context)))
                relay = resources.enter_context(running(RelayServer(("::1", 0), ("::1", backend.server_port))))
                client = EVCCClient(self.config, ("::1", relay.server_address[1]),
                                    certificates / "ca.pem", timeout=self.timeout, emit=self._emit)
                resources.callback(client.close)
                with self.lock:
                    self.client, self.relay = client, relay
                    self.topology = {"relay_port": relay.server_address[1],
                                     "backend_port": backend.server_port, "host": "::1"}
                vehicle = VehicleSnapshot(self.config["vin"], self.config["evccid"])
                client.connect()
                with self.lock:
                    self.status = "stopping" if self.stop_event.is_set() else "running"
                self._emit("SESSION_STARTED", automatic=self.automatic,
                           interval=self.interval, timeout=self.timeout)
                while not self.stop_event.is_set():
                    if not self.automatic:
                        self.step_event.wait()
                        self.step_event.clear()
                        if self.stop_event.is_set():
                            break
                    with self.lock:
                        vehicle.update(self.config["vehicle"])
                        request = vehicle.request(self.sequence)
                    client.transmit(request)
                    vehicle.record_sent(request)
                    try:
                        while not self.stop_event.is_set():
                            try:
                                client.receive()
                                break
                            except socket.timeout:
                                if client.attempts >= 3:
                                    raise RuntimeError("three unanswered attempts; lab session stopped")
                                client.retransmit()
                        with self.lock:
                            self.physical = {name: BACKEND_SIGNALS[name].physical(name, value)
                                             for name, value in client.backend.items()}
                    except ProtocolError as exc:
                        with self.lock:
                            self.rejected += 1
                        self._emit("RESPONSE_REJECTED", message=str(exc))
                        if client.connection.sock is None:
                            raise RuntimeError("response too large; connection closed, restart the lab") from exc
                    with self.lock:
                        self.sequence = (self.sequence + 1) % 256
                        with backend_state.lock:
                            self.retained = dict(backend_state.vehicles.get(self.config["vin"], {}))
                    if self.automatic and self.stop_event.wait(self.interval):
                        break
        except Exception as exc:
            if not self.stop_event.is_set():
                with self.lock:
                    self.error = str(exc)
                    self.status = "error"
                self._emit("ERROR", message=str(exc))
        finally:
            with self.lock:
                if self.status != "error":
                    self.status = "stopped"
                self.client = self.backend = None
            self._emit("SESSION_ENDED")

    def snapshot(self):
        with self.lock:
            relay_bytes = dict(self.relay.transferred) if self.relay else {"to_backend": 0, "to_vehicle": 0}
            safe_config = {name: copy.deepcopy(self.config[name]) for name in
                           ("vin", "evccid", "path", "vehicle", "backend", "departure_in_minutes")}
            return {"status": self.status, "error": self.error, "sequence": self.sequence,
                    "automatic": self.automatic, "interval": self.interval, "timeout": self.timeout,
                    "tx_count": self.tx_count, "rx_count": self.rx_count, "retries": self.retries,
                    "rejected": self.rejected, "latency_ms": self.latency_ms,
                    "relay_bytes": relay_bytes, "tls": copy.deepcopy(self.tls),
                    "last_tx": copy.deepcopy(self.last_tx), "last_rx": copy.deepcopy(self.last_rx),
                    "physical": dict(self.physical), "backend_snapshot": dict(self.retained),
                    "topology": dict(self.topology), "config": safe_config,
                    "events": copy.deepcopy(list(self.events))}

    def report(self):
        return {"project": "V2ICP Lab", "version": "0.1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "scope": "local IPv6/TLS/HTTP lab, not hardware or conformity certification",
                "identities_redacted": True,
                "state": _redact(self.snapshot(), (self.config["vin"], self.config["evccid"],
                                                   self.config["password"]))}
