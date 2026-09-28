"""Tests for synthesizing the appliance's local models into the model picker.

The wizard picks a model on the appliance; the picker has to offer it without
anyone writing a DB row. These cover the read, the on-disk presence check that
keeps a picker entry from 404ing, and the filtering the rest of
list_models_for_org applies.
"""
import json
import pathlib

import pytest

from safi_app.core.services import provider_governance as pg

CATALOGUE = {
    "schema": 1,
    "context_size": 8192,
    "model_root": "/var/lib/safi/models",
    "models": [
        {"id": "qwen3-8b", "alias": "safi-qwen3-8b", "label": "Qwen3 8B",
         "file": "Qwen3-8B-Q4_K_M.gguf", "size": 5027783488, "min_ram": 9000000000,
         "url": "https://x/y.gguf"},
        {"id": "qwen3-32b", "alias": "safi-qwen3-32b", "label": "Qwen3 32B",
         "file": "Qwen3-32B-Q4_K_M.gguf", "size": 19762149024, "min_ram": 24500000000,
         "url": "https://x/z.gguf"},
    ],
}


@pytest.fixture
def served(monkeypatch):
    """Pretend safi-model-fetch has activated a given alias."""
    def set_active(alias):
        import safi_app.config as cm
        monkeypatch.setattr(cm, "active_local_model", lambda: alias, raising=False)
        monkeypatch.setattr("safi_app.config.active_local_model", lambda: alias)
    return set_active


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    """A catalogue plus a model_root we can populate to fake a download."""
    path = tmp_path / "local-models.json"
    root = tmp_path / "models"
    payload = dict(CATALOGUE, model_root=str(root))
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(pg, "LOCAL_CATALOGUE_PATH", str(path))

    def install(model_id, file, size):
        target = root / model_id / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 1)
        target.chmod(0o644)
        # Only the size is compared, so a sparse file is enough.
        with open(target, "r+b") as handle:
            handle.truncate(size)

    install.populate = install
    install.root = root
    return install


# --------------------------------------------------------------------------
# installed_local_models
# --------------------------------------------------------------------------

def test_nothing_is_offered_before_anything_is_downloaded(catalogue):
    assert pg.installed_local_models() == []


def test_a_downloaded_model_appears_with_its_alias(catalogue, served):
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    models = pg.installed_local_models()
    assert [m["id"] for m in models] == ["safi-qwen3-8b"]
    entry = models[0]
    assert entry["label"] == "Qwen3 8B"
    assert entry["provider"] == "local"
    assert entry["local"] is True
    assert entry["context_window"] == 8192


def test_only_the_downloaded_one_of_two_is_offered(catalogue, served):
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    assert [m["id"] for m in pg.installed_local_models()] == ["safi-qwen3-8b"]


def test_a_downloaded_but_unserved_model_is_not_offered(catalogue, served):
    # The old safi-demo bug in a different guise: weights on disk, but the
    # server was started with a different --alias, so this one would 404.
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-32b")
    assert pg.installed_local_models() == []
    # ...but the catalog UI still shows it as installed.
    entry = next(m for m in pg.local_model_inventory() if m["id"] == "qwen3-8b")
    assert entry["installed"] is True
    assert entry["active"] is False


def test_the_inventory_reports_a_served_model(catalogue, served):
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    entry = next(m for m in pg.local_model_inventory() if m["id"] == "qwen3-8b")
    assert entry["installed"] is True and entry["active"] is True


def test_the_inventory_lists_the_whole_catalogue_when_nothing_is_downloaded(catalogue, served):
    served("")
    rows = pg.local_model_inventory()
    assert {m["id"] for m in rows} == {"qwen3-8b", "qwen3-32b"}
    assert not any(m["installed"] or m["active"] for m in rows)


def test_a_truncated_download_is_not_offered(catalogue, served):
    # A resumed transfer that was interrupted leaves a short file. Offering it
    # would put a model in the picker that fails on first use.
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    with open(catalogue.root / "qwen3-8b" / "Qwen3-8B-Q4_K_M.gguf", "r+b") as handle:
        handle.truncate(1024)
    assert pg.installed_local_models() == []


def test_the_url_is_not_used_to_derive_the_filename(catalogue, served):
    # The catalogue states 'file'. If a model were listed under a different url
    # basename, the downloader and this reader must still agree.
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    assert pg.installed_local_models()


