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

## 6. The math, briefly

The full formal model — every stage's signature, the reflexion-retry
mechanics, and the worked equations — lives in
[MATHEMATICAL_SPECIFICATION.md](MATHEMATICAL_SPECIFICATION.md). This is
just enough notation to read that document without starting cold.

**Core objects per turn `t`:**

| Symbol | Meaning |
|---|---|
| $x_t$ | Input context (prompt + metadata) |
| $V = \{(v_i, w_i)\}$ | The agent's value set, weights summing to 1 |
| $a_t$ | The Intellect's draft response |
| $L_t = \{(v_i, s_{i,t}, c_{i,t})\}$ | Conscience's ledger: a continuous score $s_{i,t} \in [-1, 1]$ and confidence $c_{i,t} \in [0, 1]$ per value — **not** a discrete $\{-1, 0, +1\}$; the anchors are reference points, not buckets |
| $A_t \in [0, 1]$ | Spirit's *gating* alignment (confidence-free) — what Will's third pass checks against the threshold |
| $S_t \in [1, 10]$ | Spirit's *display* coherence score (confidence-weighted) — what the Audit Hub shows as "Alignment." **Not the same number as $A_t$** — the spec is explicit that conflating them is a bug class |
| $M_t$ | Memory state carried into the next turn |

**Faculties as functions:**

$$a_t = I(x_t, V, M_t) \quad\quad L_t = C(a_t, x_t, V) \quad\quad S_t, d_t, \mu_t = \text{Spirit}(L_t, V, M_t)$$

Will isn't a single decision — it's three separate deterministic passes
(structural, hard-gate, alignment), each able to redirect independently;
only the third can trigger a single reflexion retry. See §5 above for why
the faculties are shaped this way, and the full spec for exactly how each
pass gates the next.

## 7. Multi-agent architecture

SAFi isn't single-agent — an org runs as many agents side by side as it
wants. Each is a row in the `agents` table (`persistence/database.py:283-301`):
identity (name, avatar, worldview, style), a `policy_id`, its own model
per faculty (`intellect_model`/`will_model`/`conscience_model`), a scope
statement, a tool allow-list, and a `visibility` level (private / member /
auditor / editor / admin) gating who in the org can see it. `list_agents()`
(`database.py:2313-2340`) always returns the caller's own agents plus
org-mates' agents whose visibility clears the caller's role; built-in
demo agents are seeded conditionally via `SAFI_BUILTIN_AGENTS`.

- **Persona and policy are two tiers, not one binding.** `core/personas/*.py`
  (bible_scholar, contoso_admin, fiduciary, health_navigator, safi_steward,
  socratic_tutor) are default templates — each ships a fallback `policy_id`,
  but that's just a default an agent row can override. Policies are their
  own versioned entity (`policies` / `policy_versions`), so the same
  persona can run under different policies across agents, or be
  reattached to a new one without touching its identity. See
  `core/governance/demo/policies.py` for the two-tier model spelled out.
- **Synderesis compiles fresh every turn, not once at agent creation.**
  `Synderesis.get_profile()` (`faculties/synderesis.py:553-622`) — "the
  sole governance compiler" — resolves persona → policy → org Charter into
  the normalized value set, rubric set, and scope hard-gate that feed the
  rest of the pipeline (§5, §6). It runs per message from
  `api/conversations.py`, through a caching wrapper keyed on a governance
  fingerprint (`SAFiInstanceCache.get_or_create`, `database.py:128-134`) —
  not once at creation and cached forever. Practical consequence: editing
  a policy's values takes effect on the very next turn, for every agent
  attached to it, with no redeploy or per-agent rebuild step.
- **Selecting an agent is per-user, not per-conversation.** Agent choice
  lives on the user (`users.active_profile`, `database.py:67`), read on
  every send (`conversations.py:505`). Switching (`PUT /api/me/profile`,
  `auth.py:1083`) forces a full page reload and starts a new conversation
  (`app.js:628-650`) — there's no live, mid-thread agent switcher.
  `ui-model-selector.js` is a separate concern: it only picks the LLM
  model per faculty, not the agent itself.
