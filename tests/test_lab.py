import http.client
import json
import tempfile
import threading
import time
import unittest

from demo.lab import LabController
from demo.certificates import generate
from demo.protocol import ProtocolError
from demo.web import LabHTTPServer


def wait_for(controller, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = controller.snapshot()
        if predicate(state):
            return state
        if state["status"] == "error":
            raise AssertionError(state["error"])
        time.sleep(0.02)
    raise AssertionError("timed out waiting for lab state")


class LabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="v2icp-lab-test-")
        cls.certificates = generate(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.lab = LabController(cert_dir=self.certificates)
        self.addCleanup(self.lab.stop)

    def step(self):
        previous = self.lab.snapshot()
        expected = previous["rx_count"] + 1 if previous["status"] in ("running", "starting") else 1
        self.lab.step({"timeout": 0.15})
        return wait_for(self.lab, lambda state: state["rx_count"] >= expected
                        and state["sequence"] == expected % 256)

    def test_manual_step_preserves_tls_and_does_not_auto_send(self):
        first = self.step()
        time.sleep(0.15)
        self.assertEqual(self.lab.snapshot()["tx_count"], 1)
        second = self.step()
        self.assertEqual(first["topology"], second["topology"])
        self.assertEqual(second["tx_count"], 2)
        self.assertNotIn("odo", second["last_tx"])

    def test_update_vehicle_and_backend_while_running(self):
        self.step()
        self.lab.update_vehicle({"odo": 5100})
        self.lab.update_backend({"values": {"target_soc": 90}, "departure_in_minutes": 120})
        state = self.step()
        self.assertEqual(state["last_tx"]["odo"], 5100)
        self.assertEqual(state["backend_snapshot"]["odo"], 5100)
        self.assertEqual(state["physical"]["target_soc"], 90)
        self.assertEqual(state["physical"]["driveoff"], 120)

    def test_drop_response_retries_identical_request(self):
        self.step()
        self.lab.inject("drop")
        state = self.step()
        self.assertEqual(state["retries"], 1)
        transmissions = [entry["payload"] for entry in state["events"] if entry["event"] == "TX"]
        self.assertEqual(transmissions[-1], transmissions[-2])

    def test_bad_sequence_is_rejected_then_next_step_recovers(self):
        self.step()
        self.lab.inject("wrong_seq")
        self.lab.step()
        rejected = wait_for(self.lab, lambda state: state["rejected"] == 1 and state["sequence"] == 2)
        self.assertEqual(rejected["rx_count"], 1)
        self.lab.step()
        state = wait_for(self.lab, lambda state: state["sequence"] == 3)
        self.assertEqual(state["rx_count"], 2)

    def test_oversize_closes_session(self):
        self.step()
        self.lab.inject("oversize")
        self.lab.step()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.lab.snapshot()["status"] != "error":
            time.sleep(0.02)
        self.assertEqual(self.lab.snapshot()["status"], "error")
        self.assertEqual(self.lab.snapshot()["rejected"], 1)

    def test_stop_then_restart_resets_session(self):
        self.step()
        self.assertEqual(self.lab.stop()["status"], "stopped")
        self.assertEqual(self.step()["last_tx"]["seq"], 0)

    def test_stop_immediately_during_start(self):
        self.lab.start()
        self.assertEqual(self.lab.stop()["status"], "stopped")
        self.assertFalse(self.lab.thread.is_alive())

    def test_report_removes_identities_and_credentials(self):
        self.step()
        report = json.dumps(self.lab.report())
        self.assertNotIn(self.lab.config["vin"], report)
        self.assertNotIn(self.lab.config["evccid"], report)
        self.assertNotIn(self.lab.config["password"], report)
        self.assertNotIn('"password"', report)
        self.assertIn("DEMO_VIN_REDACTED", report)

    def test_invalid_controls_rejected(self):
        for options in ({"interval": 0}, {"timeout": float("nan")}, {"automatic": "yes"}, {"port": 1}):
            with self.subTest(options=options), self.assertRaises(ProtocolError):
                self.lab.start(options)
        with self.assertRaises(ProtocolError):
            self.lab.update_vehicle({"bat_stat": 8})
        with self.assertRaises(ProtocolError):
            self.lab.update_backend({"values": {"target_soc": 101}})
        with self.assertRaises(ProtocolError):
            self.lab.inject("drop")

    def test_sna_remains_unknown(self):
        self.lab.update_backend({"values": {"ambienttemp": -51}, "departure_in_minutes": None})
        state = self.step()
        self.assertIsNone(state["physical"]["ambienttemp"])
        self.assertIsNone(state["physical"]["driveoff"])


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="v2icp-web-test-")
        cls.server = LabHTTPServer(0, LabController(cert_dir=generate(cls.directory.name)))
        cls.worker = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.controller.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(3)
        cls.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        defaults = {"Content-Type": "application/json", "X-Lab-Token": self.server.token}
        defaults.update(headers or {})
        connection.request(method, path, body=body, headers=defaults)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_index_and_assets(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.server.token.encode(), body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/app.js", "/style.css", "/api/schema", "/api/state"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 200)

    def test_no_paths_outside_asset_whitelist(self):
        for path in ("/../demo/config.json", "/.demo_certs/server.key", "/%2e%2e/README.md"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_untrusted_host_rejected(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "attacker.invalid"})[0], 403)

    def test_cross_origin_post_rejected(self):
        self.assertEqual(self.request("POST", "/api/stop", "{}", {"Origin": "http://attacker.invalid"})[0], 403)

    def test_wrong_csrf_token_rejected(self):
        self.assertEqual(self.request("POST", "/api/stop", "{}", {"X-Lab-Token": "wrong"})[0], 403)

    def test_non_json_and_large_body_rejected(self):
        self.assertEqual(self.request("POST", "/api/stop", "{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/stop", " " * 8193)[0], 413)

    def test_malformed_body_rejected(self):
        for body in ("[1,2]", "not json", '{"interval":NaN}'):
            self.assertEqual(self.request("POST", "/api/start", body)[0], 400)

    def test_backend_validation(self):
        status, _, body = self.request("POST", "/api/backend", '{"values":{"target_soc":101}}')
        self.assertEqual(status, 400)
        self.assertIn(b"error", body)

    def test_report_is_download_and_has_no_password(self):
        status, headers, body = self.request("GET", "/api/report")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertNotIn(b'"password"', body)

    def test_api_can_run_and_stop_manual_session(self):
        try:
            status, _, _ = self.request("POST", "/api/step", '{"timeout":0.2}')
            self.assertEqual(status, 200)
            state = wait_for(self.server.controller, lambda state: state["rx_count"] == 1)
            self.assertEqual(state["last_rx"]["target_soc"], 80)
        finally:
            self.assertEqual(self.request("POST", "/api/stop", "{}")[0], 200)


if __name__ == "__main__":
    unittest.main()
