import unittest
from pathlib import Path

from tools.release_check import forbidden_path, markdown_targets, text_findings


class ReleaseCheckTests(unittest.TestCase):
    def test_private_key_path_rejected(self):
        self.assertTrue(forbidden_path(Path(".demo_certs/server.key")))

    def test_runtime_and_sensitive_artifacts_rejected(self):
        for name in ("output/report.json", "capture.pcapng", "standard.pdf", ".env", "real.local.json"):
            with self.subTest(name=name):
                self.assertTrue(forbidden_path(Path(name)))

    def test_public_sources_and_example_env_allowed(self):
        for name in ("demo/config.json", "hardware/bom.csv", "docs/images/dashboard.png", ".env.example"):
            with self.subTest(name=name):
                self.assertFalse(forbidden_path(Path(name)))

    def test_key_material_detected_without_real_key(self):
        self.assertIn("private key material", text_findings("-----BEGIN " + "EC PRIVATE KEY-----"))

    def test_personal_windows_path_detected(self):
        self.assertIn("personal Windows absolute path", text_findings("C:" + "\\Users\\example\\Desktop\\private"))

    def test_github_token_pattern_detected(self):
        self.assertIn("possible GitHub credential", text_findings("ghp_" + "x" * 25))

    def test_plain_source_has_no_finding(self):
        self.assertEqual(text_findings("python -m demo.web --open"), [])

    def test_markdown_local_links_only(self):
        self.assertEqual(markdown_targets("[a](docs/readme.md#start) ![b](image.png) [c](https://example.invalid)"),
                         ["docs/readme.md", "image.png"])
