"""Appliance TLS certificates include their advertised names and can be trusted."""
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
SBIN = ROOT / "deploy/iso/config/includes.chroot/usr/local/sbin"
WIZARD_PATH = SBIN / "safi-browser-setup.py"
LOCAL_MODULE = SBIN / "safi-appliance-stage/safi_local.py"
os.environ["SAFI_LOCAL_MODULE"] = str(LOCAL_MODULE)
os.environ["SAFI_CATALOGUE"] = str(LOCAL_MODULE.parent / "local-models.json")


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wizard = _load("safi_browser_setup_certificate_test", WIZARD_PATH)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL is required by the appliance")
def test_generated_certificate_has_ip_dns_sans_and_root_trust_extensions(monkeypatch, tmp_path):
    cert_path = tmp_path / "appliance.crt"
    monkeypatch.setattr(wizard, "CERT_DIR", tmp_path)
    monkeypatch.setattr(wizard, "CERT_FILE", cert_path)
    monkeypatch.setattr(wizard, "local_ip", lambda *_args: "192.0.2.24")

    cert, key = wizard.ensure_certificate()
    san = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"],
        check=True, capture_output=True, text=True,
    ).stdout
    constraints = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "basicConstraints"],
        check=True, capture_output=True, text=True,
    ).stdout

    assert "DNS:safi.local" in san
    assert "DNS:runsafi.local" in san
    assert "IP Address:192.0.2.24" in san
    assert "CA:TRUE" in constraints
    assert oct(key.stat().st_mode & 0o777) == "0o600"
    assert oct(cert.stat().st_mode & 0o777) == "0o644"
    assert re.fullmatch(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}", wizard.certificate_fingerprint(cert))


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL is required by the appliance")
def test_certificate_is_renewed_when_the_management_ip_changes(monkeypatch, tmp_path):
    cert_path = tmp_path / "appliance.crt"
    monkeypatch.setattr(wizard, "CERT_DIR", tmp_path)
    monkeypatch.setattr(wizard, "CERT_FILE", cert_path)
    monkeypatch.setattr(wizard, "local_ip", lambda: "192.0.2.24")
    first_cert, _ = wizard.ensure_certificate()
    first_fingerprint = wizard.certificate_fingerprint(first_cert)

    monkeypatch.setattr(wizard, "local_ip", lambda: "192.0.2.25")
    renewed_cert, _ = wizard.ensure_certificate()
    san = subprocess.run(
        ["openssl", "x509", "-in", str(renewed_cert), "-noout", "-ext", "subjectAltName"],
        check=True, capture_output=True, text=True,
    ).stdout

    assert "IP Address:192.0.2.25" in san
    assert wizard.certificate_fingerprint(renewed_cert) != first_fingerprint


def test_first_boot_wizard_serves_public_certificate_for_download(monkeypatch, tmp_path):
    cert_path = tmp_path / "appliance.crt"
    cert_path.write_bytes(b"public certificate bytes")
    monkeypatch.setattr(wizard, "CERT_FILE", cert_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), wizard.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/appliance.crt") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/x-x509-ca-cert"
            assert response.headers["Content-Disposition"] == 'attachment; filename="safi-appliance.crt"'
            assert response.read() == b"public certificate bytes"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_running_app_serves_public_certificate_for_download(monkeypatch, tmp_path):
    import safi_app

    cert_path = tmp_path / "appliance.crt"
    cert_path.write_bytes(b"public certificate bytes")
    monkeypatch.setattr(safi_app, "APPLIANCE_CERT_PATH", cert_path)
    app = Flask(__name__)
    app.add_url_rule(
        "/appliance.crt",
        view_func=safi_app._appliance_certificate_response,
    )

    response = app.test_client().get("/appliance.crt")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/x-x509-ca-cert"
    assert response.headers["Content-Disposition"].endswith('filename=safi-appliance.crt')
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data == b"public certificate bytes"