def test_one_malformed_entry_costs_only_itself(catalogue, served):
    # A blank whole catalog reads as "this box has no models" and hides the very
    # model the operator is looking at, so a bad entry must be skipped alone.
    served("safi-qwen3-8b")
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    path = pathlib.Path(pg.LOCAL_CATALOGUE_PATH)
    payload = json.loads(path.read_text())
    payload["models"].insert(0, {"id": "broken", "alias": "safi-broken"})
    path.write_text(json.dumps(payload))
    assert [m["id"] for m in pg.local_model_inventory()] == ["qwen3-8b", "qwen3-32b"]


def test_a_missing_catalogue_is_not_an_error():
    # Normal deployments have no appliance catalogue at all, and the model list
    # must not depend on it existing.
    assert pg.installed_local_models("/nonexistent/local-models.json") == []


def test_a_corrupt_catalogue_is_not_an_error(tmp_path):
    bad = tmp_path / "local-models.json"
    bad.write_text("{not json")
    assert pg.installed_local_models(str(bad)) == []


def test_a_future_schema_version_is_refused(tmp_path):
    # Refusing is the safe direction: an unknown schema may mean the layout
    # changed, and guessing would report a model as installed when it is not.
    path = tmp_path / "local-models.json"
    path.write_text(json.dumps(dict(CATALOGUE, schema=2)))
    assert pg.installed_local_models(str(path)) == []


def test_a_catalogue_without_model_root_is_refused(tmp_path):
    payload = dict(CATALOGUE)
    payload.pop("model_root")
    path = tmp_path / "local-models.json"
    path.write_text(json.dumps(payload))
    assert pg.installed_local_models(str(path)) == []


# --------------------------------------------------------------------------
# list_models_for_org
# --------------------------------------------------------------------------

class FakeConfig:
    AVAILABLE_MODELS = [{"id": "gpt-oss-120b", "label": "GPT OSS 120B"}]
    LOCAL_MODEL_API_KEY = "local"
    GROQ_API_KEY = "g-k"
    OPENAI_API_KEY = ""
    ANTHROPIC_API_KEY = ""
    GEMINI_API_KEY = ""
    DEEPSEEK_API_KEY = ""
    MISTRAL_API_KEY = ""
    ZHIPU_API_KEY = ""
    CEREBRAS_API_KEY = ""


@pytest.fixture
def wired(monkeypatch, catalogue, served):
    """list_models_for_org with Config, org keys and custom rows stubbed out."""
    monkeypatch.setattr("safi_app.config.Config", FakeConfig, raising=False)
    monkeypatch.setattr(pg, "get_org_allowlist", lambda org_id: None)
    # Every known provider, so these tests turn on the local synthesis and not
    # on which provider a particular built-in id happens to route to.
    #
    # Patched on model_routing, not on pg: list_models_for_org now asks
    # effective_configured_providers(), which resolves the .env layer through
    # model_routing.configured_providers. Patching pg.configured_providers left
    # the real one running, so "every provider" silently became "whatever this
    # machine's .env happens to hold" and the built-in models vanished.
    monkeypatch.setattr("safi_app.core.services.model_routing.configured_providers",
                        lambda config: frozenset(pg.PROVIDER_METADATA))
    monkeypatch.setattr("safi_app.core.services.deployment_keys.deployment_key_providers",
                        lambda: frozenset())
    monkeypatch.setattr("safi_app.core.services.org_keys.org_key_providers",
                        lambda org_id: frozenset())
    monkeypatch.setattr("safi_app.core.services.model_routing.custom_models",
                        lambda: [])
    return catalogue


def _ids(org_id=None):
    return [m["id"] for m in pg.list_models_for_org(org_id)]


def test_the_installed_local_model_joins_the_picker(wired, served):
    wired.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    assert "safi-qwen3-8b" in _ids()


def test_the_picker_omits_a_model_that_is_not_downloaded(wired):
    assert "safi-qwen3-8b" not in _ids()


def test_the_local_entry_carries_provider_metadata(wired, served):
    wired.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    entry = next(m for m in pg.list_models_for_org(None) if m["id"] == "safi-qwen3-8b")
    assert entry["provider"] == "local"
    assert entry["provider_label"]
    # The provider must be local, never groq: an unset local key would send the
    # prompt to Groq with a placeholder.
    assert entry["provider"] != "groq"


