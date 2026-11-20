import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.lab import LabController
from demo.web import LabHTTPServer


def main():
    parser = argparse.ArgumentParser(description="Optional real-browser acceptance test")
    parser.add_argument("--browser", help="Chrome or Edge executable; omit for Playwright Chromium")
    parser.add_argument("--screenshot", default="output/dashboard.png")
    arguments = parser.parse_args()
    from playwright.sync_api import sync_playwright

    certificate_directory = tempfile.TemporaryDirectory(prefix="v2icp-browser-test-")
    server = LabHTTPServer(0, LabController(cert_dir=certificate_directory.name))
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    worker.start()
    errors = []
    try:
        with sync_playwright() as playwright:
            options = {"headless": True}
            if arguments.browser:
                options["executable_path"] = arguments.browser
            browser = playwright.chromium.launch(**options)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/")
                page.wait_for_selector("#backend-target_soc")
                page.locator("#start").click()
                page.wait_for_function("() => Number(document.querySelector('#rx-count').textContent) >= 2")
                page.locator("#backend-target_soc").fill("90")
                page.locator("#backend-form button").click()
                page.wait_for_function("() => document.querySelector('#rx-json').textContent.includes('\"target_soc\": 90')")
                page.locator("#fault").select_option("wrong_seq")
                page.locator("#inject").click()
                page.wait_for_function("() => document.querySelector('#anomalies').textContent.endsWith(' / 1')")
                page.locator("#fault").select_option("drop")
                page.locator("#inject").click()
                page.wait_for_function("() => document.querySelector('#anomalies').textContent === '1 / 1'")
                destination = Path(arguments.screenshot)
                destination.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(destination), full_page=True)
                page.locator("#stop").click()
                page.wait_for_function("() => document.querySelector('#status-label').textContent === '已停止'")
                page.locator("#step").click()
                page.wait_for_function("() => document.querySelector('#rx-count').textContent === '1'")
                page.locator("#stop").click()
                page.wait_for_function("() => document.querySelector('#status-label').textContent === '已停止'")
                page.set_viewport_size({"width": 390, "height": 844})
                if not page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"):
                    raise AssertionError("mobile layout overflows viewport")
                if errors:
                    raise AssertionError("JavaScript errors: " + "; ".join(errors))
                print(json.dumps({"result": "PASS", "browser": browser.version,
                                  "checks": ["TLS exchange", "edit SOC", "reject bad seq", "retry dropped response",
                                             "stop", "manual restart", "mobile layout", "no JS errors"],
                                  "screenshot": str(destination)}, ensure_ascii=False))
            finally:
                browser.close()
    finally:
        server.controller.stop()
        server.shutdown()
        server.server_close()
        worker.join(3)
        certificate_directory.cleanup()


if __name__ == "__main__":
    main()
