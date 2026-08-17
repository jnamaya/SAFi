# SAFi Agent & Policy Specification

> **Version:** 1.0
> **Last updated:** 2026-08-17
> **Status:** Descriptive. The code is the authority; this document names the
> shapes it accepts so you can build on them. Verified against the tree at
> the commit that introduced this file.

This is the write-side contract: the shapes User Space (the ULB) hands the
TCB to define what gets governed. The read-side contract, everything the
TCB produces, is the
[Governance Artifact Specification](GOVERNANCE_ARTIFACT_SPECIFICATION.md).
Together they bound the interface: a custom wizard, an admin tool, or a
framework integration is built against these two documents, never against
`synderesis.py`.

One rule governs everything below: **you configure what the TCB enforces;
you never invoke enforcement directly.** Every field here is data that
`get_profile()` compiles into a governed profile fresh on each turn.

## 1. The value / standard shape (shared by policies, charters, and AI standards)

The most important shape in the system. One entry per value:

```json
{
  "name": "Evidence First",
  "weight": 0.3,
  "hard_gate": false,
  "gate_reason": "grounding_violation",
  "description": "Claims must derive from provided evidence.",
  "rubric": {
    "description": "What this value checks.",
    "scoring_guide": [
      {"score": 1.0, "descriptor": "Compliant: ..."},
      {"score": 0.0, "descriptor": "Partial: ..."},
      {"score": -1.0, "descriptor": "Violation: ..."}
    ]
  }
}
```

| Field | Type | Rules |
|---|---|---|
| `name` (or `value`) | string | The identity. The Conscience's ledger entries and the Will's gate matching key off it, normalized (case- and whitespace-insensitive). |
| `weight` | float | **Relative, not absolute.** Values are weighed against each other and rescaled to their tier's share of the score (see section 4). Scored values must have `weight > 0`; hard gates are pinned to `0.0` at compile time regardless of what you send. |
| `hard_gate` | bool | `true` makes this a pass/fail gate: a ledger score of `-1.0` blocks the response outright, and the value is excluded from the alignment average. Gates are not free: every gate must appear in the Conscience's ledger on every turn or the Will fails closed. |
| `gate_reason` | string | Hard gates only. One of `scope_violation`, `grounding_violation`, `ethical_violation`. Routes the redirect when the gate fails (`ethical_violation` gates take the reflexion retry; the others redirect outright). Missing or invalid collapses to a generic `hard_gate_violation`. |
| `description` | string | Shown to the Conscience to anchor its evaluation. |
| `rubric` | object or list | Required in practice: see below. A dict carries `description` and `scoring_guide` (a list of `{score, descriptor}`); a bare list is treated as the scoring guide itself. |

**The rubric rule** (enforced at save time and again at compile time): a
value must carry a rubric the Conscience can actually score. A dict rubric
needs a non-empty `scoring_guide` or at least a `description`; a list
rubric must be non-empty. An empty shell (`{"scoring_guide": []}`) is
rejected, with a harder error for hard gates, because an unscoreable gate
would block every response the agent gives.

## 2. The policy

The business-unit governance object. Endpoints: `POST /api/policies`
(create), `PUT /api/policies/<policy_id>` (update; every edit is a new
version), `GET /api/policies`, version history and restore under
`/api/policies/<policy_id>/versions`. Editor role or above.

### 2.1 Payload

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Required. Duplicate names in the same scope are rejected (409). |
| `business_unit` | string | Display and attribution. |
| `context` | string | The human-facing description. Stored as its own field (`policy_config.context`); may be multi-line. |
| `worldview` | string | The Purpose statement. One prose blob, no required format; injected into every agent's context between the Charter preamble and the agent's own role. |
| `scope_statement` | string | The agent's lane. Compiled into an injected "Scope Compliance" hard gate (section 4); also shown to the model so it declines out-of-scope requests up front. |
| `values` | list | Section 1 shapes. **At least one is required.** These are the policy's scored standards and gates. |
| `will_rules` | object or list | The structured enforcement dict (2.2). A bare list is accepted as legacy free-text rules. |
| `alignment_threshold` | float 0..1 | The Will's blocking threshold: how well a response must score to ship. Persisted into `policy_config` and embedded as `structural_requirements.alignment_score_threshold`. Default 0.5. |
| `ethical_memory` | float 0.10..0.99 | The Spirit's EMA retention (beta): how much past behavior steadies the agent's baseline. Default 0.90. |
| `policy_id` | string | On update: which policy. Omit on create; the server derives a readable id. |

### 2.2 `will_rules` (the deterministic enforcement block)

```json
{
  "structural_requirements": {
    "require_disclaimer": false,
    "mandatory_disclaimer_substring": "",
    "banned_markdown_syntaxes": [],
    "alignment_score_threshold": 0.5
  },
  "early_prompt_blacklist": ["..."],
  "allowed_tools": ["web_search"],
  "rules": ["legacy free-text rules"],
  "allowed_knowledge_bases": ["kb-id"]
}
```

Everything in this block is enforced by deterministic code, never by a
model. Two semantics are load-bearing:

- **`allowed_tools`** holds connector names or function names; connector
  names are expanded to function names at compile time, and the Will then
  matches tool intents exactly. It can only narrow what the agent
  advertises, never grant. An empty list means deny all.