def test_built_in_models_still_list(wired, served):
    wired.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    assert "gpt-oss-120b" in _ids()


def test_a_local_model_is_hidden_when_local_is_not_configured(wired, monkeypatch, served):
    wired.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    monkeypatch.setattr("safi_app.core.services.model_routing.configured_providers",
                        lambda config: frozenset(pg.PROVIDER_METADATA) - {"local"})
    assert "safi-qwen3-8b" not in _ids()


def test_a_local_model_respects_the_org_allowlist(wired, monkeypatch, served):
    wired.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    monkeypatch.setattr(pg, "get_org_allowlist", lambda org_id: frozenset({"groq"}))
    assert "safi-qwen3-8b" not in _ids()


def test_swapping_the_model_needs_no_write(wired, served):
    # The point of synthesizing: the operator downloads a different model and
    # the picker follows, with nothing to insert or update anywhere.
    served("safi-qwen3-8b")
    wired.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    assert "safi-qwen3-8b" in _ids()
    # The operator downloads the bigger one and the fetcher re-points the server.
    (wired.root / "qwen3-8b" / "Qwen3-8B-Q4_K_M.gguf").unlink()
    wired.populate("qwen3-32b", "Qwen3-32B-Q4_K_M.gguf", 19762149024)
    served("safi-qwen3-32b")
    ids = _ids()
    assert "safi-qwen3-32b" in ids
    assert "safi-qwen3-8b" not in ids


# --------------------------------------------------------------------------
# the safi-demo phantom
# --------------------------------------------------------------------------
#
# The ISO no longer ships a model, and llama-server serves exactly one --alias,
# so a hardcoded "safi-demo" entry is an id nothing answers to. It was offered
# in every picker on any install with the local key set -- which is every
# appliance -- and selecting it 404'd.

def test_safi_demo_is_not_in_the_shipped_catalog():
    from safi_app.config import Config
    ids = {m["id"] for m in Config.AVAILABLE_MODELS}
    assert "safi-demo" not in ids
    labels = {m["label"] for m in Config.AVAILABLE_MODELS}
    assert "SAFi Demo Model" not in labels


def test_the_local_provider_is_no_longer_labelled_the_demo_model():
    from safi_app.core.services.model_routing import PROVIDER_METADATA
    assert PROVIDER_METADATA["local"]["label"] != "SAFi Demo Model"
    assert "local" in PROVIDER_METADATA["local"]["label"].lower()


def test_no_faculty_default_names_a_model_the_server_never_serves():
    from safi_app import config as cm
    for provider, defaults in cm._FACULTY_DEFAULTS_BY_PROVIDER.items():
        for role, model in defaults.items():
            assert model, f"{provider}.{role} has no default"
            assert not model.startswith("safi-"), (
                f"{provider}.{role} defaults to {model}, a local alias that is "
                "whatever the operator downloaded, not a constant")


def test_the_local_key_alone_does_not_pick_a_phantom_model(monkeypatch, tmp_path):
    # A deferred install sets the local key and nothing else. Detection walks
    # local first, so it must decline rather than return a stale default.
    from safi_app import config as cm
    monkeypatch.setenv("SAFI_LOCAL_MODEL_API_KEY", "local")
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                 "OPENAI_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY",
                 "ZHIPU_API_KEY", "CEREBRAS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cm, "active_local_model", lambda: "")

    defaults = cm._detect_faculty_defaults()
    assert all(not m.startswith("safi-") for m in defaults.values()), defaults


def test_the_local_key_with_a_live_model_becomes_the_default(monkeypatch):
    from safi_app import config as cm
    monkeypatch.setenv("SAFI_LOCAL_MODEL_API_KEY", "local")
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                 "OPENAI_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY",
                 "ZHIPU_API_KEY", "CEREBRAS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cm, "active_local_model", lambda: "safi-qwen3-8b")

    defaults = cm._detect_faculty_defaults()
    assert defaults == {"intellect": "safi-qwen3-8b",
                        "conscience": "safi-qwen3-8b", "light": "safi-qwen3-8b"}


