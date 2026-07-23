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
│   ├── main.css            # built output — regenerate after class changes (§4)
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
        ├── settings/        # Control Panel tabs, one module per tab (§8 recipe)
        └── shared/          # shared widgets (tool-picker.js)
```

## 2. Back-end structure

The backend is pure Python — it's the core of the system. SAFi uses MySQL
as its database, also a deliberate choice: it's the database I'm most
familiar with. Unlike the front-end, this one isn't a free swap — the
persistence layer (`persistence/database.py`) leans on MySQL-specific SQL
and runs its own ad hoc schema-migration guards at startup rather than
using a migration tool, so moving to Postgres or another database would
mean a real rewrite, not a drop-in change.

SAFi's backend is headless: you can connect to it from any API-based
client — Teams, Telegram, or anything else that can make API calls.

```
safi_app/
├── __init__.py            # create_app() factory; calls init_db() at boot
├── config.py               # env-driven Config class
├── models.py
├── extensions.py
├── persistence/
│   ├── database.py          # ~5k lines — all SQL, schema guards, init_db()
│   └── crypto.py             # Fernet encrypt/decrypt, key rotation
├── api/                    # Flask blueprints, one per surface
│   ├── auth.py               # OIDC/SSO, sessions, local login
│   ├── conversations.py      # chat turn endpoint (process_prompt_endpoint)
│   ├── evaluate_api.py        # /evaluate gateway for external callers
│   └── organizations.py, audit_api.py, review_api.py, incidents_api.py, ...
└── core/
    ├── orchestrator.py        # SAFi.process_prompt — the §5 phase pipeline
    ├── orchestrator_mixins/   # suggestions, tasks, tts
    ├── faculties/             # intellect, will, conscience, spirit, synderesis
    ├── governance/            # per-org policy definitions (safi/, contoso/, demo/)
    ├── personas/              # persona system prompts
    ├── plugins/, mcp_servers/ # tool/plugin integrations
    ├── services/              # llm_provider, model_routing, provider_governance, rag_service, ...
    └── rbac.py, permissions.py, provenance.py, totp.py, threat_intel.py, ...
```

Supporting top-level directories:

```
run.py, wsgi.py, asgi.py   # entry points — dev server, WSGI, ASGI
scripts/                    # retention_purge.py, backfill_encryption.py, backup_verify.py, ...
tests/                       # integration tests against live MySQL (§7)
rag/                          # index builder + doc sources for agent retrieval
deploy/systemd/                # example units for production
teams_bot.py, telegram_bot.py   # bot-channel integrations
```

## 3. Mobile structure

The Android app is a thin Capacitor shell around the same web app the
browser serves — no separate UI to maintain. `chat/`, the folder
Capacitor actually bundles into the APK, is never hand-edited or
committed: `build.sh` regenerates it from `public/` via `rsync` before
every build, so the app can't ship a stale copy of the front-end. See
[§1](#1-front-end-structure) for what's in `public/`.

```
mobile/
├── build.sh                # rsyncs public/ → chat/, then npx cap sync && gradlew
├── capacitor.config.ts       # app id, webDir, GoogleAuth client IDs, allowNavigation
├── package.json, package-lock.json   # Capacitor CLI + plugin deps
├── icons/, assets/            # app icon source images (input to @capacitor/assets)
├── www/                       # PWA manifest.json (unused by the current webDir)
├── chat/                      # generated from ../public — gitignored, never commit
└── android/                  # native Android project
    ├── local.properties        # SDK path — machine-specific, gitignored, recreate per machine
    ├── app/
    │   ├── src/main/AndroidManifest.xml
    │   ├── src/main/java/com/safi/app/MainActivity.java
    │   └── src/main/res/        # launcher icons, splash screens
    └── build.gradle, settings.gradle, gradlew, ...   # standard Gradle wrapper project
```

## 4. Setting up SAFi on your local machine

Setting up SAFi is easy — just make sure you have Git and Docker installed
first.

```bash
git clone https://github.com/jnamaya/SAFi.git
cd SAFi
cp .env.example .env   # set at least one AI model API key, plus your MySQL and local admin credentials
docker compose up
```

Visit `http://localhost:5000` once it's up.

## 5. Understanding SAFi

SAFi is a governance layer, not a chatbot framework. It wraps whatever LLM
you point it at in a deterministic evaluation-and-enforcement pipeline
that decides what actually reaches the user — and produces a verifiable
record of that decision. The model is a component it governs, not the
thing it is.

The architecture is a separation of powers across five faculties,
modeled on the classical faculties of the soul (see
[ORIGIN_STORY.md](ORIGIN_STORY.md) and [PHILOSOPHY.md](PHILOSOPHY.md) for
why). If you want the primary source, the relevant background is Aquinas,
*Summa Theologiae*, I-II, Q. 79 (on the faculties of practical reason) —
not required reading, but useful if the terminology below raises
questions:

- **Synderesis** compiles the immutable baseline before any turn runs —
  the governing policy, scope boundaries, and value weights for the
  agent.
- **Intellect** is the LLM itself. It drafts a response or proposes a
  tool call, nothing more. It operates inside an **Air Gap**: it can
  produce *intents*, never execute them — whatever the model outputs, it
  cannot itself take an action.
- **Will** approves or vetoes the Intellect's proposal, checking
  structural rules and the Conscience's ledger.
- **Conscience** evaluates the proposal against the governing policy's
  values, producing a scored ledger (−1.0 to +1.0 per value) with a
  written justification for each score.
- **Spirit** is long-term memory: it integrates Conscience's scores into
  a rolling per-agent EMA, detecting behavioral drift over time and
  feeding coaching back into future turns.

Every turn runs this as a synchronous, seven-phase loop — Phase 0's
pre-generation gate through Phase 6's commit (the phase-by-phase
mechanics get their own section later in this doc). The loop doesn't
just produce a response: it produces a governance record — the draft,
the ledger, the enforcement decision, and the exact policy version in
force — written to a hash-chained, tamper-evident audit trail. That
record, not the chat reply, is what an auditor or examiner actually
relies on afterward.

One important caveat: keeping the philosophical vocabulary doesn't mean
SAFi tries to replicate the human soul. The terms are borrowed the way
the Wright brothers borrowed "wing" from birds — for the concept, not to
replicate the mechanism. SAFi is a moral actor — it acts within a moral framework — not a moral
agent capable of bearing responsibility for it.