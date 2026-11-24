import importlib.machinery
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

SBIN = (
    Path(__file__).resolve().parents[1]
    / "deploy/iso/config/includes.chroot/usr/local/sbin"
)
if not SBIN.is_dir():
    pytest.skip("appliance ISO build tree (deploy/iso) is not present", allow_module_level=True)
WIZARD_PATH = SBIN / "safi-browser-setup.py"
LOCAL_MODULE = SBIN / "safi-appliance-stage/safi_local.py"

os.environ["SAFI_LOCAL_MODULE"] = str(LOCAL_MODULE)
os.environ["SAFI_CATALOGUE"] = str(LOCAL_MODULE.parent / "local-models.json")


def _load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safi_local = _load("safi_local_for_wizard", LOCAL_MODULE)
wizard = _load("safi_browser_setup_under_test", WIZARD_PATH)


def _hw(ram=0, vram=0, disk=500 << 30, driver=None, usable=False, vendor=None):
    return {
        "ram_bytes": ram,
        "cpu_count": 8,
        "avx2": True,
        "avx512": True,
        "disk_free_bytes": disk,
        "gpu": {"vendor": vendor, "usable": usable, "vram_bytes": vram,
                "driver_major": driver, "name": "test gpu", "reason": ""},
    }


class FakeSetup:

    @staticmethod
    def parse_template(_path):
        return ([], {})

    @staticmethod
    def render(_lines, _index, values):
        return "".join(f"{k}={v}\n" for k, v in sorted(values.items()))

    @staticmethod
    def generated_secrets():
        return {"DB_PASSWORD": "dbpw", "MYSQL_ROOT_PASSWORD": "rootpw"}


@pytest.fixture
def env_paths(tmp_path, monkeypatch):
    env_file = tmp_path / "safi.env"
    pin_file = tmp_path / "setup.pin"
    done_file = tmp_path / "done"
    state_file = tmp_path / "setup-state.json"
    choice_file = tmp_path / "model-choice.json"
    pin_file.write_text("424242\n")
    monkeypatch.setattr(wizard, "APP_DIR", tmp_path)
    monkeypatch.setattr(wizard, "ENV_FILE", env_file)
    monkeypatch.setattr(wizard, "PIN_FILE", pin_file)
    monkeypatch.setattr(wizard, "DONE_FILE", done_file)
    monkeypatch.setattr(wizard, "STATE_FILE", state_file)
    monkeypatch.setattr(wizard, "CHOICE_FILE", choice_file)
    monkeypatch.setattr(wizard, "STATE_DIR", tmp_path)
    monkeypatch.setattr(wizard, "FETCH_STATUS", tmp_path / "model-fetch.json")
    monkeypatch.setattr(wizard, "local_ip", lambda *_a: "10.0.0.5")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    return {"env": env_file, "pin": pin_file, "done": done_file,
            "state": state_file, "choice": choice_file}


def _commit(env_paths, choice, admin=None):
    state = {"choice": choice,
             "admin": admin or {"username": "admin",
                                "password": "correct-horse-battery",
                                "email": "ops@example.com"}}
    wizard.initialize(state, FakeSetup)
    return env_paths["env"].read_text()


def test_picker_offers_the_whole_catalogue():
    result = wizard.model_choices(_hw(ram=32 << 30))
    assert result["available"] is True
    catalogue = safi_local.load_catalogue()
    assert [m["id"] for m in result["models"]] == [m["id"] for m in catalogue["models"]]


def test_picker_never_offers_the_retired_0_6b():
    result = wizard.model_choices(_hw(ram=64 << 30))
    assert "qwen3-0.6b" not in [m["id"] for m in result["models"]]


def test_picker_marks_exactly_one_recommendation():
    result = wizard.model_choices(_hw(ram=32 << 30))
    assert sum(1 for m in result["models"] if m["recommended"]) == 1


def test_picker_reports_a_cpu_only_box():
    result = wizard.model_choices(_hw(ram=16 << 30))
    assert result["backend"] == "cpu"
    assert result["local_only"] is True


