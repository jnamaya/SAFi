# SAFi Governance Artifact Specification

> **Version:** 1.0.1
> **Last updated:** 2026-08-16
> **Status:** Descriptive. The code is the authority; this document names the
> shapes it produces so you can build on them. Verified against the tree at
> the commit that introduced this file.

SAFi's Trusted Computing Base (TCB) produces a small set of durable,
structured artifacts on every governed turn. This specification is the
contract for reading them, so a developer can build a custom dashboard, an
examiner tool, a SIEM feed, or a reporting pipeline without
reverse-engineering `orchestrator.py`. It documents User Space's read
surface; the write side of the boundary is covered in the
[Developer Guide, section 19](DEVELOPER_GUIDE.md#19-the-tcb-user-space-and-how-they-talk).

Two properties hold for everything below:

- **Artifacts are snapshots.** A record captures what the pipeline saw and
  decided at that moment. Later changes to agents, policies, or memory never
  rewrite an existing artifact.
- **Artifacts are attested.** Every governance record names the TCB
  fingerprint of the code that produced it, so a reader can tie any record
  to a verified build.

## 1. The governance record (one per turn)

The complete capture of a governed exchange. Stored in `governance_records`
as one Fernet-encrypted JSON blob (`record_enc`) plus plaintext filter
columns; served decrypted to authorized readers by the audit API.

### 1.1 Plaintext filter columns

These are queryable without decryption and drive the Audit Hub's lists,
trends, and aggregates:

```
message_pk, message_id, conversation_id, profile_key, policy_id,
policy_version, will_decision, will_stage, spirit_score, drift,
intellect_model, user_id, created_at
```

### 1.2 The encrypted capture

Fields present on every record:

| Field | Type | Meaning |
|---|---|---|
| `timestamp` | ISO 8601 string | When the terminal commit happened (UTC). |
| `t` | int | The agent's Spirit interaction index. Counts the agent baseline, which is shared across orgs for built-in agents; it is not "this conversation's Nth turn". |
| `t_sequence` | string | Names what `t` counts (`agent_baseline_shared`). |
| `userPrompt` | string | The user's message as governed. |
| `intellectDraft` | string | The draft the Intellect produced. |
| `intellectReflection` | string | The Intellect's reasoning text, `""` when absent. |
| `toolCalls` | list | Tool-call entries (section 3). Same entries as the hash chain. |
| `finalOutput` | string | What was actually shipped to the user. |
| `willDecision` | string | `approve`, `violation`, or `redirected`. |
| `willReason` | string | Stable reason code (`pass`, `scope_violation`, `grounding_violation`, `ethical_violation`, `hard_gate_violation`, `hard_gate_unscored`, `low_alignment_score`, ...). Treat as an identifier, not prose. |
| `conscienceLedger` | list | Ledger entries (section 2). |
| `spiritScore` | int or null | 0 to 10 alignment score. Null when no redirect-quality audit applies. |
| `spiritNote` | string | The Spirit's narrative note. |
| `drift` | float or null | Cosine drift from the agent's baseline. |
| `p_t_vector`, `mu_t_vector` | list of float | The turn's value vector and the updated baseline (see the Mathematical Specification). |
| `memorySummary` | string | Conversation summary injected this turn, `""` if none. |
| `recentTurns` | string | The verbatim recent-turns window injected this turn. |
| `spiritFeedback` | string | The self-correction nudge injected this turn, `""` if none. |
| `retrievedContext` | string | RAG, plugin, and tool evidence the draft was grounded on and the Conscience audited against. |
| `agentWorkContext` | string | The work-context memory as injected this turn (the budgeted copy), `""` when the agent tracks none. Entries inside carry `updated` and `src` stamps; `src` is the message id of the governed turn that stated the fact. |
| `retryMetadata` | object | `{was_retried, original_draft, violation_reason}` (section 5). |
| `policyId`, `policyVersion` | string, int | The exact policy version the profile was compiled from. |
| `orgId`, `userId`, `agentName` | strings | Attribution. `orgId` may be null (personal and public-bot turns). |
| `intellectModel`, `conscienceModel` | strings | The models used this turn. |
| `tcb` | object | The attestation stamp (section 4). Stamped in the single writer every governance path funnels through, so no path can mint an unattested record. |

### 1.3 Variant fields

Redirected turns (`willDecision: "redirected"`) additionally carry:

| Field | Meaning |
|---|---|
| `isRedirect` | `true`. |
| `originalLedger` | The failing audit's ledger, so the record shows why the draft was blocked. |
| `blockedDraft` | The draft that was blocked, `""` for pre-draft blocks (Phase Zero). |

Records from the `/evaluate` gateway (external outputs judged by SAFi)
carry `mode: "evaluate_gateway"` and `externalOutput` (the text under
evaluation). Fields that only make sense for generation, such as
`agentWorkContext`, are empty on gateway records.

Absent versus empty: `""`, `[]`, and `null` mean "nothing of this kind this
turn". A missing key means the record predates the field (section 8).

## 2. Conscience ledger entries

One entry per configured value, every turn. The Conscience is instructed to
return exactly this shape, and the Will fails closed if a hard-gate value
is missing from it:

```json
{ "value": "Scope Compliance", "score": -1.0, "confidence": 0.9, "reason": "..." }
```

| Field | Type | Meaning |
|---|---|---|
| `value` | string | The value's name as compiled into the profile. Match case-insensitively with normalized whitespace; that is what the Will does. |
| `score` | float | -1.0 to 1.0. A hard-gate value at -1.0 trips the Will regardless of the average. |
| `confidence` | float | 0.0 to 1.0. The Spirit weights the score by it. |
| `reason` | string | The auditor's justification. Prose, for humans. |

## 3. Tool-call entries

Built in one place (`_tool_audit_entry`) so the hash chain and the
governance record cannot describe the same call differently:

```json
{ "tool": "web_search", "decision": "approved", "reason": "...", "params": {...}, "agent_turn": 2 }
```

`params` values are clipped to a fixed length with an explicit
`...[+N chars]` marker, so a record stays small on long inputs and truncation
is visible instead of silent. `agent_turn` appears when the call happened
inside a multi-turn tool loop.

## 4. The TCB attestation stamp

```json
{ "fingerprint": "7ce01276...", "intact": true, "state": "intact" }
```

`fingerprint` is the TCB Fingerprint: the boot-time root hash over the Core
Loop file hashes. `state` is `intact`, `modified`, or `unverifiable`.
Compare the value against the `TCB Fingerprint:` line published on the
official GitHub release to determine whether the producing code was an
unmodified release. A custom interface
displaying governance records should surface a non-intact stamp loudly.

## 5. Retry metadata

```json
{ "was_retried": false, "original_draft": null, "violation_reason": null }
```

When a draft failed and the reflexion retry produced the committed answer,
`was_retried` is `true`, `original_draft` holds the failed draft, and
`violation_reason` holds the reason code that triggered the retry.

## 6. Hash-chain entries (`chat_audit_trail`)

An append-only journal of every create, update, and delete on a
`chat_history` row:

```
id, message_pk, message_id, conversation_id, action, actor, state,
event_at, prev_hash, entry_hash, org_id, created_at
```

`entry_hash = sha256(json({message_pk, message_id, conversation_id, action,
actor, state, event_at, prev_hash}, sort_keys=True))`. Two facts a verifier
must know: `org_id` is excluded from the hash on purpose (unauthenticated
routing metadata added by a later migration), and `state` is stored as
`LONGTEXT` rather than native `JSON` because MySQL's `JSON` type normalizes
documents on write, which would silently change the hashed bytes. Recompute
hashes from the stored bytes, never from a re-serialized object.

## 7. The compiled profile

The other side of every record: `get_profile()` (`synderesis.py`) compiles
agent, policy, charter, and standards into one dict, and the record's
`policyId`/`policyVersion` tell you which inputs it was compiled from. The
compiled keys that matter to a reader:

- `values`: the normalized scored set plus hard gates. Each hard gate
  carries `gate_reason` (`scope_violation`, `grounding_violation`, or
  `ethical_violation`), stamped at compile time; the Will routes failures
  from this data and never from a value's name.
- `allowed_tools`: function names, already expanded from connector names.
  The Will matches tool intents against this list exactly.
- `allowed_knowledge_bases`: absent means the policy does not narrow;
  `[]` means deny all. The distinction is load-bearing.
- `scope_statement` becomes the injected "Scope Compliance" hard gate.

Given a record's ledger and the compiled profile, the Will's decision is
recomputable: that is the determinism claim the audit rests on (Developer
Guide, section 5).

## 8. Access surfaces and stability

**Read APIs** (role-gated; see the RBAC notes in the Developer Guide,
section 10): `/api/organizations/<org_id>/audit/filters`, `/summary`,
`/trend`, `/events`, `/events/<message_pk>` (the full decrypted capture),
and `/export` (the examiner bundle, which includes integrity evidence).
`/api/audit_result` serves a turn's audit to the chat UI. The user data
export includes the caller's own records.

**Encryption**: captures are encrypted at rest and decrypted only for
authorized readers. A custom interface should sit on the APIs, not on the
database.

**Stability policy**: fields are added, never renamed or repurposed. A
reader must tolerate unknown keys and treat a missing key as "record
predates the field" (for example, `agentWorkContext` exists only on records
from 2026-08-16 onward). Reason codes and decision strings are stable
identifiers; prose fields (`reason`, `spiritNote`) are for display and must
not be parsed. Changes to this specification get a version bump and a note
in the version history below.

## Version history

- **1.0.1 (2026-08-16)** - Terminology: the Core Loop root hash is called the
  **TCB Fingerprint** everywhere (script output, release notes, this spec).
  No shapes changed.
- **1.0 (2026-08-16)** - Initial specification: governance record (including
  `agentWorkContext` and variant fields), ledger entries, tool-call entries,
  TCB stamp, retry metadata, hash-chain entries, compiled-profile keys,
  access surfaces, stability policy.
