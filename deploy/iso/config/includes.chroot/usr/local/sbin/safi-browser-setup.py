#!/usr/bin/env python3
"""One-time HTTPS bootstrap for a SAFi appliance."""
from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

APP_DIR = Path("/var/www/safi")
STATE_DIR = Path("/var/lib/safi-firstboot")
PIN_FILE = STATE_DIR / "setup.pin"
DONE_FILE = STATE_DIR / "done"
# Written by the operator's first submit, consumed and deleted by finish(). It
# holds the admin password, so 0600 root-only; the alternative is committing a
# .env that points at a model whose download may not finish.
STATE_FILE = STATE_DIR / "setup-state.json"
CHOICE_FILE = STATE_DIR / "model-choice.json"
ENV_FILE = APP_DIR / ".env"
FETCH_STATUS = Path("/var/lib/safi/model-fetch.json")
FETCH_UNIT = "safi-model-fetch.service"
HOST = "127.0.0.1"
PORT = 5001
CERT_DIR = Path("/etc/ssl/runsafi")
CERT_FILE = CERT_DIR / "appliance.crt"

# Cloud providers offered at setup. DeepSeek and Zhipu are deliberately absent:
# PROVIDER_METADATA records zdr=False for both ("retained indefinitely, used for
# training" / "no contractual ZDR program"), which is not a list to hand an
# operator unprompted on a governance appliance. Re-add behind an explicit
# disclosure if the coverage is wanted.
CLOUD_PROVIDERS = [
    ("GROQ_API_KEY", "Groq",
     "Free tier, no card required. Inference requests are not retained by default."),
    ("GEMINI_API_KEY", "Google Gemini",
     "Free tier available. BAA, EU hosting and zero-data retention supported."),
    ("CEREBRAS_API_KEY", "Cerebras",
     "Free tier, no card required. Prompts are processed and discarded."),
    ("OPENAI_API_KEY", "OpenAI",
     "Requires a billing account. BAA, EU hosting, zero data retention on approval."),
    ("ANTHROPIC_API_KEY", "Anthropic",
     "Requires a billing account. BAA, EU hosting, zero data retention by agreement."),
    ("MISTRAL_API_KEY", "Mistral",
     "Requires a billing account. EU-hosted, BAA, zero data retention on request."),
]

# Cheapest authenticated call per provider, used by the "test key" button. These
# mirror the base_url values in model_routing.build_providers_config so a key
# that passes here is the same shape the app will use.
PROVIDER_PROBES = {
    "GROQ_API_KEY": ("https://api.groq.com/openai/v1/models", "bearer"),
    "CEREBRAS_API_KEY": ("https://api.cerebras.ai/v1/models", "bearer"),
    "MISTRAL_API_KEY": ("https://api.mistral.ai/v1/models", "bearer"),
    "OPENAI_API_KEY": ("https://api.openai.com/v1/models", "bearer"),
    "ANTHROPIC_API_KEY": ("https://api.anthropic.com/v1/models", "x-api-key"),
    "GEMINI_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/models", "query"),
}


