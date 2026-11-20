import shutil
import subprocess
from pathlib import Path


def _openssl(*arguments, cwd):
    executable = shutil.which("openssl")
    if executable is None:
        raise RuntimeError("openssl is required to generate local test certificates")
    result = subprocess.run([executable, *arguments], cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"openssl failed: {result.stderr.strip()}")


def generate(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    required = [directory / name for name in ("ca.pem", "server.pem", "server.key")]
    if all(path.exists() for path in required):
        return directory
    configuration = directory / "openssl.cnf"
    configuration.write_text("[req]\ndistinguished_name=dn\n[dn]\n", encoding="ascii")
    extensions = directory / "server.ext"
    extensions.write_text("subjectAltName=DNS:localhost,IP:::1\n"
                          "basicConstraints=critical,CA:FALSE\n"
                          "keyUsage=critical,digitalSignature\n"
                          "extendedKeyUsage=serverAuth\n", encoding="ascii")
    for basename in ("ca", "server"):
        _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out",
                 basename + ".key", cwd=directory)
    _openssl("req", "-config", "openssl.cnf", "-new", "-x509", "-sha256", "-key", "ca.key", "-out", "ca.pem",
             "-days", "30", "-subj", "/CN=Local V2ICP Demo CA",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=directory)
    _openssl("req", "-config", "openssl.cnf", "-new", "-key", "server.key", "-out", "server.csr", "-subj",
             "/CN=localhost", cwd=directory)
    _openssl("x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
             "-CAcreateserial", "-out", "server.pem", "-days", "30", "-sha256",
             "-extfile", "server.ext", cwd=directory)
    return directory
