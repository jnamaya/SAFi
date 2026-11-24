import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlencode

import pytest

REPO = Path(__file__).resolve().parents[1]
if not (REPO / "deploy/iso/config/includes.chroot/usr/local/sbin").is_dir():
    pytest.skip("appliance ISO build tree (deploy/iso) is not present", allow_module_level=True)

from test_appliance_setup_wizard import FakeSetup, _hw, safi_local, wizard
CLOUD_KEYS = ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY",
              "CEREBRAS_API_KEY", "ZHIPU_API_KEY")
PIN = "424242"


class FakeSocket:
    def __init__(self, body: bytes = b""):
        self._buffer = io.BytesIO(body)

    def makefile(self, mode, **_kwargs):
        return self._buffer


class FakeServer:
    def __init__(self, pin=PIN, hardware=None):
        self.pin = pin
        self.hardware = hardware if hardware is not None else _hw(ram=32 << 30)
        self.setup = FakeSetup
        self.shutdown_called = False

    def shutdown(self):
        self.shutdown_called = True


def _call(path, fields=None, method="POST", pin=PIN, hardware=None):
    body = urlencode(fields).encode() if fields is not None else b""
    handler = wizard.Handler.__new__(wizard.Handler)
    handler.rfile = io.BytesIO(body)
    out = io.BytesIO()
    handler.wfile = out
    handler.server = FakeServer(pin, hardware)
    handler.path = path
    handler.command = method
    handler.headers = {"Content-Length": str(len(body))}
    handler.send_response = lambda *a, **k: None
    handler.send_header = lambda *a, **k: None
    handler.end_headers = lambda *a, **k: None
    if method == "POST":
        handler.do_POST()
    else:
        handler.do_GET()
    return out.getvalue().decode()


@pytest.fixture
def env_paths(tmp_path, monkeypatch):
    env_file = tmp_path / "safi.env"
    pin_file = tmp_path / "setup.pin"
    done_file = tmp_path / "done"
    state_file = tmp_path / "setup-state.json"
    choice_file = tmp_path / "model-choice.json"
    pin_file.write_text(PIN + "\n")
    monkeypatch.setattr(wizard, "APP_DIR", tmp_path)
    monkeypatch.setattr(wizard, "ENV_FILE", env_file)
    monkeypatch.setattr(wizard, "PIN_FILE", pin_file)
    monkeypatch.setattr(wizard, "DONE_FILE", done_file)
    monkeypatch.setattr(wizard, "STATE_FILE", state_file)
    monkeypatch.setattr(wizard, "CHOICE_FILE", choice_file)
    monkeypatch.setattr(wizard, "STATE_DIR", tmp_path)
    monkeypatch.setattr(wizard, "FETCH_STATUS", tmp_path / "model-fetch.json")
    monkeypatch.setattr(wizard, "local_ip", lambda *_a: "10.0.0.5")
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    return {"env": env_file, "pin": pin_file, "done": done_file,
            "state": state_file, "choice": choice_file, "calls": calls}


