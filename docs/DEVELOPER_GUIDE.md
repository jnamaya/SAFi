# SAFi Developer Guide

**Last updated:** July 2026. This is the orientation document for anyone
working on SAFi's code — repo map, request lifecycle, the invariants you
must not break, testing patterns, and recipes for common changes. For the
product overview see the [README](../README.md); for the formal model see
the [Mathematical Specification](MATHEMATICAL_SPECIFICATION.md).

## 1. Front-end structure

The front-end is plain HTML, JavaScript, and CSS — no framework. That's a
deliberate choice: I don't have hands-on experience with any front-end
framework, and a governance product benefits from fewer dependencies to
keep the security surface small. You're welcome to port it to a framework
of your choice; nothing about the backend assumes vanilla JS.

```
public/
├── index.html            # single-page app shell
├── sw.js                 # service worker (offline cache)
├── package.json, package-lock.json, tailwind.config.js   # Tailwind build only
├── css/
│   ├── input.css          # Tailwind source
│   ├── main.css            # built output — regenerate after class changes (§2)
│   ├── styles.css          # hand-written styles outside Tailwind
│   └── highlight-theme.css
├── assets/                # images, SVG icons, static reference/marketing pages
└── js/
    ├── core/               # bootstrap, API client, chat engine, cache, utils
    │   ├── app.js
    │   ├── api.js
    │   ├── chat.js
    │   ├── cache.js
    │   └── utils.js
    ├── services/           # offline-manager.js, tts-audio.js
    ├── lib/                # vendored third-party (marked, purify, highlight.js)
    └── ui/
        ├── ui.js, ui-messages.js, ui-composer-menu.js, ...   # chat UI
        ├── agent-wizard/    # multi-step agent creation flow
        ├── policy-wizard/   # multi-step policy authoring flow
        ├── settings/        # Control Panel tabs, one module per tab (§6 recipe)
        └── shared/          # shared widgets (tool-picker.js)
```

## 2. Local development