def test_detection_falls_through_to_a_cloud_key_when_no_local_model(monkeypatch):
    from safi_app import config as cm
    monkeypatch.setenv("SAFI_LOCAL_MODEL_API_KEY", "local")
    monkeypatch.setenv("GROQ_API_KEY", "g-key")
    monkeypatch.setattr(cm, "active_local_model", lambda: "")

    defaults = cm._detect_faculty_defaults()
    assert defaults["intellect"] == "openai/gpt-oss-20b"
    assert all(not m.startswith("safi-") for m in defaults.values())


def test_active_local_model_reads_the_served_alias_from_the_unit(tmp_path, monkeypatch):
    from safi_app import config as cm
    unit = tmp_path / "safi-llama-server.service"
    monkeypatch.setattr(cm, "LOCAL_MODEL_UNIT_PATH", str(unit))

    unit.write_text(
        "ExecStart=/opt/safi/bin/llama-server --model /var/lib/safi/models/"
        "qwen3-32b/m.gguf --host 127.0.0.1 --port 8081 --alias safi-qwen3-32b\n")
    assert cm.active_local_model() == "safi-qwen3-32b"

    # A unit that has been written but points elsewhere is what the server is
    # actually serving; the status file must not override it.
    status = tmp_path / "model-fetch.json"
    monkeypatch.setattr(cm, "LOCAL_MODEL_STATUS_PATH", str(status))
    status.write_text(json.dumps({"state": "done", "alias": "safi-phi4-mini",
                                  "activated": False}))
    assert cm.active_local_model() == "safi-qwen3-32b"

    # A verified download that was never activated has no unit, so nothing is
    # being served. Reporting the download here is what made the catalog claim
    # "Serving" for a model the server was not running.
    unit.unlink()
    assert cm.active_local_model() == ""

    unit.write_text("ExecStart=/opt/safi/bin/llama-server --model /m.gguf --port 8081\n")
    assert cm.active_local_model() == ""


# --------------------------------------------------------------------------
# GET /api/models/local
# --------------------------------------------------------------------------

def test_the_payload_reports_off_appliance_rather_than_erroring(tmp_path, monkeypatch):
    # Most SAFi deployments are not appliances and have no catalogue file. That
    # is an ordinary state, so it must not surface as a failure.
    monkeypatch.setattr(pg, "LOCAL_CATALOGUE_PATH", str(tmp_path / "absent.json"))
    payload = pg.local_catalog_payload()
    assert payload["ok"] is True
    assert payload["available"] is False
    assert payload["models"] == []
    assert payload["active"] is None
    assert "no on-appliance model catalogue" in payload["reason"]


def test_the_payload_reports_the_whole_catalogue_and_the_served_one(catalogue, served):
    catalogue.populate("qwen3-8b", "Qwen3-8B-Q4_K_M.gguf", 5027783488)
    served("safi-qwen3-8b")
    payload = pg.local_catalog_payload()

    assert payload["available"] is True
    assert {m["id"] for m in payload["models"]} == {"qwen3-8b", "qwen3-32b"}
    assert payload["active"] == "safi-qwen3-8b"
    by_id = {m["id"]: m for m in payload["models"]}
    assert by_id["qwen3-8b"]["active"] is True
    assert by_id["qwen3-32b"]["installed"] is False


def test_the_payload_has_no_active_model_when_none_is_served(catalogue, served):
    catalogue.populate("qwen3-32b", "Qwen3-32B-Q4_K_M.gguf", 19762149024)
    served("")
    payload = pg.local_catalog_payload()
    assert payload["active"] is None
    by_id = {m["id"]: m for m in payload["models"]}
    assert by_id["qwen3-32b"]["installed"] is True
    # Installed but not being served: the server still points at the old alias.
    assert by_id["qwen3-32b"]["active"] is False


def test_the_payload_carries_what_the_catalog_table_renders(catalogue, served):
    # The table prints label, size_human and min_ram; a missing key would render
    # "undefined" straight into the page.
    served("")
    for m in pg.local_catalog_payload()["models"]:
        assert m["label"] and isinstance(m["label"], str)
        assert m["size_human"].endswith("GB")
        assert m["min_ram"] > 0
        assert isinstance(m["installed"], bool)
        assert isinstance(m["active"], bool)