- **`allowed_knowledge_bases`**: **absent means the policy does not
  narrow; `[]` means deny all.** Send the key only when the author
  explicitly restricted knowledge. Coercing absent to `[]` would silently
  un-ground every agent under the policy. (`allowed_tools` deliberately
  has the opposite empty-list semantics; see the field notes in the
  Developer Guide, section 11.)

### 2.3 Save-time validation

Rejected with a 400 and a human-readable reason: a missing name, zero
values, any value failing the rubric rule, a scored value with weight 0,
`will_rules` that is neither list nor dict.

## 3. The agent

An agent is identity and role; its scored values come from governance
(section 4), never from itself. Three ways to define one:

### 3.1 Wizard / API agents (the normal path, no code)

`POST /api/agents` (create), `PUT /api/agents/<key>` (update). Payload:

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Required. Display name; the key is derived org-prefixed. |
| `description` | string | What the agent is for. Also feeds the wizard's drafting calls. |
| `worldview` | string | The role: system instructions ("You are..."). Says what the agent does and where its job ends; must not restate policy rules, the policy carries them. |
| `style` | string | Voice and formatting rules. |
| `scope_statement` | string | Agent-level scope. A policy's scope wins when both are present. |
| `policy_id` | string | The governing policy, or `"standalone"`. **Governance is required**: an agent with neither a policy nor an org Charter is rejected, because it would have no scored values and could not be governed. |
| `values` | list | Accepted for legacy shapes; under the two-tier model scored values are rebuilt from Charter and Policy at compile time, so agent-level scored values are discarded. Agent-level hard gates are preserved. |
| `will_rules` (or `rules`) | object or list | Agent-level enforcement additions, same shape as 2.2. Org and policy requirements can be added to, never dropped. |
| `tools` | list | Connector names the agent advertises. The compiled `allowed_tools` is the intersection: advertised ∩ policy ∩ org standards. |
| `rag_knowledge_base` | string | Knowledge base id. Authorization is checked at save time: it must be a corpus the caller can read, and policy knowledge authorization narrows it at compile time. |
| `rag_format_string` | string | Optional template for how retrieved chunks are presented. |
| `intellect_model`, `conscience_model`, `will_model` | string | Per-agent model overrides; provider must be configured and org-allowed. |
| `visibility` | string | `private` or org-visible. |
| `max_agent_turns` | int | Cap on sequential tool-call turns before a forced final answer. |
| `track_work_context` | bool | Default `true`. Whether the agent accumulates per-user work-context memory (see the Artifact Specification for what that memory looks like in records). |
| `avatar` | string | Display. |

### 3.2 Code-defined agents (built-ins and extensions)

A Python module exporting two attributes, discovered, never imported by
name:

```python
KEY = "night_auditor"     # registry key; may not shadow a built-in
AGENT = { ... }           # same field names as above, plus the extras below
```

Built-ins ship in `safi_app/core/agents/`; operator extensions load from
`SAFI_EXTENSIONS_DIR` (installing the file is the enablement). Extra
fields available only to code-defined agents:

| Field | Meaning |
|---|---|
| `internal_rephrase_directives` | Dict keyed by violation reason (`scope_violation`, `ethical_violation`): the agent-voiced instruction used to write the redirect for that class of block. |
| `example_prompts` | List of suggested prompts shown on the new-chat screen. |
| `history_turns` | Verbatim conversation window depth for this agent (int, or `"all"`); unset uses the deployment default. |
| `FALLBACK = True` | Module attribute (built-ins only): membership in the set enabled when `SAFI_BUILTIN_AGENTS` matches nothing. |

### 3.3 What an agent can never do

Grant itself tools its policy does not allow, carry scored values of its
own under the two-tier model, exempt itself from the scope gate, or call
anything: the Intellect proposes, the Will disposes, and both read only
the compiled profile.

## 4. Compilation semantics (what the TCB does with your data)

`get_profile()` compiles Charter + AI Standards + Policy + Agent into one
profile per turn. The rules a shape author must know:

- **Two-tier weights.** Scored values come from the org Charter and the
  Policy, split by the org's `governance_split` (default Charter 40% /
  Policy 60%). Within each tier, weights are ratios and are rescaled to
  the tier's share; the absolute numbers never matter, only proportions.
- **Hard gates bypass the split.** Gates from any tier are deduped by
  name, pinned to weight 0, and enforced individually.
- **Scope becomes a gate.** `scope_statement` compiles into an injected
  "Scope Compliance" hard gate with `gate_reason: scope_violation`.
- **`gate_reason` is stamped.** Missing reasons on hard gates are filled
  at compile time (legacy names recognized; everything else gets the
  generic reason). The Will routes from this data, never from names.
- **Connectors expand.** Tool connector names become exact function names
  in `allowed_tools`; the Will matches exactly and treats the compiled
  list as deny-all when empty.
- **Mission is context, not mandate.** The Charter's mission and value
  names are injected as descriptive context only. The model is never
  ordered to embody the values; the Conscience measures alignment after
  generation, which is what keeps the audit meaningful.

## 5. Stability

Same policy as the Artifact Specification: fields are added, never renamed
or repurposed; unknown fields are ignored rather than rejected; semantics
marked load-bearing above (absent-vs-empty, weight relativity, the rubric
rule) only change with a version bump and a note in the history below.

## Version history

- **1.0 (2026-08-17)** - Initial specification: the shared value/rubric
  shape, the policy payload and `will_rules` block, the three agent
  definition paths, and the compilation semantics.
