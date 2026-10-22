# Audit Hub Improvement Proposal

Status: **proposal only** — no code changed.
Scope: the native Audit Hub tab and its API, i.e.
`public/js/ui/settings/ui-settings-dashboard.js` (UI),
`safi_app/api/audit_api.py` (endpoints), and the `governance_*`
functions in `safi_app/persistence/database.py` (queries), plus the
`governance_records` / `chat_audit_trail` tables.

## 1. What we have today

### 1.1 Architecture (this part is strong — keep it)

- **Observe stays observe.** The hub has no write actions; dispositions live in
  the Review tab. The single write is the server-side `audit_export` custody log
  to `org_compliance_log` (`audit_api.py:224-241`). This is the right boundary and
  should be preserved.
- **Encryption discipline.** KPI / trend / explorer reads only **plaintext
  filter/aggregate columns** (`spirit_score`, `drift`, `will_decision`,
  `created_at`…). Decryption happens **only** in drill-down, prompt search, and
  export (`audit_api.py:10-12`, `database.py:5337`, `5368`, `5460`). The caps
  (`GOVERNANCE_SEARCH_CAP`, `GOVERNANCE_EXPORT_CAP`) bound how many rows get
  decrypted in one request.
- **Integrity evidence, honestly scoped.** Exports carry per-record
  `chat_audit_trail` chain heads, and the payload's `integrity` block explicitly
  states the chain is *integrity evidence, not proof of non-tampering* because it
  is unkeyed and written by the same process that writes the records
  (`audit_api.py:200-216`). That self-limiting honesty is a real asset.
- **N/A, never a default.** `alignmentLabel` / `consistencyLabel` and the SQL
  `NULL` handling render missing data as `N/A` (`ui-settings-dashboard.js:30-37`,
  `database.py:5238-5242`). Good.

### 1.2 Current surfaces

- **KPI row** (`ui-settings-dashboard.js:266-303`): overall gauge, avg
  alignment, avg consistency, interventions, total audits.
- **Trend** (`340-540`): SVG line chart, per-agent split (up to 8 series),
  moving average (3/7/14/30), three views (consistency %, drift, deviation).
- **Log Explorer** (`544-630`): paginated table (50/page), prompt search, four
  decision filters (flagged/approved/redirected/violation), row click → detail.
- **Drill-down** (`690+`): draft, decision, policy audit ledger, alignment,
  output, tool-call timeline, review-queue status, chain verification.

### 1.3 Controls / filters today

Mode (agent/policy), entity, **single** user, range (7d/30d/all), decision
filter, free-text prompt search. That is the full filter surface.

## 2. Gaps and improvement proposals

Ordered by impact-to-effort. Each item is independent and shippable on its own.

### 2.1 Add a "flagged" first-class view to KPI + trend (HIGH impact, LOW effort)
Today `flagged` exists only as an Explorer filter (`VALID_FILTERS`,
`audit_api.py:26`); the KPI row and trend always cover the whole window
(`audit_api.py:93`, `115` explicitly `pop("flt")`). A compliance reader's first
question is *"how many turns need attention, and is it getting worse?"*
- Extend `governance_summary` to also return the flagged subset's alignment/
  drift and a flagged-rate.
- Add a "Flagged trend" view (flagged count / flagged rate per bucket) so the
  trend card answers "is the problem growing?" directly.

### 2.2 Multi-select filters (HIGH, MEDIUM)
Current filters are single-valued: one user, one entity, one range preset.
Real triage is usually *"agent A and agent B, user X, last 14 days."*
- Generalize `profile`, `policy_id`, `user_id` to accept comma-separated /
  repeated params in `_common_filters` and `_governance_where`.
- UI: turn the single `<select>`s into multi-select (checkbox dropdown) for
  user, and allow "compare N agents" in the trend (already supported up to 8
  series — this just makes it reachable).

### 2.3 Custom date range (MEDIUM, MEDIUM)
Range is hard-coded to 7d/30d/all (`ui-settings-dashboard.js:135-139`, `210`).
The API already accepts arbitrary `from`/`to` (`audit_api.py:59-62`), so this is
purely a UI gap. Add two date inputs that feed the existing params.

### 2.4 Column sort + server-side sort in Explorer (MEDIUM, MEDIUM)
`list_governance_events` only supports `ORDER BY created_at DESC, id DESC`
(`database.py:5350`). Readers want "worst alignment first" / "highest drift
first" to triage. Add a `sort` param (whitelisted: `created_at`,
`spirit_score`, `drift`) and clickable column headers.