def test_picker_picks_a_cuda_backend_for_a_capable_gpu():
    result = wizard.model_choices(
        _hw(ram=64 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia"))
    assert result["backend"] == "cuda-12.8"
    assert result["local_only"] is False


def test_picker_degrades_when_hardware_is_unknown():
    result = wizard.model_choices(None)
    assert result["available"] is False
    assert result["models"] == []


def test_local_choice_records_alias_and_backend():
    choice = wizard.validate_choice({"model": "qwen3-8b"}, _hw(ram=32 << 30))
    assert choice == {"mode": "local", "model": "qwen3-8b",
                      "alias": "safi-qwen3-8b", "backend": "cpu",
                      "size": choice["size"]}
    assert choice["size"] == 5027783488


def test_local_choice_carries_the_cuda_backend_when_a_gpu_is_present():
    choice = wizard.validate_choice(
        {"model": "qwen3-32b"},
        _hw(ram=64 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia"))
    assert choice["backend"] == "cuda-12.8"


def test_force_cpu_downgrades_the_backend():
    choice = wizard.validate_choice(
        {"model": "qwen3-8b", "prefer_cpu": "1"},
        _hw(ram=64 << 30, vram=24 << 30, driver=580, usable=True, vendor="nvidia"))
    assert choice["backend"] == "cpu"


def test_a_model_too_big_for_the_box_is_refused_server_side():
    with pytest.raises(ValueError) as exc:
        wizard.validate_choice({"model": "qwen3-32b"}, _hw(ram=4 << 30))
    assert "does not fit" in str(exc.value)


def test_an_unknown_model_id_is_refused():
    with pytest.raises(ValueError) as exc:
        wizard.validate_choice({"model": "llama3-70b"}, _hw(ram=64 << 30))
    assert "Choose a local model" in str(exc.value)


def test_missing_model_selection_is_refused():
    with pytest.raises(ValueError):
        wizard.validate_choice({}, _hw(ram=64 << 30))


def test_cloud_choice_requires_a_key():
    with pytest.raises(ValueError) as exc:
        wizard.validate_cloud({"provider": "GROQ_API_KEY", "api_key": "  "})
    assert "API key is required" in str(exc.value)


def test_cloud_choice_records_provider_and_key():
    choice = wizard.validate_cloud({"provider": "GEMINI_API_KEY", "api_key": "abc"})
    assert choice == {"mode": "cloud", "provider": "GEMINI_API_KEY", "api_key": "abc"}


def test_retired_high_retention_providers_are_not_offered():
    for provider in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY"):
        with pytest.raises(ValueError) as exc:
            wizard.validate_cloud({"provider": provider, "api_key": "abc"})
        assert "Choose an AI provider" in str(exc.value)


def test_offered_cloud_providers_all_have_a_probe():
    for key, _, _ in wizard.CLOUD_PROVIDERS:
        assert key in wizard.PROVIDER_PROBES


def test_probe_urls_match_the_apps_routing():
    assert wizard.PROVIDER_PROBES["GROQ_API_KEY"][0] == "https://api.groq.com/openai/v1/models"
    assert wizard.PROVIDER_PROBES["CEREBRAS_API_KEY"][0] == "https://api.cerebras.ai/v1/models"
    assert wizard.PROVIDER_PROBES["MISTRAL_API_KEY"][0] == "https://api.mistral.ai/v1/models"
    assert wizard.PROVIDER_PROBES["ANTHROPIC_API_KEY"][1] == "x-api-key"
    assert wizard.PROVIDER_PROBES["GEMINI_API_KEY"][1] == "query"


def test_local_commit_writes_the_chosen_alias_to_every_faculty(env_paths):
    text = _commit(env_paths, {"mode": "local", "model": "qwen3-32b",
                               "alias": "safi-qwen3-32b", "backend": "cuda-13.4",
                               "size": 19762149024})
    for faculty in ("INTELLECT", "BACKEND", "NOTETAKER", "SUMMARIZER"):
        assert f"SAFI_{faculty}_MODEL=safi-qwen3-32b" in text
    assert "SAFI_LOCAL_MODEL_API_KEY=local" in text
    assert "SAFI_MAX_INTELLECT_TOKENS=8192" in text


def test_local_commit_leaves_conscience_unpinned(env_paths):
    text = _commit(env_paths, {"mode": "local", "model": "qwen3-32b",
                               "alias": "safi-qwen3-32b", "backend": "cuda-13.4",
                               "size": 19762149024})
    assert "SAFI_CONSCIENCE_MODEL=safi-qwen3-32b" not in text
    assert "SAFI_CONSCIENCE_MODEL\n" not in text


def test_local_commit_never_writes_a_cloud_key(env_paths):
    text = _commit(env_paths, {"mode": "local", "model": "qwen3-8b",
                               "alias": "safi-qwen3-8b", "backend": "cpu",
                               "size": 5027783488})
    assert "GROQ_API_KEY" not in text
    assert "GEMINI_API_KEY" not in text


def test_cloud_commit_writes_only_the_selected_provider(env_paths):
    text = _commit(env_paths, {"mode": "cloud", "provider": "MISTRAL_API_KEY",
                               "api_key": "sk-test"})
    assert "MISTRAL_API_KEY=sk-test" in text
    assert "GROQ_API_KEY" not in text
    assert "SAFI_LOCAL_MODEL_API_KEY=local" not in text


def test_commit_keeps_sso_off(env_paths):
    text = _commit(env_paths, {"mode": "cloud", "provider": "GROQ_API_KEY",
                               "api_key": "sk-test"})
    assert "SAFI_SSO_ENABLED=false" in text


def test_commit_makes_software_engineer_the_default_agent(env_paths):
    text = _commit(env_paths, {"mode": "cloud", "provider": "GROQ_API_KEY",
                               "api_key": "sk-test"})
    assert "SAFI_PROFILE=software_engineer" in text
    assert "SAFI_BUILTIN_AGENTS=software_engineer,sysadmin,tutor" in text


def test_commit_uses_https_and_secure_cookie_for_appliance_access(env_paths):
    text = _commit(env_paths, {"mode": "cloud", "provider": "GROQ_API_KEY",
                               "api_key": "sk-test"})
    assert "WEB_BASE_URL=https://10.0.0.5" in text
    assert "ALLOWED_ORIGINS=https://10.0.0.5" in text
    assert "SESSION_COOKIE_SECURE=True" in text


def test_commit_removes_the_pin_and_marks_done(env_paths):
    _commit(env_paths, {"mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk"})
    assert not env_paths["pin"].exists()
    assert env_paths["done"].exists()


def test_commit_erases_the_stored_admin_password(env_paths):
    wizard.write_state({"choice": {"mode": "cloud", "provider": "GROQ_API_KEY",
                                   "api_key": "sk"},
                        "admin": {"username": "admin",
                                  "password": "correct-horse-battery", "email": ""}})
    assert env_paths["state"].exists()
    _commit(env_paths, {"mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk"})
    assert not env_paths["state"].exists()


def test_state_file_is_root_only(env_paths):
    wizard.write_state({"choice": {"mode": "cloud"}, "admin": {"password": "x"}})
    assert oct(env_paths["state"].stat().st_mode)[-3:] == "600"


def test_env_file_is_written_private(env_paths):
    _commit(env_paths, {"mode": "cloud", "provider": "GROQ_API_KEY", "api_key": "sk"})
    assert oct(env_paths["env"].stat().st_mode)[-3:] == "600"


def test_choose_page_has_the_pin_and_both_modes():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert 'name="pin"' in page
    assert 'value="local"' in page
    assert 'value="cloud"' in page
    assert 'name="password_confirm"' in page
    assert "This appliance uses HTTPS." in page
    assert 'href="/appliance.crt"' in page
    assert 'Open https://' in page


def test_choose_page_shows_the_detected_hardware():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30, vram=24 << 30,
                                            driver=535, usable=True, vendor="nvidia"))
    assert "32.0 GiB RAM" in page
    assert "24.0 GiB VRAM" in page
    assert "CUDA 12.8" in page


def test_choose_page_marks_the_recommendation():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert "Recommended" in page
    assert 'value="qwen3-14b" selected' in page


def test_choose_page_labels_unavailable_models():
    page = wizard.page_choose(hardware=_hw(ram=6 << 30))
    assert "Unavailable" in page
    assert "needs" in page


def test_choose_page_omits_the_retired_providers():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert "DeepSeek" not in page
    assert "Zhipu" not in page
    for label in ("Groq", "Google Gemini", "Cerebras", "OpenAI", "Anthropic", "Mistral"):
        assert f">{label}</option>" in page


def test_choose_page_explains_the_data_retention_position():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert "not retained" in page
    assert "processed and discarded" in page


def test_choose_page_mentions_internet_access():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert "internet access" in page


def test_progress_page_hides_finish_while_a_local_model_downloads():
    page = wizard.page_progress(
        {"choice": {"mode": "local", "alias": "safi-qwen3-8b", "size": 5027783488}},
        "424242")
    assert 'id="finish" style="display:none"' in page
    assert "20.0 GB" not in page
    assert "5.0 GB" in page


def test_progress_page_offers_finish_immediately_for_a_cloud_key():
    page = wizard.page_progress(
        {"choice": {"mode": "cloud", "provider": "GROQ_API_KEY"}}, "424242")
    assert 'id="finish" style="display:none"' not in page
    assert 'id="finish"' in page
    assert "Groq" in page


def test_progress_page_carries_the_pin_for_finish_and_retry():
    page = wizard.page_progress(
        {"choice": {"mode": "local", "alias": "safi-qwen3-8b", "size": 1}}, "424242")
    assert 'value="424242"' in page
    assert "/setup/retry" in page
    assert "/setup/finish" in page


def test_progress_page_polls_only_for_a_local_model():
    local = wizard.page_progress(
        {"choice": {"mode": "local", "alias": "safi-qwen3-8b", "size": 1}}, "1")
    cloud = wizard.page_progress({"choice": {"mode": "cloud", "provider": "GROQ_API_KEY"}}, "1")
    assert "/setup/status" in local
    assert "setInterval" in local
    assert "/setup/status" not in cloud


def test_pages_escape_the_error_they_are_given():
    page = wizard.page_choose("<script>alert(1)</script>", hardware=_hw(ram=8 << 30))
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_the_choose_page_offers_deciding_later():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert 'value="later"' in page
    assert "Decide later" in page


def test_a_resumed_visit_explains_the_admin_password_is_asked_again():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30), resume=True)
    assert "Setup was deferred" in page
    assert "password is asked again" in page


def test_a_fresh_visit_does_not_claim_to_be_resuming():
    page = wizard.page_choose(hardware=_hw(ram=32 << 30))
    assert "Setup was deferred" not in page