def load_setup_module():
    spec = importlib.util.spec_from_file_location("runsafi_setup", APP_DIR / "scripts/setup.py")
    if not spec or not spec.loader:
        raise RuntimeError("SAFi setup helpers are unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_safi_local():
    """Import the appliance's catalogue/helper module (stdlib only).

    SAFI_LOCAL_MODULE overrides the location, which is what lets the test suite
    exercise the picker against a build-host copy of the module.
    """
    path = Path(os.environ.get("SAFI_LOCAL_MODULE", "/usr/local/lib/safi_local.py"))
    if not path.exists():
        # Build-time fallback so a partially migrated image still renders.
        path = Path("/usr/local/sbin/safi-appliance-stage/safi_local.py")
    spec = importlib.util.spec_from_file_location("safi_local", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


safi_local = load_safi_local()


def ensure_certificate(ip_address: str | None = None) -> tuple[Path, Path]:
    cert_dir = CERT_DIR
    cert_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = cert_dir / "appliance.key"
    cert = CERT_FILE
    address = ip_address if ip_address is not None else local_ip()
    expected_dns = ("safi.local", "runsafi.local")

    def matches_current_names() -> bool:
        if not key.is_file() or not cert.is_file():
            return False
        try:
            sans = subprocess.run(
                ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"],
                check=True, capture_output=True, text=True,
            ).stdout
            constraints = subprocess.run(
                ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "basicConstraints"],
                check=True, capture_output=True, text=True,
            ).stdout
            subprocess.run(
                ["openssl", "x509", "-in", str(cert), "-checkend", "0", "-noout"],
                check=True, capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        if "CA:TRUE" not in constraints or any(f"DNS:{name}" not in sans for name in expected_dns):
            return False
        if address and address != "<appliance-ip>":
            return re.search(rf"IP Address:\s*{re.escape(address)}(?:\s|,|$)", sans) is not None
        return True

    if not matches_current_names():
        san = [*(f"DNS:{name}" for name in expected_dns)]
        if address and address != "<appliance-ip>":
            san.append(f"IP:{address}")
        new_key = cert_dir / "appliance.key.new"
        new_cert = cert_dir / "appliance.crt.new"
        new_key.unlink(missing_ok=True)
        new_cert.unlink(missing_ok=True)
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:3072",
                "-days", "3650", "-keyout", str(new_key), "-out", str(new_cert),
                "-subj", "/CN=SAFi Appliance",
                "-addext", f"subjectAltName={','.join(san)}",
                "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,digitalSignature,keyCertSign,cRLSign",
                "-addext", "extendedKeyUsage=serverAuth",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            new_key.chmod(0o600)
            new_cert.chmod(0o644)
            os.replace(new_key, key)
            os.replace(new_cert, cert)
        finally:
            new_key.unlink(missing_ok=True)
            new_cert.unlink(missing_ok=True)
    return cert, key


def certificate_fingerprint(cert: Path) -> str:
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip().split("=", 1)[-1]


def local_ip(retries: int = 1) -> str:
    # The operator browses the appliance over its management/LAN NIC, not the
    # egress NIC a NAT/router would answer for `ip route get`. Enumerate the
    # host's global IPv4 addresses first (kernel PCI order: eth0/enp0s3 before
    # a NAT NIC) so WEB_BASE_URL points at the address a browser can reach;
    # fall back to the routable source only if enumeration fails.
    for attempt in range(retries):
        try:
            addrs = subprocess.check_output(
                ["ip", "-4", "-o", "addr", "show", "scope", "global"], text=True)
            for line in addrs.splitlines():
                tokens = line.split()
                if len(tokens) >= 4:
                    return tokens[3].split("/")[0]
        except Exception:
            pass
        if attempt + 1 < retries:
            time.sleep(1)
    try:
        route = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True)
        fields = route.split()
        return fields[fields.index("src") + 1]
    except Exception:
        pass
    return "<appliance-ip>"


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, STATE_FILE)


def clear_state() -> None:
    for path in (STATE_FILE, CHOICE_FILE):
        try:
            path.unlink()
        except OSError:
            pass


def read_fetch_status() -> dict:
    try:
        return json.loads(FETCH_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "pending", "percent": 0, "label": "Waiting to start"}


# --------------------------------------------------------------------------
# model choice
# --------------------------------------------------------------------------

def model_choices(hardware: dict | None) -> dict:
    """Catalogue entries annotated with fit, for the picker."""
    if safi_local is None or hardware is None:
        return {"available": False, "models": [], "backend": None, "backend_reason": ""}
    try:
        catalogue = safi_local.load_catalogue()
    except (OSError, ValueError):
        return {"available": False, "models": [], "backend": None, "backend_reason": ""}
    backend_id = safi_local.select_backend(catalogue, hardware)
    return {
        "available": True,
        "models": safi_local.evaluate_models(catalogue, hardware, backend_id),
        "backend": backend_id,
        "backend_reason": safi_local.backend_reason(catalogue, hardware, backend_id),
        "local_only": backend_id == "cpu",
    }


def validate_choice(fields: dict, hardware: dict | None) -> dict:
    """Turn posted form fields into a stored choice, or raise ValueError."""
    if safi_local is None or hardware is None:
        raise ValueError("Local model selection is unavailable on this appliance")
    catalogue = safi_local.load_catalogue()
    prefer_cpu = fields.get("prefer_cpu") == "1"
    backend_id = safi_local.select_backend(catalogue, hardware, prefer_cpu=prefer_cpu)
    entries = {e["id"]: e for e in safi_local.evaluate_models(catalogue, hardware, backend_id)}

    model_id = fields.get("model", "").strip()
    entry = entries.get(model_id)
    if entry is None:
        raise ValueError("Choose a local model")
    # Re-check server-side. The browser disables options that do not fit, but a
    # crafted POST should not be able to start a 20 GB download on a 4 GB VM.
    if not entry["fits"]:
        raise ValueError(f"{entry['label']} does not fit this appliance: {'; '.join(entry['reasons'])}")
    return {
        "mode": "local",
        "model": model_id,
        "alias": entry["alias"],
        "backend": backend_id,
        "size": entry["size"],
    }


def validate_cloud(fields: dict) -> dict:
    provider = fields.get("provider", "").strip()
    if provider not in dict(PROVIDER_PROBES):
        raise ValueError("Choose an AI provider")
    api_key = fields.get("api_key", "").strip()
    if not api_key:
        raise ValueError("Provider API key is required")
    return {"mode": "cloud", "provider": provider, "api_key": api_key}