- **The agent-wizard creates real agents, not just cosmetic variants.**
  `public/js/ui/agent-wizard/` is five steps — identity + policy attach,
  tools, model, safety, review — and produces a genuine new agent row
  (new `agent_key`, custom name/avatar/scope/model). Step 1 lets an admin
  attach an existing org policy or fall back to "Charter only." What it
  doesn't do is let an admin author values/rubrics inline: scored values
  always come from the attached policy (or the Charter as a floor), never
  from the wizard itself. Custom agents are real; custom scoring criteria
  still route through the policy system.

## 8. SSO authentication

Two OIDC providers are supported today: **Google Workspace** and
**Microsoft Entra ID (Azure AD)**. **SAML is not implemented yet** — it's
scoped as future work in
[SAML_SSO_PLAN.md](SAML_SSO_PLAN.md); don't point a customer at SAML
support until that plan is actually built. GitHub OAuth also exists in
`auth.py`, but it's a tool-connection flow (like Google Drive/SharePoint),
not a login method — don't confuse the two when reading the auth code.

**Local setup:** register an app with each provider and set the client
credentials in `.env`:

```bash
# Google — console.cloud.google.com/apis/credentials
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
# redirect URI must include: {WEB_BASE_URL}/api/callback/google

# Microsoft — portal.azure.com/#view/Microsoft_AAD_RegisteredApps
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
```

**Per-org enforcement** lives in `_org_claim_gate()`
(`safi_app/api/auth.py:135-169`), called from the Google web/mobile flows
(`auth.py:248-328`, `333-434`) and the Microsoft flow (`auth.py:615-707`).
Two things worth knowing before touching this code:

- **Pinning is opt-in, fail-open by default.** Until an org sets
  `google_hd` (Workspace domain) or `ms_tenant_id` (Entra tenant) — via
  `get_org_identity_config`/`set_org_identity_config`
  (`database.py:4594-4711`), surfaced in the Control Panel's Organization
  tab under "Identity & Sessions" (`ui-settings-org.js:252-301`) — *any*
  Google or Microsoft account can sign in. Configuring the tenant/domain
  is what turns on rejection, not a platform default.
- **`require_mfa` only checks Microsoft's `amr` claim, not Google's.**
  There's no equivalent MFA-evidence check in the Google branch — Google
  MFA is treated as attested by Workspace policy, not verified in code.
  An org relying on `require_mfa` to cover Google logins specifically is
  relying on something the code doesn't check.
- **`join_policy` defaults to `domain_auto_join`, silently, for every
  org.** `_resolve_membership()` (`auth.py:156-226`) auto-adds a user as
  `member` — no invite, no admin approval — when the org's `join_policy`
  is `domain_auto_join`/`both` (the three values live in
  `JOIN_POLICIES`, `database.py:4427`) and their email domain matches an
  org via `get_organization_by_domain()` (`database.py:2650-2659`). That
  lookup only ever matches orgs with `domain_verified=TRUE`, a flag set
  exclusively through a deliberate DNS TXT-record proof flow
  (`organizations.py:9-101`) — so a fresh, unverified org is inert to
  this path, not silently walk-in-able. But once an admin *does* verify
  their domain (a natural thing to do while setting up SSO), auto-join
  is live by default unless they've explicitly switched `join_policy` to
  `invite_only` in the Organization tab. Worth calling out to anyone
  configuring SSO for an org that doesn't want unapproved joins.
  Separately: the live demo (`/api/login/demo`, gated by
  `SAFI_ENABLE_DEMO`) is unrelated to any of this — it never touches
  `_resolve_membership`, and mints a fresh, isolated, 24h-expiring
  sandbox org per visitor instead.

