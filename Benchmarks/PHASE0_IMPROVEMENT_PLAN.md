# Phase 0 Hardening — Design Doc / Implementation Plan

**Status:** Draft for review · **Author:** (drafted with Claude Code) · **Date:** 2026-06-03
**Scope:** `safi_app/core/faculties/phase_zero.py`, `safi_app/core/threat_intel.py`, `Benchmarks/Scripts/jailbreak_test.py`
**Non-goals:** Changes to Will/Conscience/Spirit, the redirect UX, or persona definitions (beyond optional per-persona config).

---

## 1. Background

Phase 0 is SAFi's pre-generation injection gate (`PhaseZeroGate`). It runs in the
orchestrator at `orchestrator.py:443-457`, **before the Intellect is invoked**, and
short-circuits to `trigger_persona_redirect()` on a hit. It is fully deterministic
(zero LLM calls).

Current logic (`evaluate_prompt`), in order:
1. **Global signature scan** — naive `pattern in prompt.lower()` substring match over
   `INJECTION_SIGNATURES` (~200 patterns across 11 categories).
2. **Persona blacklist scan** — same substring match over `will_rules.early_prompt_blacklist`.
3. **Embedded-instruction heuristic** — Shannon entropy of first 300 chars ≥ 4.5, then
   look for an instruction marker in the remainder.

### Why it's "primitive"
- **Naive substring matching** → both false positives ("how do I defend against a *jailbreak*?"
  is blocked) and trivial evasion ("j a i l b r e a k", "ignore​previous" with a zero-width char).
- **No input normalization** — no Unicode folding, homoglyph folding, whitespace/zero-width
  stripping, or leetspeak handling before matching.
