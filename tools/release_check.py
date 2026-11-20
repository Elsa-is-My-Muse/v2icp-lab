import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".demo_certs", "output", "__pycache__", ".venv", "venv", ".pytest_cache", ".idea", ".vscode"}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".csr", ".srl", ".pcap", ".pcapng",
                      ".log", ".exe", ".bin", ".hex", ".elf", ".axf", ".o", ".obj", ".pyc",
                      ".pdf", ".zip", ".7z"}
REQUIRED = ("README.md", "README.en.md", "LICENSE", "NOTICE.md", "SECURITY.md", "CONTRIBUTING.md",
            "CHANGELOG.md", ".gitignore", "start-lab.cmd", ".github/workflows/test.yml",
            "demo/web.py", "demo/lab.py", "demo/static/index.html", "demo/static/app.js",
            "docs/delivery.md", "docs/architecture.md", "docs/signals.md", "docs/quickstart.md",
            "docs/testing.md", "docs/validation-record.md", "docs/github-release.md",
            "docs/sources-and-limitations.md", "docs/hardware-integration.md",
            "docs/images/dashboard.png", "hardware/README.md", "hardware/architecture.svg",
            "hardware/bom.csv", "hardware/interfaces.csv", "hardware/validation-checklist.md",
            "hardware/bringup-record-template.md", "embedded/v2icp_boundary.c", "embedded/README.md")


def forbidden_path(path):
    return (bool(set(path.parts) & EXCLUDED) or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or path.name.endswith(".local.json")
            or (path.name.startswith(".env") and path.name != ".env.example"))


def text_findings(text):
    findings = []
    if re.search("-----BEGIN " + r"(?:[A-Z]+ )?PRIVATE KEY-----", text):
        findings.append("private key material")
    if re.search(r"[A-Za-z]:[\\/]Users[\\/][^\s`\"']+", text, re.IGNORECASE):
        findings.append("personal Windows absolute path")
    if re.search(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}", text):
        findings.append("possible GitHub credential")
    return findings


def candidates(root):
    try:
        repository = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                    capture_output=True, text=True, check=True)
        if Path(repository.stdout.strip()).resolve() == root.resolve():
            listing = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=root,
                                     capture_output=True, check=True)
            return [Path(name) for name in listing.stdout.decode("utf-8").split("\0") if name], True
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(path.relative_to(root) for path in root.rglob("*")
                  if path.is_file() and not (set(path.relative_to(root).parts) & EXCLUDED)), False


def markdown_targets(text):
    return [unquote(target.split("#")[0]) for target in re.findall(r"\]\(([^)\s]+)\)", text)
            if not re.match(r"[a-z]+:", target, flags=re.IGNORECASE) and not target.startswith("#")]


def inspect(root, paths):
    failures = []
    included = {path.as_posix() for path in paths}
    for required in REQUIRED:
        if required not in included:
            failures.append(f"missing from publication set: {required}")
    for relative in paths:
        absolute = root / relative
        if forbidden_path(relative):
            failures.append(f"must not publish: {relative.as_posix()}")
            continue
        if absolute.is_symlink():
            failures.append(f"review symbolic link: {relative.as_posix()}")
            continue
        if not absolute.is_file():
            failures.append(f"missing tracked file: {relative.as_posix()}")
            continue
        if absolute.stat().st_size > 3_000_000:
            failures.append(f"review file larger than 3 MB: {relative.as_posix()}")
        if relative.suffix.lower() not in {".md", ".py", ".json", ".csv", ".yml", ".yaml", ".js", ".html", ".css", ".c", ".h", ".svg", ".cmd", ".ps1"}:
            continue
        try:
            text = absolute.read_text(encoding="utf-8-sig")
        except UnicodeError:
            failures.append(f"not UTF-8 text: {relative.as_posix()}")
            continue
        failures.extend(f"{relative.as_posix()}: {finding}" for finding in text_findings(text))
        if relative.suffix.lower() == ".md":
            for target in markdown_targets(text):
                resolved = (relative.parent / target).as_posix()
                destination = (root / resolved).resolve()
                try:
                    normalized = destination.relative_to(root.resolve()).as_posix()
                except ValueError:
                    failures.append(f"link leaves project: {relative.as_posix()} -> {target}")
                    continue
                if normalized not in included:
                    failures.append(f"missing publication link target: {relative.as_posix()} -> {target}")
    config_path = root / "demo" / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if (config.get("vin"), config.get("evccid"), config.get("password")) != (
                    "WVWZZZ1JZXW000001", "000102030405", "Abc1234!"):
                failures.append("demo/config.json: public synthetic identities/password were replaced; review privately")
        except (ValueError, OSError):
            failures.append("demo/config.json: cannot validate public sample configuration")
    return failures


def main():
    parser = argparse.ArgumentParser(description="Read-only publication-set and basic sensitive-data check")
    parser.add_argument("--require-git", action="store_true", help="fail unless examining this project's Git tracked set")
    arguments = parser.parse_args()
    paths, tracked = candidates(ROOT)
    failures = inspect(ROOT, paths)
    if arguments.require_git and not tracked:
        failures.append("not a project-root Git repository; stage intended public files before final review")
    print(f"Mode: {'Git tracked files' if tracked else 'workspace fallback (local runtime directories excluded)'}")
    print(f"Files checked: {len(paths)}")
    for failure in failures:
        print("FAIL: " + failure)
    print("FAIL" if failures else "PASS: basic checks only; manual rights, secret and Git history review is still required.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