**Fastest:** `docker compose up` (see the README Quick Start) — includes
MySQL. **Native:**

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env    # set DB_*, one LLM key, SAFI_ENCRYPTION_KEY
venv/bin/python run.py  # dev server; schema auto-creates via init_db()
```

Useful `.env` toggles for development: `SAFI_LOCAL_ADMIN_EMAIL/PASSWORD`
(skip OAuth), `SAFI_ENABLE_DEMO=true` (one-click demo login),
`SAFI_DEBUG_JSONL_LOGS=true` (plaintext per-turn logs on disk — debug only,
default off). Production runs under systemd (`safi.service`, gunicorn) with
a daily `safi-retention-purge.timer` — example units for both live in
`deploy/systemd/`. The Docker stack runs an equivalent `purge` service, so
retention policies execute in both deployment styles.

After backend changes, restart the service; after frontend changes that
touch Tailwind classes:

```bash
cd public && npx tailwindcss -i ./css/input.css -o ./css/main.css
# then bump the css/main.css?v=... cache-buster in public/index.html
```

## 3. The request lifecycle (read this before touching the pipeline)

A chat turn enters at `conversations.py:process_prompt_endpoint` and flows
through `SAFi.process_prompt` (orchestrator.py):

1. **Phase 0** — deterministic pre-generation gate (injection signatures,
   blacklists) on the raw prompt.
2. **Phases 1–2** — Intellect gathers context (RAG, memory, tools) and
   drafts. The Intellect only produces *intents*; it never executes.
3. **Phase 3** — structural Will checks (disclaimers, allowed syntax).
4. **Phase 4** — Conscience audit: per-value scores (−1..+1) + confidence
   + written justification = the ledger.
5. **Phase 5** — hard gates and the alignment threshold; one Reflexion
   retry on a failing score; Spirit integrates approved turns into the
   per-agent EMA (drift = consistency signal).
6. **Phase 6** — commit. **This is the important part:**

Every turn terminates in `db.update_audit_results()` — all four terminal
paths (approve, persona redirect, system-failure notice, `/evaluate`
gateway) funnel there. Inside ONE transaction it: journals the prior row
state to the hash-chained `chat_audit_trail`, updates `chat_history`,
runs the review-sampling hook, and writes the encrypted per-turn
`governance_records` row. If you add anything that must be atomic with a
turn, it goes on that cursor, isolated the same way (an exception in your
hook must log and skip, never block the commit).

## 4. Invariants — break these and you break the product's claims

- **Encryption is accessor-layer with dual-read.** Sensitive columns are
  Fernet tokens written via `crypto.encrypt_value` and read via
  `crypto.decrypt_value`, which passes legacy plaintext through unchanged.
  Never query encrypted columns with SQL (`LIKE` won't work); search paths
  decrypt-and-scan under hard row caps. New sensitive columns go into
  `scripts/backfill_encryption.py`'s manifest.
- **Evidence-logging rides the same transaction.** Any org-level config
  change (retention, providers, review rules, offline switch) calls
  `append_compliance_log(..., cursor=cursor)` inside the transaction that
  applies the change — a change can never dodge the evidence log. Exports
  of decrypted data custody-log BEFORE streaming; no evidence, no export.
- **The audit trail is append-only and hash-chained.** Never UPDATE or
  DELETE `chat_audit_trail` rows outside the retention purge's
  whole-chain rule. Every `chat_history` mutation journals prior state via
  `_chat_trail_append` on the same cursor.
- **Provider governance fails closed.** Every LLM dispatch — including
  background tasks — asserts the org's allow-list via
  `provider_governance`. New model calls must route through
  `LLMProvider` / `_backend_json_completion`, never a raw client.
- **`governance_records` has no FK by design.** Org-attributed records
  survive member deletion (supervisory evidence); personal (org-NULL)
  records erase on user delete; only the retention purge destroys org
  records. Any new deletion path must call
  `_erase_personal_governance_records` or consciously decide otherwise.
- **UI vocabulary.** User-facing metrics are **Alignment** (spirit score
  /10) and **Consistency** ((1 − drift) × 100%); a null score renders
  **N/A**, never a default; "Compliance Score" is banned. Faculty names
  stay in code/architecture docs, not in capability claims.
- **AI output marking.** Any new surface that emits AI-generated content
  must carry the Art. 50(2) marker (`core/provenance.py`): the
  `aiProvenance` body object and/or the `X-AI-Generated` header, and
  per-message `ai_generated` flags in exports.

## 5. Testing

Tests are integration tests against a live local MySQL — no mocks of the
database layer. Run them individually:

```bash
venv/bin/python tests/test_governance_records.py
```

Patterns to copy: create real org/user/conversation fixtures in
`setUpClass` and delete them (in FK-safe order) in `tearDownClass`; forge
an authenticated session with `client.session_transaction()` setting
`sess["user"]` (+ `sess["user_id"]`); test RBAC by role, org isolation
with a second org, and evidence by reading `org_compliance_log`. Existing
suites are the spec: `test_review_api.py` (API + RBAC),
`test_governance_records.py` (transactional write paths),
`test_retention_purge.py` (purge semantics).

## 6. Recipes

- **Add an LLM provider:** entry in `PROVIDER_METADATA` (label + verified
  `baa_capable` / `eu_hostable` / `zdr` flags — do not guess these) and
  `build_providers_config` in `model_routing.py`; a prefix rule in
  `detect_provider`; models into `Config.AVAILABLE_MODELS`.
- **Add an API surface:** blueprint in `safi_app/api/`, register it in
  `create_app()` with the `/api` prefix; guard with
  `require_role`/`require_any_role` plus the explicit org-match 403
  (copy `audit_api.py`).
- **Add a table or column:** `CREATE TABLE IF NOT EXISTS` or a guarded
  `SHOW COLUMNS`/information_schema `ALTER` in `init_db()` — migrations
  run automatically at startup; there is no separate migration tool.
- **Add a Control Panel tab:** module in `public/js/ui/settings/`
  (copy `ui-settings-review.js`), lazy-load hook in
  `ui-settings-core.js`, nav entry + RBAC flag in `app.js`.
- **Change rag/docs content:** rebuild the index or the agents won't see
  it (paths are cwd-relative, so run from `rag/`):
  `cd rag && ../venv/bin/python build_index_v2.py --name safi --source_dir docs`,
  then restart the service.

## 7. Documentation map

| Doc | What it is |
|---|---|
| [MATHEMATICAL_SPECIFICATION.md](MATHEMATICAL_SPECIFICATION.md) | Formal model of the faculties and scoring |
| [PHILOSOPHY.md](PHILOSOPHY.md) / [ORIGIN_STORY.md](ORIGIN_STORY.md) | Why the architecture looks like this |
| [SEC_COMPLIANCE_READINESS.md](SEC_COMPLIANCE_READINESS.md), [EU_AI_ACT_READINESS.md](EU_AI_ACT_READINESS.md), [HIPAA_READINESS.md](HIPAA_READINESS.md) | Per-regime readiness: shipped vs pending |
| [DATA_ERASURE_AND_RETENTION.md](DATA_ERASURE_AND_RETENTION.md) | Erasure vs retention position |
| [MONITORING_PLAN.md](MONITORING_PLAN.md) | Art. 72 post-market monitoring plan |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution workflow |