def probe_provider(provider: str, api_key: str) -> tuple[bool, str]:
    """Cheapest authenticated call. Never raises."""
    url, style = PROVIDER_PROBES[provider]
    if style == "query":
        url = f"{url}?key={api_key}"
        request = urllib.request.Request(url)
    elif style == "x-api-key":
        request = urllib.request.Request(url, headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read(1)
            return True, "Key accepted"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, f"Provider rejected the key (HTTP {exc.code})"
        return False, f"Unexpected response (HTTP {exc.code})"
    except urllib.error.URLError as exc:
        return False, f"Could not reach the provider: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - advisory only
        return False, f"Could not verify the key: {exc}"


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

CSS = """
:root{--bg:#111827;--panel:#1f2937;--line:#374151;--green:#16a34a;--bright:#22c55e;--muted:#9ca3af;--warn:#fbbf24;--bad:#ef4444}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:#f9fafb;font:16px system-ui,sans-serif}
main{width:min(720px,calc(100% - 32px));background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:32px;box-shadow:0 20px 60px #0006}
.brand{display:flex;align-items:center;gap:10px;color:var(--bright);font-weight:800;letter-spacing:.08em;text-transform:uppercase}.brand svg{width:34px;height:34px;flex:none}h1{margin:.4rem 0 .5rem}h2{margin:1.4rem 0 .4rem;font-size:1.05rem}
p{color:var(--muted);line-height:1.5}label{display:block;margin:18px 0 6px;font-weight:600}
input,select{width:100%;padding:12px;border:1px solid var(--line);border-radius:8px;background:#111827;color:#fff;font:inherit}
button{margin-top:24px;width:100%;border:0;border-radius:8px;padding:13px;background:var(--green);color:#fff;font-weight:700;font-size:1rem;cursor:pointer}
button:hover{background:var(--bright);color:#052e16}button.secondary{background:#374151;margin-top:10px}
button.secondary:hover{background:#4b5563;color:#fff}
.error{margin:16px 0;padding:12px;border:1px solid var(--bad);color:#fecaca;border-radius:8px;white-space:pre-wrap}
.ok{margin:16px 0;padding:12px;border:1px solid var(--green);color:#bbf7d0;border-radius:8px}
.hw{margin:14px 0;padding:10px 12px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:.9rem}
.hw b{color:#f9fafb}
.section-card{background:#11182766;border:1px solid var(--line);border-radius:12px;padding:24px;margin-top:24px}.section-card h2{margin:0 0 16px;padding-bottom:12px;border-bottom:1px solid var(--line);font-size:1.15rem}.hidden{display:none!important}.flex-row{display:flex;gap:8px;align-items:flex-start}.flex-grow{flex-grow:1}
.opt{display:block;margin:8px 0;padding:12px;border:1px solid var(--line);border-radius:8px;cursor:pointer}
.opt:has(input:checked){border-color:var(--bright);background:#14532d22}
.opt.dis{opacity:.45;cursor:not-allowed}
.opt small{display:block;color:var(--muted);font-weight:400;margin-top:4px;line-height:1.4}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.72rem;font-weight:700;vertical-align:middle}
.pill.rec{background:var(--bright);color:#052e16}.pill.gpu{background:#1d4ed8;color:#dbeafe}.pill.no{background:#7f1d1d;color:#fecaca}
.bar{height:14px;background:#111827;border:1px solid var(--line);border-radius:999px;overflow:hidden;margin:18px 0 8px}
.bar>i{display:block;height:100%;background:var(--bright);width:0;transition:width .4s}
.mono{font-family:ui-monospace,monospace;font-size:.85rem;color:var(--muted)}
fieldset{border:1px solid var(--line);border-radius:8px;padding:4px 12px 12px;margin:18px 0}
legend{padding:0 6px;font-weight:700}
"""


def shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SAFi Appliance Setup</title>
 <style>{CSS}</style></head><body><main><div class="brand"><svg viewBox="29 29 42 42" role="img" aria-label="SAFi Rosetta logo"><circle cx="50" cy="36" r="7" fill="#16a34a"/><circle cx="64" cy="46" r="7" fill="#16a34a"/><circle cx="58" cy="64" r="7" fill="#16a34a"/><circle cx="42" cy="64" r="7" fill="#16a34a"/><circle cx="36" cy="46" r="7" fill="#16a34a"/><circle cx="50" cy="52" r="6" fill="#4ade80"/></svg><span>SAFi</span></div><h1>{title}</h1>
{body}</main></body></html>"""


def hardware_strip(hardware: dict) -> str:
    if safi_local is None or hardware is None:
        return '<div class="hw">Hardware details are unavailable on this appliance.</div>'
    return ('<div class="hw">This appliance: <b>'
            + html.escape(safi_local.describe_hardware(hardware)) + "</b></div>")


def _model_options(entries: list[dict], chosen: str = "", show_vram: bool = False) -> str:
    out = []
    for entry in entries:
        pills = []
        if entry["recommended"]:
            pills.append('<span class="pill rec">Recommended</span>')
        if entry["placement"] == "gpu" and entry["fits"]:
            pills.append('<span class="pill gpu">GPU</span>')
        if not entry["fits"]:
            pills.append('<span class="pill no">Unavailable</span>')
        detail = entry["summary"]
        if entry["fits"]:
            detail += (f" &middot; {entry['size_human']} download, {entry['disk_human']} disk"
                       f", needs {entry['ram_human']} RAM")
            if show_vram:
                detail += f" / {entry['vram_human']} VRAM"
        else:
            detail += " &middot; " + "; ".join(entry["reasons"])
        for note in entry.get("notes", []):
            detail += f" &middot; {html.escape(note)}"
        selected = " selected" if entry["id"] == chosen else ""
        out.append(
            f'<option value="{html.escape(entry["id"])}"{selected}>'
            f'{html.escape(entry["label"])} ({entry["size_human"]}) '
            f'{" ".join(pills)}{" - " + html.escape(detail)}</option>')
    return "".join(out)


def page_choose(error: str = "", hardware: dict | None = None, values: dict | None = None,
                notice: str = "", resume: bool = False) -> str:
    values = values or {}
    banner = ""
    if error:
        banner += f'<div class="error">{html.escape(error)}</div>'
    if notice:
        banner += f'<div class="ok">{html.escape(notice)}</div>'
    if resume:
        banner += (
            '<div class="ok">Setup was deferred, so your administrator account '
            'already exists. Choose a model to finish &mdash; or press Decide '
            'later again to come back later. The password is asked again because '
            'finishing setup rewrites the configuration file.</div>')
    choices = model_choices(hardware)
    model_id = values.get("model", "")
    if not model_id and choices["available"]:
        # Pre-select the recommendation. Without this the browser falls back to
        # the first option, so an operator who reads the page and clicks
        # Continue would silently get the smallest model rather than the one the
        # picker told them was right for their hardware.
        recommended = [m["id"] for m in choices["models"] if m["recommended"]]
        model_id = recommended[0] if recommended else ""

    provider_opts = "".join(
        f'<option value="{key}">{html.escape(label)}</option>'
        for key, label, _ in CLOUD_PROVIDERS)
    provider_notes = "".join(
        f'<small>{html.escape(label)}: {html.escape(note)}</small><br>'
        for _, label, note in CLOUD_PROVIDERS)

    if choices["available"] and choices["models"]:
        show_vram = choices.get("backend") != "cpu"
        local_block = (
            "<h2>Run a model on this appliance</h2>"
            f'<p>Inference backend: <b>{html.escape(choices["backend_reason"])}</b>.</p>'
            '<select id="model" name="model">'
            + _model_options(choices["models"], model_id, show_vram)
            + "</select>")
        if choices.get("local_only"):
            local_block += ('<p><small>No CUDA-capable GPU was detected, so every model here '
                            'runs on the CPU. Larger models are slow without a GPU.</small></p>')
    else:
        local_block = ('<h2>Run a model on this appliance</h2>'
                       '<p><small>Local model selection is unavailable on this appliance. '
                       'Choose a cloud model below.</small></p>')

    body = f"""{banner}
<p>Configure the runtime environment and set up the local administrator account.
This appliance has internet access, so live market and web tools work.</p>
<p>This appliance uses HTTPS. To remove the first-visit certificate warning, <a href="/appliance.crt">download its certificate</a>, verify its SHA-256 fingerprint against the appliance console, then add it to your browser or operating system's trusted root certificates.</p>
<form method="post" action="/setup" id="setup-form">
<div class="section-card"><h2>1. Device Authorization</h2>
<p>Enter the one-time PIN displayed on the appliance console.</p>
<label for="pin">One-time setup PIN</label>
<input id="pin" name="pin" required inputmode="numeric" autocomplete="one-time-code"></div>
<div class="section-card"><h2>2. SAFi Intelligence Engine</h2>
<label class="opt"><input type="radio" name="mode" value="local" checked onchange="toggleMode()"> Run a model on this appliance
<small>Inference runs locally; prompts do not leave the hardware.</small></label>
<label class="opt"><input type="radio" name="mode" value="cloud" onchange="toggleMode()"> Use a cloud AI model
<small>Connect to a managed provider for cloud inference.</small></label>
<label class="opt"><input type="radio" name="mode" value="later" onchange="toggleMode()"> Decide later
<small>Finish setup now and choose a model from the dashboard.</small></label>
<div id="local-options">{hardware_strip(hardware)}{local_block}
<label class="opt"><input type="checkbox" name="prefer_cpu" value="1"> Force CPU inference
<small>Skips the GPU backend download, but generation is slower.</small></label></div>
<div id="cloud-options" class="hidden"><label for="provider">Select Provider</label>
<select id="provider" name="provider">{provider_opts}</select>
<label for="api_key">Provider API key</label><div class="flex-row"><input class="flex-grow" id="api_key" name="api_key" type="password" autocomplete="off">
<button type="submit" formaction="/setup/test-key" class="secondary" style="width:100px;margin-top:0">Test</button></div>
<p class="mono">{provider_notes}</p></div></div>
<div class="section-card"><h2>3. Administrator Account</h2>
<p>This credential manages the local system and SAFi web console.</p>
<label for="username">Administrator username</label>
<input id="username" name="username" value="admin" required autocomplete="username" pattern="[A-Za-z0-9._-]{{3,64}}" title="3-64 letters, digits, dot, underscore or hyphen">
<label for="email">Administrator email <small>(optional)</small></label>
<input id="email" name="email" type="email" autocomplete="email" placeholder="Used for alerts and audit logs">
<label for="password">Administrator password</label><input id="password" name="password" type="password" minlength="8" required autocomplete="new-password">
<label for="password_confirm">Confirm administrator password</label><input id="password_confirm" name="password_confirm" type="password" minlength="8" required autocomplete="new-password"></div>
<button type="submit">Complete Setup</button>
<p style="text-align:center"><small>Open https://{html.escape(local_ip())}/ after completion.</small></p>
</form>
<script>function toggleMode(){{const m=document.querySelector('input[name="mode"]:checked').value;document.getElementById('local-options').classList.toggle('hidden',m!=='local');document.getElementById('cloud-options').classList.toggle('hidden',m!=='cloud');document.getElementById('api_key').required=m==='cloud';}}</script>"""
    return shell("Appliance setup", body)


def page_progress(state: dict, pin: str = "") -> str:
    choice = state.get("choice") or {}
    local = choice.get("mode") == "local"
    if local:
        size = safi_local.human_bytes(choice.get("size", 0)) if safi_local else ""
        summary = (f"Downloading {html.escape(choice.get('alias', ''))} ({size}) and starting "
                   "the model server. On a slow link this can take a long time. You can "
                   "close this page: the download resumes if you come back.")
    else:
        provider = {k: l for k, l, _ in CLOUD_PROVIDERS}.get(choice.get("provider", ""), "")
        summary = f"Using {html.escape(provider)}."

    # The PIN rides along in the forms below so /setup/finish and /setup/retry
    # are gated. It is the same secret the operator just typed, this page is
    # HTTPS, and the wizard listens on loopback behind apache.
    pin_field = f'<input type="hidden" name="pin" value="{html.escape(pin)}">'

    if local:
        live = """<div class="bar"><i id="bar"></i></div>
<p id="status" class="mono">Waiting to start</p>
<p id="detail" class="mono"></p>
<div id="result"></div>"""
        script = """<script>
const bar=document.getElementById('bar'),status=document.getElementById('status'),
      detail=document.getElementById('detail'),result=document.getElementById('result'),
      finish=document.getElementById('finish');
function fmt(n){if(n>=1e9)return (n/1e9).toFixed(1)+' GB';
  if(n>=1e6)return (n/1e6).toFixed(0)+' MB';return n+' B';}
function render(s){
  bar.style.width=(s.percent||0)+'%';
  status.textContent=(s.percent||0)+'% \\u2014 '+(s.label||'');
  const bits=[];
  if(s.step_name)bits.push(s.step_name);
  if(s.step_size)bits.push(fmt(s.step_bytes||0)+' of '+fmt(s.step_size));
  detail.textContent=bits.join('   ');
  if(s.state==='error'){
    result.innerHTML='<div class="error">'+s.error+'</div>'+
      '<form method="post" action="/setup/retry">'+document.getElementById('pinf').outerHTML+
      '<button class="secondary">Retry download</button></form>';
  }else if(s.state==='done'){finish.style.display='block';}
}
function poll(){fetch('/setup/status',{cache:'no-store'}).then(r=>r.json())
  .then(render).catch(()=>{});}
poll();setInterval(poll,2000);
</script>"""
    else:
        # A cloud key has nothing to download, so there is no progress to poll
        # and Finish is offered straight away.
        live = '<p id="result">Nothing to download. Press Start SAFi when ready.</p>'
        script = ""

    body = f"""<p>{summary}</p>
{live}
<form method="post" action="/setup/finish">
<span id="pinf" hidden>{pin_field}</span>
<button type="submit" id="finish"{"" if not local else ' style="display:none"'}>Start SAFi</button>
</form>
{script}
"""
    return shell("Installing", body)


# --------------------------------------------------------------------------
# commit
# --------------------------------------------------------------------------

def initialize(state: dict, setup) -> None:
    """Write .env, provision the database, and mark setup done.

    Deliberately does not start the model server. For a local model that has
    already been fetched and verified by this point; safi-model-fetch owns the
    unit's lifecycle.

    A deferred setup (mode="later") is NOT done. The admin account is created
    and SAFi starts, but the PIN is kept and DONE_FILE is not written, so this
    wizard comes back on the next boot and the operator can finish the decision
    without rebuilding the box.
    """
    admin = state["admin"]
    choice = state["choice"]
    username = admin["username"]
    password = admin["password"]
    deferred = choice["mode"] == "later"
    local_provider = choice["mode"] == "local"

    lines, index = setup.parse_template(APP_DIR / ".env.example")
    base_url = f"https://{local_ip()}"
    values = {
        "FLASK_ENV": "production", "SAFI_DEPLOYMENT_MODE": "production",
        "APP_PORT": str(PORT), "WEB_BASE_URL": base_url,
        "ALLOWED_ORIGINS": base_url, "SESSION_COOKIE_SECURE": "True",
        "DB_HOST": "localhost", "DB_USER": "safi", "DB_NAME": "safi",
        "SAFI_LOCAL_ADMIN_USERNAME": username,
        "SAFI_LOCAL_ADMIN_EMAIL": admin.get("email", ""),
        "SAFI_LOCAL_ADMIN_PASSWORD": password,
        # SSO is intentionally off on the appliance regardless of internet
        # access: an appliance operator authenticates locally, and offering
        # Google/Microsoft sign-in that no appliance identity is registered for
        # is a dead end on the sign-in page.
        "SAFI_SSO_ENABLED": "false",
    }
    if local_provider:
        alias = choice["alias"]
        values.update({
            "SAFI_INTELLECT_MODEL": alias,
            "SAFI_CONSCIENCE_MODEL": alias,
            "SAFI_BACKEND_MODEL": alias,
            "SAFI_NOTETAKER_MODEL": alias,
            "SAFI_SUMMARIZER_MODEL": alias,
            # Cap the completion well under the server's context window so
            # prompt plus completion always fits; the server rejects every turn
            # with exceed_context_size_error otherwise.
            "SAFI_MAX_INTELLECT_TOKENS": "1024",
            "SAFI_LOCAL_MODEL_API_KEY": "local",
        })
    elif deferred:
        # No provider key of any kind. The app already refuses to store a model
        # whose provider has no key (model_provider_configured), so leaving all
        # of them empty degrades to "no model offered" rather than to a turn
        # that fails against a placeholder key. SAFi comes up and is usable for
        # everything that does not need a model.
        #
        # The local key IS still set, as a marker of intent rather than a
        # credential. Config.validate() refuses to start when no provider key
        # exists at all, so without it a deferred box would not boot. It is
        # harmless: installed_local_models() returns nothing until a model is
        # actually downloaded, so no local model is offered and nothing is ever
        # dispatched to 127.0.0.1:8081.
        values["SAFI_LOCAL_MODEL_API_KEY"] = "local"
    else:
        values[choice["provider"]] = choice["api_key"]

    values.update(setup.generated_secrets())
    tmp = ENV_FILE.with_suffix(".env.tmp")
    tmp.write_text(setup.render(lines, index, values), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, ENV_FILE)
    # This service writes .env as root, but safi.service / safi-kb-indexer run
    # as safi:www-data; without a chown gunicorn dies on the first dotenv read
    # (PermissionError) and apache serves 503. Keep it 0600, owned by safi.
    subprocess.run(
        ["chown", "safi:www-data", str(ENV_FILE)], check=True)

    subprocess.run(["systemctl", "start", "mysql"], check=True)
    db_password = values["DB_PASSWORD"].replace("'", "''")
    root_password = values["MYSQL_ROOT_PASSWORD"].replace("'", "''")
    sql = (
        "CREATE DATABASE IF NOT EXISTS `safi` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        # Scratch schema for backup restore-verification (backup_verify.py). It
        # is provisioned up-front so the minimal `safi` DB account never needs
        # database-level CREATE; the verifier wipes it by dropping its tables.
        "CREATE DATABASE IF NOT EXISTS `safi_verify` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_password}'; "
        f"CREATE USER IF NOT EXISTS 'safi'@'localhost' IDENTIFIED BY '{db_password}'; "
        f"ALTER USER 'safi'@'localhost' IDENTIFIED BY '{db_password}'; "
        "GRANT ALL PRIVILEGES ON `safi`.* TO 'safi'@'localhost'; "
        "GRANT ALL PRIVILEGES ON `safi_verify`.* TO 'safi'@'localhost'; FLUSH PRIVILEGES;"
    )
    subprocess.run(["mysql", "--protocol=socket", "-u", "root", "-e", sql], check=True)
    # Operator account (console + SSH): the appliance admin password unlocks
    # the `admin` OS user created by 020-accounts-and-dirs.chroot. One
    # password governs both the web admin login and the box itself.
    subprocess.run(
        ["bash", "-c",
         f"printf '%s\\n' 'admin:{password}' | chpasswd"], check=True)
    if deferred:
        # Keep the PIN and do not mark setup done, so main() serves this wizard
        # again after a reboot and the operator can come back and choose.
        #
        # The state is cleared: it held the admin password, and unlike the
        # local-model path there is no download to wait for, so nothing needs it
        # to survive. A later visit recognises a deferred setup from ENV_FILE
        # existing without DONE_FILE, which is why that pair is the whole signal.
        clear_state()
        return
    PIN_FILE.unlink(missing_ok=True)
    DONE_FILE.touch(mode=0o600, exist_ok=True)
    clear_state()


# --------------------------------------------------------------------------
# request handling
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body: str) -> None:
        self._send(body.encode(), "text/html; charset=utf-8")

    def _json(self, payload: dict) -> None:
        self._send(json.dumps(payload).encode(), "application/json")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _pin_ok(self, fields: dict) -> bool:
        return secrets.compare_digest(fields.get("pin", ""), self.server.pin)

    def _fields(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode() if length else ""
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/appliance.crt":
            try:
                body = CERT_FILE.read_bytes()
            except OSError:
                self.send_error(404, "Appliance certificate is not available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", 'attachment; filename="safi-appliance.crt"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/setup/status":
            self._json(read_fetch_status())
            return
        if path != "/setup":
            self._redirect("/setup")
            return
        state = read_state()
        if (state.get("choice") or {}).get("mode") not in (None, "later"):
            self._html(page_progress(state, self.server.pin))
        else:
            # ENV_FILE without DONE_FILE is exactly the deferred case: the
            # administrator was provisioned but no model was ever chosen.
            self._html(page_choose(hardware=self.server.hardware,
                                   resume=ENV_FILE.exists()))

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        fields = self._fields()

        if not self._pin_ok(fields):
            self._html(page_choose("Invalid or expired setup PIN.",
                                   self.server.hardware, fields))
            return

        try:
            if path == "/setup/test-key":
                try:
                    provider = fields.get("provider", "").strip()
                    api_key = fields.get("api_key", "").strip()
                    if provider not in PROVIDER_PROBES:
                        raise ValueError("Choose an AI provider")
                    if not api_key:
                        raise ValueError("Enter a provider API key to test")
                    ok, detail = probe_provider(provider, api_key)
                except ValueError as exc:
                    self._html(page_choose(str(exc), self.server.hardware, fields))
                    return
                # Show what actually answered. An operator testing a key wants
                # to know which model will be live, not merely that it parsed.
                self._html(page_choose(
                    "" if ok else detail, self.server.hardware, fields,
                    notice=("Key accepted. " + detail) if ok else ""))
                return

            if path == "/setup/retry":
                subprocess.run(["systemctl", "restart", FETCH_UNIT],
                               check=True, capture_output=True)
                self._html(page_progress(read_state(), self.server.pin))
                return

            if path == "/setup/finish":
                state = read_state()
                if not state.get("choice") or not state.get("admin"):
                    raise ValueError("Setup was not completed. Start again.")
                if state["choice"]["mode"] == "local":
                    status = read_fetch_status()
                    if status.get("state") != "done":
                        raise ValueError("The model has not finished downloading yet.")
                initialize(state, self.server.setup)
                if state["choice"]["mode"] == "later":
                    # Setup is not finished, so the wizard keeps serving and the
                    # PIN stays valid. SAFi itself starts now.
                    subprocess.run(["systemctl", "start", "safi.service"], check=True)
                    self._html(shell("SAFi is running", (
                        "<p>No AI model is configured yet, so anything that needs "
                        "one will say so. Come back to this address whenever you "
                        "want to choose a model &mdash; it stays available until "
                        "you do.</p>")))
                    return
                self._html(shell("SAFi is starting", "<p>SAFi is starting. You will be "
                                                   "redirected to the application shortly.</p>"
                                                   "<meta http-equiv=\"refresh\" content=\"8;url=/\">"
                                                   "<script>setTimeout(() => location.replace('/'), 8000);</script>"))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            if path != "/setup":
                raise ValueError("Unknown setup action")

            mode = fields.get("mode", "local")
            if mode == "local":
                choice = validate_choice(fields, self.server.hardware)
            elif mode == "cloud":
                choice = validate_cloud(fields)
            elif mode == "later":
                choice = {"mode": "later"}
            else:
                raise ValueError("Choose how SAFi should run its model.")

            password = fields.get("password", "")
            if password != fields.get("password_confirm"):
                raise ValueError("Administrator passwords do not match")
            if len(password) < 8:
                raise ValueError("Administrator password must be at least 8 characters")
            username = fields.get("username", "").strip().lower()
            if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
                raise ValueError("Administrator username must be 3-64 letters, digits, "
                                 "dot, underscore or hyphen")
            email = fields.get("email", "").strip()
            if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise ValueError("That email address does not look valid")

            state = {
                "choice": choice,
                "admin": {"username": username, "password": password, "email": email},
            }
            write_state(state)

            if choice["mode"] == "later":
                # Nothing to wait for, so there is no progress page: provision
                # now, start SAFi, and leave this wizard up for the second visit.
                initialize(state, self.server.setup)
                subprocess.run(["systemctl", "start", "safi.service"], check=True)
                self._html(shell("SAFi is running", (
                    "<p>No AI model is configured yet, so anything that needs one "
                    "will say so. Come back to this address whenever you want to "
                    "choose a model &mdash; it stays available until you do.</p>")))
                return

            if choice["mode"] == "local":
                CHOICE_FILE.write_text(json.dumps(
                    {"model": choice["model"], "backend": choice["backend"]}),
                    encoding="utf-8")
                CHOICE_FILE.chmod(0o600)
                # --no-block: a 20 GB download must not hold this request open.
                subprocess.run(["systemctl", "start", "--no-block", FETCH_UNIT],
                               check=True, capture_output=True)
            # The PIN goes back into the page: on the cloud path this response
            # is the only place the operator sees the Start button, and without
            # it the follow-up /setup/finish would be rejected.
            self._html(page_progress(state, self.server.pin))
        except Exception as exc:  # noqa: BLE001 - shown to the operator verbatim
            self._html(page_choose(str(exc), self.server.hardware, fields))

    def log_message(self, *_args):
        return


def main() -> int:
    if sys.argv[1:] == ["--refresh-certificate"]:
        address = local_ip(60)
        cert, _key = ensure_certificate(address)
        subprocess.run(["systemctl", "reload", "apache2"], check=True)
        print(f"Refreshed TLS certificate for https://{address}/")
        print(f"SHA-256 fingerprint: {certificate_fingerprint(cert)}")
        print(f"Download certificate: https://{address}/appliance.crt")
        return 0
    if sys.argv[1:]:
        print("Usage: safi-browser-setup.py [--refresh-certificate]", file=sys.stderr)
        return 2

    address = local_ip(60)
    if DONE_FILE.exists():
        return 0
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not PIN_FILE.exists():
        PIN_FILE.write_text(f"{secrets.randbelow(1_000_000):06d}\n", encoding="ascii")
        PIN_FILE.chmod(0o600)
    pin = PIN_FILE.read_text(encoding="ascii").strip()
    cert, key = ensure_certificate(address)
    setup = load_setup_module()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.pin = pin
    server.setup = setup
    try:
        server.hardware = safi_local.detect_hardware() if safi_local else None
    except Exception:
        server.hardware = None
    # Print the banner FIRST: the PIN must reach the console even if apache has
    # a hiccup, otherwise a boot looks frozen with no way in. Apache is what
    # serves https://IP/ -> 127.0.0.1:5001; its failure must never be fatal
    # here (a PIN worth of bricked console is worse than a retry).
    # DHCP can finish just after network-online.target on appliances with more
    # than one NIC. Wait briefly so the console shows a usable URL, not a
    # permanent <appliance-ip> placeholder.
    print(f"SAFi Appliance is Active. Complete configuration at: https://{address}/", flush=True)
    print(f"TLS certificate SHA-256 fingerprint: {certificate_fingerprint(cert)}", flush=True)
    print(f"Download certificate: https://{address}/appliance.crt", flush=True)
    print("Trust it as a root certificate after comparing its SHA-256 fingerprint here.", flush=True)
    if address == "<appliance-ip>":
        # No DHCP lease (isolated lab, or a static site that has not been
        # configured yet). The install is still fully usable over the console;
        # be explicit about the commands that give it an address rather than
        # leaving a bare placeholder on the screen.
        print("", flush=True)
        print("No network address yet - this appliance has no IP configured.", flush=True)
        print("Inspect:   safi network show", flush=True)
        print("Configure: safi network set dhcp <iface>", flush=True)
        print("           safi network diff && safi network apply", flush=True)
        print("Or static: safi network set static <iface> <cidr> <gateway> <dns>", flush=True)
    print(f"One-time setup PIN: {pin}", flush=True)
    try:
        subprocess.run(["systemctl", "enable", "--now", "apache2"], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"warning: apache2 could not be started ({exc.returncode}); "
              "https://<ip>/ will be unavailable until it is.", flush=True)
    server.serve_forever()
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "safi", "safi-kb-indexer"], check=True)
    subprocess.run(["systemctl", "enable", "safi-retention-purge.timer", "safi-backup.timer", "safi-backup-verify.timer"], check=True)
    # Keep the status dashboard on tty1 after first boot. It is informational
    # only; local console login is intentionally disabled there.
    subprocess.run(["systemctl", "start", "safi-console"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