### 2.5 Per-value audit breakdown in the drill-down (HIGH for understanding, MEDIUM)
The drill-down shows the aggregate `spirit_score` and the ledger, but the
headline number is opaque. `profile_values` are already fetched
(`ui-settings-dashboard.js:723-727`). Render a compact per-value bar
(name, weight, score, importance) so a reviewer sees *why* a turn scored as it
did without parsing the ledger JSON.

### 2.6 Trend ↔ Explorer cross-filtering (MEDIUM, MEDIUM)
Clicking a day/point on the trend chart should deep-link the Explorer to that
bucket (set `from`/`to` to the bucket). The data model already supports it; this
is a UX wiring change and makes the hub feel like one instrument rather than
three.

### 2.7 Integrity: make the chain *keyed* (HIGH value, HIGHER effort — separate workstream)
This is the one architectural improvement rather than a UI tweak. The
`chat_audit_trail` chain is **unkeyed** (`entry_hash` does not incorporate a
secret; `database.py:727-762`), so a DB writer can rewrite and re-chain history.
The export doc is honest about this, but the stronger property is a keyed
Merkle/Hashlink construction where each `entry_hash` includes the previous hash
**and** a server-held key, and periodic **anchoring** of chain heads into an
external, append-only store (the `org_compliance_log` digest, a notary, or a
signed snapshot). This turns "integrity evidence" into "tamper-evident
evidence." Recommend scoping this as its own project; do not fold it into the
hub UI.

### 2.8 Performance: pre-aggregation for long windows (LOW priority until volume grows)
`governance_summary` / `governance_trend` run `AVG`/`GROUP BY` over
`governance_records` on every load (`database.py:5220`, `5265`). Fine at current
scale. If "All time" + large orgs get slow, add a nightly rollup table
(`governance_daily_rollup`: org, profile, day, counts, sums) and read the
rollup for day-bucketed aggregates. Do not build this speculatively.

### 2.9 Small UX/robustness items (LOW)
- **Keyboard accessibility** in the Explorer: rows are `cursor-pointer` but not
  focusable/`role="row"`-navigable (`ui-settings-dashboard.js:564-577`).
- **Loading / empty state consistency**: the "no records" message references the
  legacy dashboard sunset (`598`); keep it in sync with the actual sunset plan.
- **`will_stage` exposure**: `will_stage` is selected (`database.py:5320`) but not
  surfaced in the Explorer table — showing gate stage (draft vs tool_intent)
  would make the decision badge legible.

### 2.10 Search improvements (the weakest of the three cards)

The search box is the only place decryption is legitimately involved, and it is
currently the least capable surface. Today any `q` forces
`search_governance_events` (`audit_api.py:143-150`, `database.py:5368-5418`) to:
run the plaintext `WHERE` + `COUNT` → `window`; refuse with 413 if
`window > GOVERNANCE_SEARCH_CAP` (5,000, `database.py:5123`); otherwise select
**all** matching rows **including `record_enc`**, decrypt each, and do an
in-Python `needle in prompt.lower()` substring match; return matches newest-first
up to `limit`. In search mode the UI drops pagination and the footer reports the
in-window count, not the match count (`ui-settings-dashboard.js:555`, `608`).

Ranked problems:

1. **Decrypt-everything to substring-match.** Within the 5k window it decrypts
   every matching row just to test one `in` on the plaintext prompt — O(window)
   decryption per debounced request. It also means **only the prompt is
   searchable** (`userPrompt`, `database.py:5396-5397`); no model, policy,
   decision, or output field.
2. **Case/substring only, no field scoping, no highlighting.** Bare `contains`,
   no whole-word, no "search in prompt vs. output vs. tool calls." The 160-char
   preview has **no match highlight**, forcing a drill-down click to see *why* it
   matched.
3. **Search and pagination are mutually exclusive.** The cap forces
   newest-first up to `limit` with no offset (`audit_api.py:146-147`), so you
   cannot page through matches. Near the cap you see at most `limit` (≤200)
   matches with no way to reach older ones.
4. **`window` is the pre-decrypt count, not the match count.** "across M records in
   the window" presents the in-window row count as if it were the match count
   (2,000 in-window rows may yield 3 matches).