## 9. The `/evaluate` gateway

`POST /api/evaluate` (`safi_app/api/evaluate_api.py:28`) is how an
external system — your own agent, a Teams/Telegram bot, anything —
routes its output through SAFi's governance pipeline. **The critical
thing to get right: this endpoint doesn't generate a response, it
evaluates one you already have.** You send the prompt *and* your
agent's already-generated output; SAFi audits and enforces against it.
There is no Intellect call here — SAFi is the evaluator, never the
author, and the response reflects that (`aiProvenance.generator` is
`"external-agent"`, not SAFi).

**Auth:** an `X-API-KEY` header or `Authorization: Bearer <key>`,
checked against the `api_keys` table (SHA-256 hash, never the raw key)
via `get_policy_id_by_api_key` (`database.py:4924`). Keys are scoped to
a **policy**, not an org — mint one with
`POST /api/policies/<policy_id>/keys`, rotate with
`.../rotate_key` (`policy_api_routes.py:255-320`). The raw key is shown
exactly once at creation; only its hash persists after that.

**Request:**

```json
{
  "agent_id": "fiduciary",
  "input": "What's your recommended asset allocation for a 30-year-old?",
  "output": "Here's what I'd suggest: 80% equities, 20% bonds...",
  "persona": "safi",
  "session_id": "my-app-conversation-42"
}
```

`agent_id`, `input`, and `output` are required — a `400` lists whichever
are missing. `persona` defaults to `"safi"`; `session_id` defaults to
`agent_id` and gets a `gw_` prefix if you don't supply one.

**Response** (built in `orchestrator.py:1178-1190`, then two fields
added by the route handler):

```json
{
  "decision": "approve",
  "stage": "conscience",
  "reason": "...",
  "evaluatedOutput": "Here's what I'd suggest: 80% equities, 20% bonds...",
  "outputRepaired": false,
  "conscienceLedger": [ { "value": "Fiduciary Duty", "score": 0.8, "confidence": 0.9 } ],
  "spirit_score": 8,
  "drift": 0.02,
  "policyId": "fiduciary_advisory_policy",
  "policyVersion": 3,
  "messageId": "b2e1...",
  "conversationId": "gw_my-app-conversation-42",
  "audit_status": "complete",
  "caller_obligations": {
    "eu_ai_act_art_50_1": "If this output is presented to end users, the duty to disclose that they are interacting with an AI system rests with the deploying caller."
  },
  "aiProvenance": {
    "ai_generated": true,
    "marking_standard": "EU-AI-Act-Art-50(2)",
    "evaluator": "SAFi",
    "generator": "external-agent"
  }
}
```

The `X-AI-Generated: true` header is set alongside the body
(`provenance.mark_json_response`). `caller_obligations` exists because
the Art. 50(1) disclosure duty follows whoever actually faces the end
user — that's your app, not SAFi, so the gateway reminds you of it on
every call rather than assuming you've read the compliance docs.

A few things worth knowing before integrating against this:

- **A governed rejection is still `200 OK`.** Blocked or violating
  output comes back as `"decision": "violation"` with a normal success
  status — check the `decision` field, not the HTTP status code, to
  know whether your output was approved.
- **It's a reduced pipeline, not the full five faculties.** No
  Intellect (nothing to generate), no Will redirect/reflexion machinery
  — just Phase 0's injection gate on the input, then Conscience → hard
  gates → Spirit's alignment threshold, the same `_finalize_draft` path
  native chat turns use. It still writes a full governance record and a
  hash-chained audit trail entry (mode `evaluate_gateway`) — evaluated
  turns are audited exactly like native ones.
- **Provider governance still applies fail-closed.** The Conscience
  call respects the org's LLM allow-list the same way native turns do.
- **There's no rate limiting or request-size cap today.** Nothing in
  `create_app()` enforces one — worth knowing if you're integrating a
  high-volume caller, and worth adding before this becomes a
  production bottleneck.