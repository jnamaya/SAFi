import time

import pytest

from safi_app.core.services import deployment_keys as dk


@pytest.fixture(autouse=True)
def _clear_cache():
    dk.invalidate_deployment_keys_cache()
    yield
    dk.invalidate_deployment_keys_cache()


@pytest.fixture
def stored(monkeypatch):
    def _set(mapping):
        monkeypatch.setattr(dk, "deployment_key_map", lambda: dict(mapping))
    return _set


def test_the_env_key_is_used_when_nothing_is_stored():
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-env"


def test_a_deployment_key_overrides_the_env_key(stored):
    stored({"groq": "gsk-from-db"})
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-db"


def test_an_org_key_still_wins_over_a_deployment_key(stored, monkeypatch):
    stored({"groq": "gsk-from-db"})
    from safi_app.core.services import org_keys
    monkeypatch.setattr(org_keys, "active_org_key", lambda p: "gsk-from-org")
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-org"


def test_a_stored_key_for_another_provider_does_not_leak(stored):
    stored({"groq": "gsk-from-db"})
    assert dk.resolve_provider_key("openai", "sk-from-env") == "sk-from-env"
    assert dk.resolve_provider_key("openai", None) is None


def test_a_db_failure_falls_back_to_the_env_key(monkeypatch):
    def _boom():
        raise RuntimeError("database is gone")
    monkeypatch.setattr(dk, "deployment_key_map", _boom)
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-env"
    assert dk.deployment_key_providers() == frozenset()


class _Cfg:
    GROQ_API_KEY = ""
    OPENAI_API_KEY = ""
    ANTHROPIC_API_KEY = ""
    GEMINI_API_KEY = ""
    MISTRAL_API_KEY = ""
    DEEPSEEK_API_KEY = ""
    CEREBRAS_API_KEY = ""
    ZHIPU_API_KEY = ""
    LOCAL_MODEL_API_KEY = "local"


def test_the_env_layer_alone_configures_only_local(stored):
    from safi_app.core.services.model_routing import effective_configured_providers
    stored({})
    assert effective_configured_providers(_Cfg()) == frozenset({"local"})


def test_a_stored_deployment_key_adds_the_provider_to_the_catalog(stored):
    from safi_app.core.services.model_routing import effective_configured_providers
    stored({"groq": "gsk-from-db"})
    assert "groq" in effective_configured_providers(_Cfg())


def test_an_org_key_counts_for_that_org_only(stored, monkeypatch):
    from safi_app.core.services import model_routing, org_keys
    stored({})
    monkeypatch.setattr(org_keys, "org_key_providers", lambda o: frozenset({"openai"}) if o == "org-1" else frozenset())
    assert "openai" in model_routing.effective_configured_providers(_Cfg(), "org-1")
    assert "openai" not in model_routing.effective_configured_providers(_Cfg(), "org-2")
    assert "openai" not in model_routing.effective_configured_providers(_Cfg(), None)


