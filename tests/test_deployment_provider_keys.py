"""Deployment-wide provider keys: the layer under .env.

An appliance has no organization, so the org-scoped key endpoints were
unreachable and the Model Catalog's provider dropdown rendered empty — "add a
cloud model" with nothing to pick. These keys are the fix, so the tests here are
about the three things that had to be true: a stored deployment key makes a
provider dispatchable, an org key still wins over it, and neither layer
disturbs the .env default.
"""
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
    """Stand in for the encrypted table with a plaintext dict."""
    def _set(mapping):
        monkeypatch.setattr(dk, "deployment_key_map", lambda: dict(mapping))
    return _set


# --------------------------------------------------------------------------
# precedence
# --------------------------------------------------------------------------

def test_the_env_key_is_used_when_nothing_is_stored():
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-env"


def test_a_deployment_key_overrides_the_env_key(stored):
    stored({"groq": "gsk-from-db"})
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-db"


def test_an_org_key_still_wins_over_a_deployment_key(stored, monkeypatch):
    # The layering that keeps tenant billing separation intact: an org key beats
    # anything the deployment stored.
    stored({"groq": "gsk-from-db"})
    from safi_app.core.services import org_keys
    monkeypatch.setattr(org_keys, "active_org_key", lambda p: "gsk-from-org")
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-org"


def test_a_stored_key_for_another_provider_does_not_leak(stored):
    stored({"groq": "gsk-from-db"})
    assert dk.resolve_provider_key("openai", "sk-from-env") == "sk-from-env"
    assert dk.resolve_provider_key("openai", None) is None


def test_a_db_failure_falls_back_to_the_env_key(monkeypatch):
    # Never let the key layer take down a turn: the .env default still works.
    def _boom():
        raise RuntimeError("database is gone")
    monkeypatch.setattr(dk, "deployment_key_map", _boom)
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-env"
    assert dk.deployment_key_providers() == frozenset()


# --------------------------------------------------------------------------
# the configured-provider set the catalog is built from
# --------------------------------------------------------------------------

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
    # The original bug, pinned: with no cloud key anywhere the catalog's
    # provider list is just the local appliance.
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
    # A different org must not inherit it, or the picker would offer a model
    # whose provider has no key for that tenant.
    assert "openai" not in model_routing.effective_configured_providers(_Cfg(), "org-2")
    assert "openai" not in model_routing.effective_configured_providers(_Cfg(), None)


def test_a_broken_key_layer_still_reports_the_env_providers(stored, monkeypatch):
    # Hiding every provider on a DB hiccup would empty the model picker; the
    # .env set is a safe floor.
    from safi_app.core.services import model_routing
    monkeypatch.setattr(dk, "deployment_key_providers",
                        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert model_routing.effective_configured_providers(_Cfg()) == frozenset({"local"})


def test_model_provider_configured_sees_a_stored_key(stored):
    from safi_app.core.services.model_routing import model_provider_configured
    stored({"groq": "gsk-from-db"})
    assert model_provider_configured("llama-3.3-70b-versatile", _Cfg()) is True


# --------------------------------------------------------------------------
# cache behaviour
# --------------------------------------------------------------------------

def test_the_map_is_cached_so_dispatch_does_not_query_every_turn(monkeypatch):
    # Every faculty turn and every background task resolves a key. Without the
    # TTL cache that is a DB round-trip per provider per call.
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
    # Same posture as org_keys: a readable stored key must not silently fall
    # back to .env because of a transient DB error, or the call would bill to
    # the wrong account.
    from safi_app.persistence import database as db
    monkeypatch.setattr(dk, "_cache_entry", (0.0, {"groq": "gsk-from-db"}))  # past the TTL

    def _boom():
        raise RuntimeError("database is gone")

    monkeypatch.setattr(db, "get_deployment_provider_keys_decrypted", _boom)
    assert dk.deployment_key_map() == {"groq": "gsk-from-db"}


def test_a_cold_cache_and_a_failed_read_yield_no_keys(monkeypatch):
    # With nothing cached there is no key to protect, so an empty map is correct
    # and resolve_provider_key falls through to .env.
    from safi_app.persistence import database as db
    monkeypatch.setattr(dk, "_cache_entry", None)

    def _boom():
        raise RuntimeError("database is gone")

    monkeypatch.setattr(db, "get_deployment_provider_keys_decrypted", _boom)
    assert dk.deployment_key_map() == {}
    assert dk.resolve_provider_key("groq", "gsk-from-env") == "gsk-from-env"


# --------------------------------------------------------------------------
# who may set a deployment-wide key
# --------------------------------------------------------------------------
# A deployment key changes what every org on the install dispatches against, so
# on a multi-tenant install an org admin must not be able to set one. Gating on
# SAFI_SUPER_ADMINS alone would lock the appliance out, because that defaults to
# blank and an org-less appliance's admin IS the deployment.

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
    # The escalation this guard exists to stop: an org admin silently changing
    # which provider key every OTHER org dispatches against.
    assert _forbidden(org_count=3, mode='multi', operator=False, monkeypatch=monkeypatch) == 403


def test_the_admin_of_an_org_less_appliance_may_set_one(monkeypatch):
    # No orgs means no other tenant to affect, so admin == deployment owner.
    assert _forbidden(org_count=0, mode='single', operator=False, monkeypatch=monkeypatch) is None


def test_the_admin_of_a_default_single_tenant_install_may_set_one(monkeypatch):
    # The commonest install there is, and the case a count-only test got wrong:
    # single-tenant mode still CREATES one org on first login, so a stock
    # install holds exactly one row. Treating "one org" as multi-tenant locked
    # the ordinary admin out of the pane that exists for them.
    assert _forbidden(org_count=1, mode='single', operator=False, monkeypatch=monkeypatch) is None


def test_single_tenant_mode_does_not_excuse_an_install_that_grew_tenants(monkeypatch):
    # The mirror image: SAFI_TENANCY_MODE left on 'single' after several orgs
    # were created. Trusting the declared mode alone would let any one of those
    # orgs retarget everyone else's dispatch.
    assert _forbidden(org_count=4, mode='single', operator=False, monkeypatch=monkeypatch) == 403


def test_multi_tenant_mode_is_not_overridden_by_having_one_org(monkeypatch):
    # A multi-tenant deployment's first org exists before its second, and in
    # that window a deployment key set by its admin would be inherited by every
    # tenant that joins later.
    assert _forbidden(org_count=1, mode='multi', operator=False, monkeypatch=monkeypatch) == 403


def test_the_guard_fails_closed_when_the_org_count_cannot_be_read(monkeypatch):
    # Assuming single-tenant on a DB error would hand a multi-tenant install's
    # keys to any admin, which is the one outcome not acceptable here.
    assert _forbidden(org_count=0, mode='single', count_raises=True, monkeypatch=monkeypatch) == 403