- **Reactive signature treadmill** — the multilingual list and many comments ("seen in live
  logs") show the list grows one attack at a time; paraphrases and novel framings bypass it.
- **Encoding gap** — detects the *phrase* "convert from base64" but never decodes the payload,
  so an encoded attack without a telltale phrase passes untouched.
- **Narrow entropy heuristic** — single fixed threshold, samples only the first 300 chars,
  requires a marker from a fixed 12-item list.
- **Binary block** — every match is a hard block → refusal. A refusal-on-substring product
  cannot afford the false-positive rate this produces.

### Guiding principle
Phase 0 is the **first layer of defense-in-depth**, not the only one. Intellect, Will (structural +
hard-gate), Conscience (audit), and Spirit sit behind it. So Phase 0 should:
- **Block the clear-cut, cheap-to-detect attacks with high precision**, and
- **Defer ambiguous cases to the model layers** rather than hard-blocking on a weak signal.

The goal is **precision + resistance to evasion**, not a blocklist that tries to catch everything.

---

## 2. What already exists (build on, don't rebuild)

`Benchmarks/Scripts/jailbreak_test.py` is a 100-case regression suite:
- 80 attack prompts across 9 categories + 20 legitimate controls.
- `--mode phase0` runs the gate directly (no server) by loading `threat_intel.py` via importlib
  and **reimplementing `evaluate_prompt` inline** (`_phase0_evaluate`).
- `--mode http` runs the full pipeline against a live server.
- Reports per-category coverage, attack-block rate, control-handling rate, and failures.

**Implication:** this is our measurement instrument. Two consequences:
1. We measure baseline + every change against it.
2. The inline reimplementation (`_phase0_evaluate`) **must be kept in sync** with the real gate,
   or replaced by importing the real gate. See §6.

---

## 3. Target architecture

```
                 ┌─────────────────────────────────────────────┐
raw user_prompt →│ 0. NORMALIZE                                 │
                 │    NFKC · strip zero-width · collapse ws ·   │
                 │    homoglyph fold · leetspeak fold           │→ normalized_text
                 └─────────────────────────────────────────────┘
                                    │ (original preserved for logging)
                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │ 1. DECODE-AND-RESCAN                         │
                 │    detect b64/hex/rot13 blobs → decode →     │
                 │    feed decoded text back through matching   │
                 └─────────────────────────────────────────────┘
                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │ 2. SIGNATURE MATCH (word-boundary regex)     │
                 │    each signature tagged HARD | SOFT         │
                 │    + persona blacklist (HARD)                │
                 └─────────────────────────────────────────────┘
                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │ 3. HEURISTICS (entropy, sliding window)→SOFT │
                 └─────────────────────────────────────────────┘
                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │ 4. SCORING / DECISION                        │
                 │    any HARD hit            → BLOCK           │
                 │    ≥2 SOFT or SOFT+context → BLOCK           │
                 │    1 SOFT                  → (opt) ESCALATE  │
                 │    else                    → PASS            │
                 └─────────────────────────────────────────────┘
                                    ▼
                 (opt) 5. SEMANTIC TIER — embeddings or fast LLM
                          only for ESCALATE; returns block/pass
```

The public contract stays **`evaluate_prompt(prompt, persona_blacklist) -> (is_safe, reason)`**
so the orchestrator is unchanged. `reason` keeps the `injection:<category>` / `scope_violation`
shape so `trigger_persona_redirect`'s `scope_like` classification still works.

---

## 4. Implementation phases

### Phase A — Measurement baseline (no behavior change)
**Goal:** numbers before we touch logic.
- Run `jailbreak_test.py --mode phase0` against current code; save the JSON to
  `Benchmarks/Results/` as the baseline.
- **Expand the corpus** with the evasion cases the current gate provably fails:
  spaced-out keywords, zero-width-injected keywords, homoglyph keywords, leetspeak,
  base64 payloads *without* a trigger phrase, and ~20 more benign-but-tricky controls
  (security questions: "how do I defend against prompt injection?", "explain what a
  jailbreak attack is"; foreign-language benign prompts).
- Record baseline: attack-block %, control-pass %, and a new **evasion-block %**.

**Deliverable:** baseline numbers + expanded corpus. No production code touched.

---

### Phase B — Normalization (highest ROI, deterministic)
**New module:** `safi_app/core/faculties/_normalize.py` (or `text_normalize.py`).
```python
def normalize_for_matching(text: str) -> str:
    # 1. Unicode NFKC (fold fullwidth, ligatures, etc.)
    # 2. strip zero-width / bidi control chars (​–‏, ‪–‮, ﻿)
    # 3. homoglyph fold (Cyrillic/Greek lookalikes → ASCII) via a small static map
    # 4. collapse internal whitespace runs (incl. between letters → optional de-spacing pass)
    # 5. leetspeak fold (4→a 3→e 0→o 1→i 5→s 7→t @→a $→s) for a *second* match pass
    # 6. casefold (Unicode-aware, replaces .lower())
```
- Matching runs against `normalize_for_matching(prompt)`. The **original** prompt is kept for
  logging and for the redirect (we never feed normalized text downstream).
- De-spacing and leetspeak are aggressive; run them as a **secondary** match pass so we can
  measure their false-positive cost separately and disable if needed.

**Files:** new `_normalize.py`; `phase_zero.py` calls it. `threat_intel.py` unchanged.
**Risk:** over-normalization false positives → mitigated by keeping de-space/leet as a
separate, individually-toggleable pass and measuring against the control set.

---

### Phase C — Matching engine + severity tiers
**`threat_intel.py` schema change.** Today: `dict[str, list[str]]`. Proposed: keep the category
keys, but allow each pattern to carry a severity. Backward-compatible shape:
```python
INJECTION_SIGNATURES: dict[str, dict] = {
  "jailbreak_archetypes": {
      "severity": "HARD",                 # category default
      "patterns": ["dan mode", "do anything now", ...],
      "soft_patterns": ["jailbreak", "god mode"],   # ambiguous in isolation
  },
  ...
}
```
- **Word-boundary regex**: compile patterns to `\b…\b` regexes at import (cache compiled set).
  Multi-word patterns become `\bword1\W+word2\b`. This is the single biggest false-positive fix.
- **Allowlist guard**: a small set of defensive framings ("defend against", "protect from",
  "what is a", "how do attackers", "explain the") that demote a SOFT hit when they co-occur.
- **Decision rule** (§3 step 4): any HARD → block; ≥2 SOFT (or 1 SOFT + entropy signal) → block;
  1 SOFT alone → pass (or escalate if Phase E is enabled).

**Migration note:** patterns currently relied on for hard blocks (DAN, system_override, XML tags,
authority claims) stay **HARD** so we don't regress the 80 attack cases. Only genuinely-ambiguous
single words ("jailbreak", "god mode", "decision tree", governance-probing terms) move to SOFT.

**Files:** `threat_intel.py` (schema), `phase_zero.py` (compiled-regex matcher + scoring).

---

### Phase D — Decode-and-rescan
- Detect candidate encoded blobs in the normalized text:
  - base64: `[A-Za-z0-9+/]{20,}={0,2}` that decodes to valid UTF-8 text;
  - hex: long even-length `[0-9a-f]` runs;
  - rot13: apply when an `encoded_payload` rot13 marker is present.
- Decode → run the **signature matcher** over the decoded text → if it hits, block with
  `injection:encoded_payload`.
- Guardrails: cap decode size, ignore blobs that decode to binary/non-text, only rescan
  (don't recurse infinitely).

**Files:** `phase_zero.py` (helper), reuses Phase C matcher. Closes the "phrase-without-decode" gap.

---

### Phase E — Heuristic hardening
- Entropy: **sliding window** across the whole prompt (not just first 300 chars); flag the
  max-entropy window. Make `ENTROPY_THRESHOLD`, window size, and min-length **per-persona
  overridable** via `will_rules` (fall back to module defaults).
- Treat "high-entropy window present" as a **SOFT** signal feeding the §3-step-4 scorer rather
  than requiring a marker from the fixed list.

**Files:** `threat_intel.py` (defaults stay; add optional persona override read), `phase_zero.py`.

---

### Phase F — Semantic escalation tier (optional, do last, behind a flag)
For novel/paraphrased attacks that no signature catches. **Only invoked for ESCALATE
(1-SOFT) cases**, so >95% of traffic keeps the fast deterministic path.
- **Option F1 — embedding classifier (preferred first cut):** embed prompt, cosine-compare to a
  curated bank of known-attack embeddings; threshold → block. No LLM, ~ms, cheap.
  (SAFi already has embedding infra for RAG/faiss — reuse it.)
- **Option F2 — fast LLM classifier (Haiku):** binary injection/benign + confidence. Higher
  recall on truly novel attacks, but adds latency + cost; cache by prompt hash.
- Config flag `phase0.semantic_tier = off | embeddings | llm`, default `off` until proven on the
  eval harness.

**Decision deferred** to after Phases A–E numbers are in. Documented here for completeness.

---

## 5. Decision rule summary (final state)

| Condition | Outcome |
|---|---|
| Any HARD signature / persona-blacklist hit | **BLOCK** (`injection:<cat>` / `scope_violation`) |
| Decoded payload matches any signature | **BLOCK** (`injection:encoded_payload`) |
| ≥2 SOFT hits, or 1 SOFT + entropy signal | **BLOCK** (`injection:<cat>`) |
| Exactly 1 SOFT hit | **PASS** (or **ESCALATE** if Phase F enabled) |
| Defensive-framing allowlist demotes the only SOFT hit | **PASS** |
| Nothing | **PASS** |

PASS results still face Will + Conscience downstream — defense-in-depth intact.

---

## 6. Test & validation plan

- **Keep `jailbreak_test.py` as the gate of record.** Replace the inline `_phase0_evaluate`
  reimplementation with a direct import of the real `PhaseZeroGate` (via importlib, same as it
  loads `threat_intel.py`) so the test can never drift from production. *(If the faiss import
  chain blocks this, keep the inline copy but add a unit test asserting the two agree.)*
- Acceptance gates for each phase:
  - **No regression** on the existing 80 attack cases (attack-block % must not drop).
  - **No regression** on the 20 legitimate controls (control-pass % must not drop).
  - **Improvement** on the new evasion corpus (Phase A) — this is the whole point.
  - New target control set ("defend against jailbreak", etc.) must **PASS** (proves precision gain).
- Add a fast `pytest` wrapper so the suite runs in CI / pre-restart.

---

## 7. Rollout & ops

- Each phase is independently shippable and independently revertible.
- After each backend change: `systemctl restart safi` (per CLAUDE.md). No CSS/Tailwind impact.
- **Logging:** keep the existing `PhaseZeroGate` warnings; add the matched severity + whether a
  decode/normalization pass caused the hit, so live-log triage stays possible.
- **Telemetry → signature curation:** log every decision (block/pass + reason + matched pattern)
  to a queryable store so future signatures are added from data, not anecdote. (Stretch.)

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Over-normalization (de-space/leet) blocks legit text | Separate toggleable pass; measure FP cost on controls |
| Severity reclassification regresses attack blocks | Keep all currently-relied-on patterns HARD; eval-gate every change |
| Decode-and-rescan performance / decode bombs | Size caps, text-only, single non-recursive rescan |
| Test harness drift | Import real gate in `jailbreak_test.py` (§6) |
| Semantic tier latency/cost | Off by default; only on 1-SOFT escalate; cache by hash |

---

## 9. Proposed sequence

1. **A** — baseline + expand corpus (measure)
2. **B** — normalization
3. **C** — word-boundary regex + severity tiers + allowlist
4. **D** — decode-and-rescan
5. **E** — entropy hardening + per-persona config
6. **F** — semantic tier (decide after A–E numbers)

Phases B + C together are expected to deliver the bulk of the value (evasion resistance **and**
fewer false positives) with zero added latency and no LLM dependency.

---

## 10. Open questions for review

1. **Scope of this session** — implement A–C now, or land the full A–E and evaluate F separately?
2. **Severity reclassification** — comfortable moving "jailbreak", "god mode", and the
   governance-probing terms to SOFT? (They're the main false-positive sources.)
3. **Semantic tier** — if we pursue F, prefer F1 (embeddings, reuse faiss) over F2 (Haiku)?
4. **Config location** — per-persona Phase 0 overrides in `will_rules`, or a dedicated
   `phase0` block in the persona schema?
5. **Telemetry** — is there an existing decision-log sink to reuse, or is that out of scope?