def test_a_wrong_pin_cannot_start_a_download(env_paths):
    body = _call("/setup", {
        "pin": "000000", "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "Invalid or expired setup PIN." in body
    assert not env_paths["calls"], "a bad PIN must not reach systemctl"


def test_a_missing_pin_is_rejected(env_paths):
    body = _call("/setup", {
        "mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "Invalid or expired setup PIN." in body


def test_the_pin_is_not_leaked_into_the_status_endpoint(env_paths):
    wizard.write_state({"choice": {"mode": "local", "alias": "safi-qwen3-8b"}})
    body = _call("/setup/status", method="GET")
    assert PIN not in body


def test_local_setup_starts_the_fetch_without_blocking(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "Installing" in body
    start = [c for c in env_paths["calls"] if "start" in c]
    assert start and "--no-block" in start[0]


GPU_BOX = _hw(ram=32 << 30, vram=24 << 30, driver=580, usable=True, vendor="nvidia")


def test_local_setup_records_the_choice_for_the_fetch_script(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b", "prefer_cpu": "1",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"}, hardware=GPU_BOX)
    assert json.loads(env_paths["choice"].read_text()) == {
        "model": "qwen3-8b", "backend": "cpu"}


def test_a_gpu_box_uses_cuda_unless_told_otherwise(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-32b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"}, hardware=GPU_BOX)
    assert json.loads(env_paths["choice"].read_text()) == {
        "model": "qwen3-32b", "backend": "cuda-13.4"}


def test_an_oversized_model_is_refused_by_the_form_too(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-32b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "does not fit" in body
    assert not env_paths["choice"].exists()


def test_a_refresh_returns_to_the_progress_page(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    body = _call("/setup", method="GET")
    assert "Installing" in body


def test_finish_is_refused_while_the_model_is_still_downloading(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    env_paths["pin"].write_text(PIN + "\n")
    body = _call("/setup/finish", {"pin": PIN})
    assert "has not finished downloading" in body
    assert not env_paths["done"].exists()
    assert not env_paths["env"].exists()


def test_finish_commits_once_the_model_verifies(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    env_paths["pin"].write_text(PIN + "\n")
    wizard.FETCH_STATUS.write_text(json.dumps({"state": "done"}))
    body = _call("/setup/finish", {"pin": PIN})
    assert "SAFi is starting" in body
    assert env_paths["done"].exists()
    assert "SAFI_INTELLECT_MODEL=safi-qwen3-8b" in env_paths["env"].read_text()


def test_finish_refuses_a_corrupt_model(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    env_paths["pin"].write_text(PIN + "\n")
    wizard.FETCH_STATUS.write_text(json.dumps({"state": "error",
                                               "error": "sha256 mismatch"}))
    body = _call("/setup/finish", {"pin": PIN})
    assert "has not finished downloading" in body
    assert not env_paths["done"].exists()


def test_retry_restarts_the_fetch(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    env_paths["calls"].clear()
    body = _call("/setup/retry", {"pin": PIN})
    assert any("restart" in c for c in env_paths["calls"])
    assert "Installing" in body


def test_finish_without_a_started_setup_is_refused(env_paths):
    body = _call("/setup/finish", {"pin": PIN})
    assert "Start again" in body
    assert not env_paths["done"].exists()


def test_cloud_setup_waits_for_an_explicit_start(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk-test",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "Installing" in body
    assert f'value="{PIN}"' in body, "the Start form must carry the PIN back"
    assert not env_paths["done"].exists()

    body = _call("/setup/finish", {"pin": PIN})
    assert "SAFi is starting" in body
    assert env_paths["done"].exists()
    assert "GROQ_API_KEY=sk-test" in env_paths["env"].read_text()
    assert not any("safi-model-fetch" in " ".join(map(str, c)) for c in env_paths["calls"])


def test_test_key_probes_the_provider(env_paths, monkeypatch):
    monkeypatch.setattr(wizard, "probe_provider",
                        lambda provider, key: (True, "Groq · gpt-oss-120b"))
    body = _call("/setup/test-key", {
        "pin": PIN, "mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk-test"})
    assert "Groq · gpt-oss-120b" in body


def test_test_key_reports_a_rejected_key(env_paths, monkeypatch):
    monkeypatch.setattr(wizard, "probe_provider",
                        lambda provider, key: (False, "Groq rejected that key."))
    body = _call("/setup/test-key", {
        "pin": PIN, "mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "bad"})
    assert "Groq rejected that key." in body


def test_test_key_rejects_an_unlisted_provider(env_paths, monkeypatch):
    called = []
    monkeypatch.setattr(wizard, "probe_provider",
                        lambda p, k: called.append(p) or (True, "should not happen"))
    body = _call("/setup/test-key", {
        "pin": PIN, "mode": "cloud", "provider": "DEEPSEEK_API_KEY", "api_key": "sk"})
    assert "Choose an AI provider" in body
    assert not called, "an unlisted provider must never reach the network"


@pytest.mark.parametrize("fields,expected", [
    ({"password": "short", "password_confirm": "short"}, "at least 8 characters"),
    ({"password": "correct-horse-battery", "password_confirm": "different"},
     "do not match"),
    ({"username": "ab", "password": "correct-horse-battery",
      "password_confirm": "correct-horse-battery"}, "3-64 letters"),
    ({"username": "admin", "email": "not-an-email", "password": "correct-horse-battery",
      "password_confirm": "correct-horse-battery"}, "does not look valid"),
])
def test_bad_admin_input_is_reported_not_committed(env_paths, fields, expected):
    payload = {"pin": PIN, "mode": "cloud", "provider": "GROQ_API_KEY",
               "api_key": "sk", "username": "admin",
               "password": "correct-horse-battery",
               "password_confirm": "correct-horse-battery"}
    payload.update(fields)
    body = _call("/setup", payload)
    assert expected in body
    assert not env_paths["done"].exists()
    assert not env_paths["env"].exists()


def test_the_admin_password_never_appears_back_in_the_page(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "correct-horse-battery" not in body


def test_deferring_starts_safi_and_keeps_setup_open(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "later",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "SAFi is running" in body
    assert "No AI model is configured yet" in body
    assert any("safi.service" in " ".join(map(str, c)) for c in env_paths["calls"])
    assert not env_paths["done"].exists()
    assert env_paths["pin"].exists()
    assert not any("safi-model-fetch" in " ".join(map(str, c)) for c in env_paths["calls"])


def test_deferring_writes_no_provider_key_at_all(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "later",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    text = env_paths["env"].read_text()
    for provider in ("GROQ_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY",
                     "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CEREBRAS_API_KEY"):
        assert f"{provider}=" not in text
    assert "SAFI_LOCAL_MODEL_API_KEY=local" in text
    assert "SAFI_INTELLECT_MODEL" not in text
    assert "SAFI_CONSCIENCE_MODEL" not in text
    assert "SAFI_BACKEND_MODEL" not in text


def test_deferring_does_not_leave_the_admin_password_on_disk(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "later",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert not env_paths["state"].exists()


def test_a_visit_after_deferring_returns_the_choose_page(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "later",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    body = _call("/setup", method="GET")
    assert "Installing" not in body
    assert 'value="later"' in body
    assert "Setup was deferred" in body


def test_deferring_still_requires_an_admin_password(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "later", "username": "admin", "password": "short",
        "password_confirm": "short"})
    assert "at least 8 characters" in body
    assert not env_paths["done"].exists()


def test_the_second_pass_can_finish_with_a_local_model(env_paths):
    _call("/setup", {
        "pin": PIN, "mode": "later",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    _call("/setup", {
        "pin": PIN, "mode": "local", "model": "qwen3-8b",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    wizard.FETCH_STATUS.write_text(json.dumps({"state": "done"}))
    body = _call("/setup/finish", {"pin": PIN})
    assert "SAFi is starting" in body
    assert env_paths["done"].exists()
    assert env_paths["pin"].exists() is False
    assert "SAFI_INTELLECT_MODEL=safi-qwen3-8b" in env_paths["env"].read_text()


def test_an_unknown_mode_is_refused(env_paths):
    body = _call("/setup", {
        "pin": PIN, "mode": "telepathy",
        "username": "admin", "password": "correct-horse-battery",
        "password_confirm": "correct-horse-battery"})
    assert "Choose how SAFi should run its model." in body
    assert not env_paths["done"].exists()


def test_a_deferred_env_file_really_configures_no_provider(env_paths, monkeypatch):
    from test_appliance_setup_wizard import _load
    from safi_app.core.services.model_routing import configured_providers

    setup = _load("real_setup_under_test", REPO / "scripts/setup.py")
    monkeypatch.setattr(wizard, "APP_DIR", REPO)
    wizard.initialize(
        {"choice": {"mode": "later"},
         "admin": {"username": "admin", "password": "correct-horse-battery",
                   "email": ""}},
        setup)
    rendered = env_paths["env"].read_text()

    offenders = [line for line in rendered.splitlines()
                 if line.startswith(CLOUD_KEYS) and line.partition("=")[2].strip()]
    assert offenders == [], f"deferred .env must leave cloud providers blank: {offenders}"
    assert "SAFI_LOCAL_MODEL_API_KEY=local" in rendered
    for faculty in ("INTELLECT", "CONSCIENCE", "BACKEND", "SUMMARIZER"):
        assert f"SAFI_{faculty}_MODEL=\n" in rendered

    import safi_app.config as config_module
    saved = config_module.Config
    try:
        config_module.Config = type("Cfg", (), {
            k: "" for k in dir(saved)
            if k.endswith("_API_KEY") or k.endswith("_MODEL")})
        assert configured_providers(config_module.Config) == frozenset()
    finally:
        config_module.Config = saved
