# V2ICP Lab

An independent, local-first learning lab for the EVCC ↔ backend communication discussed in VDV 261. [中文完整说明](README.md).

## Run

Requirements: Python 3.10+, OpenSSL on PATH, and working IPv6 loopback. No Python runtime packages, JavaScript build tools or CDN are required.

```sh
python -m demo.web --open
python -m demo.run_demo --interval 1
python -m unittest discover -s tests -v
```

Open `http://127.0.0.1:8765/`. On Windows, `start-lab.cmd` is also available. Keep the terminal open. Stop the session in the UI before pressing Ctrl+C.

The dashboard supports live vehicle/backend inputs, manual steps, automatic cycles, raw/physical values, failure injection, event history and redacted report export. The IPv6/TLS/HTTP traffic is real, over loopback; the relay forwards encrypted bytes without terminating TLS. Fast mode uses intentionally shortened timings.

## Scope and deliverables

- Software: runnable Python simulator, local dashboard, automated tests and optional real-browser smoke tests.
- Hardware references: original architecture diagram, category-level BOM, interface checklist, staged bring-up plan and recording templates in `hardware/`.
- Integration references: isolated connection contexts and an illustrative C boundary in `embedded/`.
- Documentation: usage, architecture, protocol-model signals, hardware integration, testing, limitations and GitHub publication instructions.

**Not included:** manufactured boards, PCB/Gerber files, production EVCC/SECC firmware, PLC/SLAC or InternetAccess VAS integration, an IPv6 router, CAN actuation or certification. Hardware has not been tested. The protocol model has not received an independent clause-by-clause audit against the licensed specification; review the exact edition before using it in a real product.

This is not an official VDV project or a conformance tool. Backend requests are not vehicle safety commands. Preserve the original ISO 15118 connection and use a separate V2ICP socket/TLS context. A byte relay is not a production Internet gateway.

The UI binds only to `127.0.0.1`, uses no cross-origin API, and must not be exposed publicly. Test private keys, real credentials, proprietary firmware and standard PDFs must not be published. The CLI report is not redacted; review it privately or use the UI's redacted export.

Original materials use the MIT license; third-party standards and proprietary materials are excluded. See [NOTICE](NOTICE.md), [contributing](CONTRIBUTING.md), [roadmap](docs/roadmap.md) and [release procedure](docs/github-release.md).