5. **No cheap path for plaintext fields you *can* search without decryption.**
   `intellect_model`, `policy_key`, `user_id`, `will_decision` are plaintext
   (`_GOV_EVENT_COLUMNS`, `database.py:5318-5322`); a `q` targeting those should be
   a plain `LIKE` with zero decryption, but today any `q` forces the decrypt path.
6. **No query hygiene.** `q` is trimmed but has no length cap, no escaping
   feedback, no visible "searching…" state; a 10-char term fires a decrypt scan of
   up to 5k rows on every debounced keystroke.

Proposals (each independent; all reuse `_common_filters` / `_governance_where`
and the existing cap — no new decryption *paths*, no writes, no schema):

- **2.10a Split `q` into a cheap path and a decrypt path (HIGH, MEDIUM).** Route
  by what the query could match: if it targets a **plaintext column** (model,
  agent/profile key, user id/name, decision), run SQL `LIKE %q%` on those columns
  — no decryption, no cap, fully paginatable. Only fall through to the decrypt
  substring scan when the reader explicitly targets **prompt text** (a "prompt"
  field selector, a `q:` prefix, or a "Search prompt content" toggle). This
  preserves the decrypt-on-demand discipline while making the common
  "find all turns by model X" case free and paginatable.
- **2.10b Paginate search results (MEDIUM, MEDIUM).** Replace "newest-first up to
  limit, no offset" with pagination **on the match set**. After a search resolves
  the matching `message_pk`s (bounded by the cap), page over
  `WHERE message_pk IN (...)` with a stable ordering — the cap still bounds the
  one-time decrypt, but pages reuse the already-identified match set without
  re-decrypting. At minimum, make the footer count **matches**, not in-window
  rows (fixes problem 4).
- **2.10c Multi-field search + highlight (MEDIUM, MEDIUM).** Add field scoping
  (prompt / model / agent / user / decision via checkboxes or an `in:` prefix).
  In the row preview, highlight the matched span (`<mark>`) and show a longer
  preview (e.g. 240 chars centered on the match, not just the first 160) so the
  reader sees *why* it matched without clicking through.
- **2.10d Search UX/robustness (LOW).** Keep the 400 ms debounce but add a visible
  searching state and cancel-in-flight (a `fetch` token) so a slow decrypt scan
  doesn't race a newer keystroke. Cap `q` length server-side (e.g. 200 chars) with
  a clear 400. When `window` is near `GOVERNANCE_SEARCH_CAP`, show a hint
  ("narrow the date range to search") *before* the 413 so it reads as guidance,
  not an error.

Explicitly **not** proposed for 2.10:

- **No full-text index over decrypted content.** Persisting plaintext in an index
  breaks the "decrypt only on demand" discipline and the cap's purpose. Keep
  search on-demand and bounded.
- **No regex / advanced query language.** Substring + field scoping covers the
  real triage needs; a regex engine over decrypted content is over-engineered and
  a footgun.

## 3. Recommended sequencing

1. **Quick wins (one PR):** 2.3 custom dates, 2.4 sort, 2.9 stage column.
2. **Core value (one PR):** 2.1 flagged KPI/trend, 2.5 per-value breakdown.
3. **Filter power (one PR):** 2.2 multi-select + 2.6 cross-filtering.
4. **Search (one PR):** 2.10a cheap/decrypt split first (highest value), then 2.10b
   match-set pagination + footer match count, then 2.10c field scoping/highlight,
   then 2.10d UX/robustness. The 2.10d `q`-length cap is trivial and can ship
   earlier with the quick wins.
5. **Separate, larger effort:** 2.7 keyed/anchored chain integrity.
6. **Only when needed:** 2.8 rollups.

## 4. Explicitly NOT proposed (and why)

- **No writes in the hub.** Adding dispositions here would break the clean
  observe/review split that is the tab's defining property.
- **No new decryption paths.** All proposals above reuse the existing
  plaintext-column reads for KPI/trend/explorer; only the already-decrypting
  drill-down/search/export gain features.
- **No schema changes** for 2.1–2.6 (all are query/param/UI work). Only 2.7 and
  2.8 touch schema.

## 5. Verification notes for whoever implements

- Every new read endpoint must stay on the **plaintext-column** path and pass
  through `_common_filters` (so the 30-day default window and role checks apply).
- New sort/filter params must be **whitelisted** before touching the `WHERE`
  clause (`_governance_where`) — no raw interpolation.
- `flagged` KPI math must mirror `_GOV_FLAGGED_SQL` so the KPI count and the
  Explorer filter count always agree.
