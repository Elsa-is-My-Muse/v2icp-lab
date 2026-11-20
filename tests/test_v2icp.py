import copy
import json
import socket
import ssl
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path

from demo.certificates import generate
from demo.network import (CIPHER, BackendServer, BackendState, EVCCClient, RelayServer,
                          running, tls_context)
from demo.protocol import (BACKEND_SIGNALS, MAX_PAYLOAD, VEHICLE_SIGNALS, ProtocolError,
                           VehicleSnapshot, backend_values, decode_payload,
                           encode_payload, validate_request)


CONFIG_PATH = Path(__file__).resolve().parents[1] / "demo" / "config.json"


def configuration():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def snapshot(config=None):
    config = config or configuration()
    return VehicleSnapshot(config["vin"], config["evccid"], config["vehicle"])


class ProtocolTests(unittest.TestCase):
    def test_seq_zero_contains_every_vehicle_signal(self):
        self.assertTrue(set(VEHICLE_SIGNALS) <= snapshot().request(0).keys())

    def test_unavailable_vehicle_signals_are_sna_not_ok(self):
        request = VehicleSnapshot(configuration()["vin"], configuration()["evccid"]).request(0)
        self.assertTrue(all(request[name] == -1 for name in VEHICLE_SIGNALS))

    def test_unchanged_request_still_has_identity_and_safety(self):
        vehicle = snapshot()
        vehicle.record_sent(vehicle.request(0))
        self.assertEqual(set(vehicle.request(1)), {"seq", "vin", "evccid", "h2_stat", "bat_stat"})

    def test_only_changed_signals_added(self):
        vehicle = snapshot()
        vehicle.record_sent(vehicle.request(0))
        vehicle.update({"chrg_stat": 3})
        self.assertEqual(set(vehicle.request(1)),
                         {"seq", "vin", "evccid", "chrg_stat", "h2_stat", "bat_stat"})

    def test_sequence_wrap_zero_is_full_again(self):
        vehicle = snapshot()
        vehicle.record_sent(vehicle.request(255))
        self.assertTrue(set(VEHICLE_SIGNALS) <= vehicle.request((255 + 1) % 256).keys())

    def test_new_connection_resets_snapshot(self):
        vehicle = snapshot()
        vehicle.record_sent(vehicle.request(0))
        vehicle.new_connection()
        self.assertTrue(set(VEHICLE_SIGNALS) <= vehicle.request(0).keys())

    def test_backend_signal_cannot_be_written_as_vehicle_signal(self):
        with self.assertRaises(ProtocolError):
            snapshot().update({"target_soc": 80})

    def test_invalid_signal_range_rejected(self):
        with self.assertRaises(ProtocolError):
            snapshot().update({"chrg_stat": 5})

    def test_boolean_not_accepted_as_integer(self):
        with self.assertRaises(ProtocolError):
            snapshot().update({"bat_stat": True})

    def test_driveoff_raw_twelve_is_sixty_minutes(self):
        self.assertEqual(BACKEND_SIGNALS["driveoff"].physical("driveoff", 12), 60)

    def test_driveoff_maximum_raw_is_288(self):
        self.assertEqual(BACKEND_SIGNALS["driveoff"].physical("driveoff", 288), 1440)
        with self.assertRaises(ProtocolError):
            BACKEND_SIGNALS["driveoff"].validate("driveoff", 1440)

    def test_temperature_minus_one_is_not_sna(self):
        signal = BACKEND_SIGNALS["ambienttemp"]
        self.assertEqual(signal.physical("ambienttemp", -1), -1)
        self.assertIsNone(signal.physical("ambienttemp", -51))

    def test_backend_decrements_departure_countdown(self):
        self.assertEqual(backend_values({}, 3600, 0)["driveoff"], 12)
        self.assertEqual(backend_values({}, 3600, 300)["driveoff"], 11)
        self.assertEqual(backend_values({}, 3600, 4000)["driveoff"], 0)

    def test_json_has_no_unnecessary_whitespace(self):
        self.assertEqual(encode_payload({"seq": 0, "vin": "ABC"}), b'{"seq":0,"vin":"ABC"}')

    def test_unknown_fields_ignored(self):
        request = snapshot().request(0)
        request["future_signal"] = {"value": 1}
        validate_request(request)

    def test_uppercase_keys_accepted(self):
        request = snapshot().request(0)
        decoded = decode_payload(encode_payload({name.upper(): value for name, value in request.items()}))
        validate_request(decoded)

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ProtocolError):
            decode_payload(b'{"seq":0,"SEQ":1}')

    def test_multiple_json_objects_rejected(self):
        with self.assertRaises(ProtocolError):
            decode_payload(b'{}{}')

    def test_array_payload_rejected(self):
        with self.assertRaises(ProtocolError):
            decode_payload(b'[]')

    def test_nan_rejected(self):
        with self.assertRaises(ProtocolError):
            decode_payload(b'{"future":NaN}')

    def test_oversized_payload_rejected(self):
        with self.assertRaises(ProtocolError):
            decode_payload(b" " * (MAX_PAYLOAD + 1))

    def test_missing_battery_safety_rejected(self):
        request = snapshot().request(0)
        del request["bat_stat"]
        with self.assertRaises(ProtocolError):
            validate_request(request)

    def test_missing_initial_parameter_rejected(self):
        request = snapshot().request(0)
        del request["odo"]
        with self.assertRaises(ProtocolError):
            validate_request(request)


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="v2icp-test-")
        cls.certificates = generate(Path(cls.directory.name) / "certificates")
        cls.wrong_certificates = generate(Path(cls.directory.name) / "untrusted")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.config = configuration()
        self.state = BackendState(self.config)
        context = tls_context(server=True, certificate=self.certificates / "server.pem",
                              private_key=self.certificates / "server.key")
        self.backend = self.resources.enter_context(running(BackendServer(("::1", 0), self.state, context)))
        self.relay = self.resources.enter_context(running(RelayServer(("::1", 0), ("::1", self.backend.server_port))))

    def client(self, config=None, ca=None, **keywords):
        client = EVCCClient(config or self.config, ("::1", self.relay.server_address[1]),
                            ca or self.certificates / "ca.pem", **keywords)
        self.resources.callback(client.close)
        return client

    def test_real_ipv6_tls_exchange_via_relay(self):
        client = self.client()
        response = client.exchange(snapshot().request(0))
        self.assertEqual(response["target_soc"], 80)
        self.assertEqual(client.tls, {"version": "TLSv1.2", "cipher": CIPHER})
        self.assertGreater(self.relay.transferred["to_backend"], 0)
        self.assertGreater(self.relay.transferred["to_vehicle"], 0)

    def test_three_rounds_share_same_tls_connection(self):
        client, vehicle = self.client(), snapshot()
        connection = None
        for sequence in range(3):
            request = vehicle.request(sequence)
            client.exchange(request)
            vehicle.record_sent(request)
            if connection is None:
                connection = client.connection.sock
            self.assertIs(client.connection.sock, connection)
        self.assertEqual(len(self.state.received), 3)

    def test_backend_merges_delta_requests(self):
        client, vehicle = self.client(), snapshot()
        request = vehicle.request(0)
        client.exchange(request)
        vehicle.record_sent(request)
        vehicle.update({"chrg_stat": 3})
        client.exchange(vehicle.request(1))
        saved = self.state.vehicles[self.config["vin"]]
        self.assertEqual(saved["odo"], 5000)
        self.assertEqual(saved["chrg_stat"], 3)

    def test_wrong_password_rejected(self):
        config = copy.deepcopy(self.config)
        config["password"] = "Wrong123!"
        with self.assertRaisesRegex(ProtocolError, "401"):
            self.client(config).exchange(snapshot().request(0))

    def test_untrusted_backend_certificate_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.client(ca=self.wrong_certificates / "ca.pem").connect()

    def test_wrong_certificate_hostname_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.client(server_name="not-localhost.invalid").connect()

    def test_wrong_response_sequence_rejected(self):
        self.state.corrupt_seq_next = True
        with self.assertRaisesRegex(ProtocolError, "seq/vin"):
            self.client().exchange(snapshot().request(0))

    def test_wrong_response_vin_rejected(self):
        self.state.corrupt_vin_next = True
        with self.assertRaisesRegex(ProtocolError, "seq/vin"):
            self.client().exchange(snapshot().request(0))

    def test_non_200_response_rejected(self):
        self.state.status_next = 503
        with self.assertRaisesRegex(ProtocolError, "503"):
            self.client().exchange(snapshot().request(0))

    def test_oversized_response_rejected(self):
        self.state.oversize_next = True
        with self.assertRaisesRegex(ProtocolError, "512"):
            self.client().exchange(snapshot().request(0))

    def test_fragmented_http_body_reassembled(self):
        self.state.fragment_response = True
        self.assertEqual(self.client().exchange(snapshot().request(0))["target_soc"], 80)

    def test_no_second_request_while_one_outstanding(self):
        client = self.client()
        client.transmit(snapshot().request(0))
        with self.assertRaises(RuntimeError):
            client.transmit(snapshot().request(1))
        client.receive()

    def test_timeout_retransmits_identical_payload_same_connection(self):
        self.state.drop_next = 1
        client = self.client(timeout=0.15)
        client.transmit(snapshot().request(0))
        connection = client.connection.sock
        with self.assertRaises(socket.timeout):
            client.receive()
        client.retransmit()
        self.assertEqual(client.receive()["seq"], 0)
        self.assertIs(client.connection.sock, connection)
        self.assertEqual(len(self.state.received), 2)
        self.assertEqual(self.state.received[0], self.state.received[1])

    def test_retransmission_limited_to_three_attempts(self):
        self.state.drop_next = 3
        client = self.client(timeout=0.15)
        client.transmit(snapshot().request(0))
        for attempt in range(3):
            with self.assertRaises(socket.timeout):
                client.receive()
            if attempt < 2:
                client.retransmit()
        with self.assertRaises(TimeoutError):
            client.retransmit()
        client.close()
        self.assertEqual(len(self.state.received), 3)


if __name__ == "__main__":
    unittest.main()
