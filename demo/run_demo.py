import argparse
import json
import socket
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from .certificates import generate
from .network import BackendServer, BackendState, EVCCClient, RelayServer, running, tls_context
from .protocol import BACKEND_SIGNALS, VehicleSnapshot


def load_config(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def main(argv=None):
    parser = argparse.ArgumentParser(description="IPv6/TLS V2ICP learning demo")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--cert-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / ".demo_certs")
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument("--backend-port", type=int, default=0)
    parser.add_argument("--relay-port", type=int, default=0)
    parser.add_argument("--report", type=Path,
                        default=Path(__file__).resolve().parents[1] / "output" / "demo_report.json")
    arguments = parser.parse_args(argv)
    if arguments.interval < 0 or arguments.timeout <= 0 or arguments.cycles < 1:
        parser.error("interval >= 0, timeout > 0 and cycles >= 1 are required")
    config = load_config(arguments.config)
    certificates = generate(arguments.cert_dir)
    events = []
    started = time.monotonic()

    def emit(event, **fields):
        events.append({"event": event, "elapsed_seconds": time.monotonic() - started, **fields})
        print(f"[EVCC] {event} {json.dumps(fields, ensure_ascii=True)}", flush=True)

    context = tls_context(server=True, certificate=certificates / "server.pem",
                          private_key=certificates / "server.key")
    state = BackendState(config)
    with ExitStack() as resources:
        backend = resources.enter_context(running(BackendServer(("::1", arguments.backend_port),
                                                                state, context)))
        relay = resources.enter_context(running(RelayServer(("::1", arguments.relay_port),
                                                            ("::1", backend.server_port))))
        relay_port = relay.server_address[1]
        print(f"[TOPOLOGY] EVCC -> SECC relay [::1]:{relay_port} -> backend [::1]:{backend.server_port}")
        print("[SCOPE] Real IPv6/TLS/HTTP; PLC, ISO 15118 VAS and vehicle CAN are simulated.")
        print("[SECURITY] EVCC validates the backend certificate; relay has no certificate or key.")
        print("[PORTS] Ephemeral loopback ports for local testing, not production port 443.")
        print(f"[TIMING] interval={arguments.interval}s timeout={arguments.timeout}s")
        client = EVCCClient(config, ("::1", relay_port), certificates / "ca.pem",
                            timeout=arguments.timeout, emit=emit)
        resources.callback(client.close)
        vehicle = VehicleSnapshot(config["vin"], config["evccid"], config.get("vehicle"))
        responses = []
        for sequence in range(arguments.cycles):
            if sequence:
                time.sleep(arguments.interval)
            if sequence == 2:
                vehicle.update({"chrg_stat": 3})
                print("[VEHICLE] simulated chrg_stat -> 3 (charging and preconditioning)")
            request = vehicle.request(sequence % 256)
            client.transmit(request)
            vehicle.record_sent(request)
            while True:
                try:
                    response = client.receive()
                    break
                except socket.timeout:
                    if client.attempts >= 3:
                        client.close()
                        raise TimeoutError("three unanswered attempts; demo stops without firmware reconnect")
                    client.retransmit()
            physical = {name: BACKEND_SIGNALS[name].physical(name, value)
                        for name, value in client.backend.items()}
            print("[VEHICLE] accepted physical values: " + json.dumps(physical))
            print("[VEHICLE] demonstration only: no real BMS/HVAC commands are executed.")
            responses.append(response)
        client.close()
        report = {"scope": "local IPv6 + TLS + HTTP + transparent relay demonstration",
                  "not_conformance_certification": True, "tls": client.tls,
                  "cycles": len(responses), "interval_seconds": arguments.interval,
                  "timeout_seconds": arguments.timeout, "relay_bytes": relay.transferred,
                  "vehicle_snapshot_on_backend": state.vehicles,
                  "accepted_backend": client.backend, "events": events}
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[PASS] {len(responses)} request/response cycles; report: {arguments.report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