def test_a_broken_key_layer_still_reports_the_env_providers(stored, monkeypatch):
    from safi_app.core.services import model_routing
    monkeypatch.setattr(dk, "deployment_key_providers",
                        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert model_routing.effective_configured_providers(_Cfg()) == frozenset({"local"})


def test_model_provider_configured_sees_a_stored_key(stored):
    from safi_app.core.services.model_routing import model_provider_configured
    stored({"groq": "gsk-from-db"})
    assert model_provider_configured("llama-3.3-70b-versatile", _Cfg()) is True


def test_the_map_is_cached_so_dispatch_does_not_query_every_turn(monkeypatch):
    from safi_app.persistence import database as db
    calls = []

    def _counting():
        calls.append(1)
        return {"groq": "gsk-from-db"}

    monkeypatch.setattr(db, "get_deployment_provider_keys_decrypted", _counting)
    monkeypatch.setattr(dk, "_cache_entry", None)

    assert dk.deployment_key("groq") == "gsk-from-db"
    assert dk.deployment_key("openai") is None
    assert dk.deployment_key_providers() == frozenset({"groq"})
    assert len(calls) == 1, "the map must be read once per TTL window, not per lookup"


def test_a_fresh_entry_is_reused_without_touching_the_database(monkeypatch):
    from safi_app.persistence import database as db

    def _boom():
        raise AssertionError("a warm cache must not read the database")

    monkeypatch.setattr(db, "get_deployment_provider_keys_decrypted", _boom)
    monkeypatch.setattr(dk, "_cache_entry", (time.monotonic(), {"groq": "gsk-warm"}))
    assert dk.deployment_key("groq") == "gsk-warm"


def test_invalidating_the_cache_drops_the_singleton():
    dk._cache_entry = (0.0, {"groq": "stale"})
    dk.invalidate_deployment_keys_cache()
    assert dk._cache_entry is None


def test_a_stale_map_is_kept_when_the_read_fails(monkeypatch):
    from safi_app.persistence import database as db
    monkeypatch.setattr(dk, "_cache_entry", (0.0, {"groq": "gsk-from-db"}))

    def _boom():
        raise RuntimeError("database is gone")

    monkeypatch.setattr(db, "get_deployment_provider_keys_decrypted", _boom)
    assert dk.deployment_key_map() == {"groq": "gsk-from-db"}


def test_a_cold_cache_and_a_failed_read_yield_no_keys(monkeypatch):
    from safi_app.persistence import database as db
    monkeypatch.setattr(dk, "_cache_entry", None)

    def _boom():
        raise RuntimeError("database is gone")

    monkeypatch.setattr(db, "get_deployment_provider_keys_decrypted", _boom)
    assert dk.deployment_key_map() == {}
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-env"


def _forbidden(*, org_count, mode='multi', operator=False, count_raises=False, monkeypatch):
    from flask import Flask
    from safi_app.api import model_api_routes as mar
    from safi_app.config import Config
    from safi_app.persistence import database as db
    monkeypatch.setattr(mar, "_is_deployment_operator", lambda: operator)
    monkeypatch.setattr(Config, "TENANCY_MODE", mode)
    if count_raises:
        def _boom():
            raise RuntimeError("database is gone")
        monkeypatch.setattr(db, "count_organizations", _boom)
    else:
        monkeypatch.setattr(db, "count_organizations", lambda: org_count)
    with Flask(__name__).test_request_context():
        result = mar._deployment_keys_forbidden()
    return result[1] if isinstance(result, tuple) else result


def test_a_named_operator_may_set_a_deployment_key_on_a_multi_tenant_install(monkeypatch):
    assert _forbidden(org_count=7, operator=True, monkeypatch=monkeypatch) is None


def test_an_org_admin_may_not_set_a_deployment_key_when_tenants_exist(monkeypatch):
    assert _forbidden(org_count=3, mode='multi', operator=False, monkeypatch=monkeypatch) == 403


def test_the_admin_of_an_org_less_appliance_may_set_one(monkeypatch):
    assert _forbidden(org_count=0, mode='single', operator=False, monkeypatch=monkeypatch) is None


def test_the_admin_of_a_default_single_tenant_install_may_set_one(monkeypatch):
    assert _forbidden(org_count=1, mode='single', operator=False, monkeypatch=monkeypatch) is None


def test_single_tenant_mode_does_not_excuse_an_install_that_grew_tenants(monkeypatch):
    assert _forbidden(org_count=4, mode='single', operator=False, monkeypatch=monkeypatch) == 403


def test_multi_tenant_mode_is_not_overridden_by_having_one_org(monkeypatch):
    assert _forbidden(org_count=1, mode='multi', operator=False, monkeypatch=monkeypatch) == 403


def test_the_guard_fails_closed_when_the_org_count_cannot_be_read(monkeypatch):
    assert _forbidden(org_count=0, mode='single', count_raises=True, monkeypatch=monkeypatch) == 403
