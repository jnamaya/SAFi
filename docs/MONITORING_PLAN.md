# SAFi Post-Market Monitoring Plan

**Version 1.0 — July 2026.** This plan describes how a SAFi deployment
continuously monitors the behaviour of governed AI agents in production, how
deviations are surfaced, and how humans review and act on them. It supports
EU AI Act Article 72 (post-market monitoring) and FINRA 3110/3120
supervisory-review expectations. It describes shipped functionality, not
intentions.

## 1. What is monitored

Every governed turn is evaluated and scored before it is committed, and the
scores are stored with the record. Monitoring watches three signals:

| Signal | Definition | Default threshold | When checked |
|---|---|---|---|
| **Alignment (rolling)** | Mean Alignment score (0–10) of the last N approved responses for an agent. Redirected responses are scored on a separate redirect-quality rubric and are excluded, so graceful refusals cannot mask degradation. | Alert when the rolling mean falls below **6 / 10** over a **20-turn** window | On every approved turn |
| **Consistency (per turn)** | How closely one response's value expression matches the agent's own historical pattern, as a percentage (100% = fully in character). | Alert when a turn falls below **60%** | On every scored turn |
| **Review-queue backlog** | Age of the oldest response sampled for human review that no reviewer has yet dispositioned. | Alert when older than **14 days** | On queue reads and a daily timer |

All thresholds and the window size are configurable per organization. Every
threshold change is written to the organization's append-only compliance
evidence log, so the monitoring configuration in force at any past date is
reconstructable.

## 2. How alerts are delivered

1. **Journal (always).** Every alert is written to an append-only alert log
   with its observed value, threshold, and delivery outcome. Alerts cannot be
   edited or deleted.
2. **In-app (always).** Alerts render in the organization's Review tab
   regardless of any external configuration.
3. **Webhook (optional).** Organizations may register an HTTPS endpoint.
   Alerts are POSTed as JSON with an `X-SAFi-Signature` header
   (HMAC-SHA256 over the exact request body) so the receiver can verify
   origin and integrity; delivery uses a 10-second timeout with one retry,
   and the outcome (`ok` / `failed`) is recorded in the alert journal.
   A webhook receiver can fan out to email, Slack, Teams, or paging systems.

Duplicate alerts for the same organization, alert type, and agent are
suppressed for 24 hours so a sustained condition produces one actionable
signal per day, not a flood.

## 3. Human review procedure

Monitoring is paired with a supervisory review queue:

- **Sampling.** Each organization configures deterministic sampling rules:
  a random percentage of all turns (verifiable after the fact — the sampling
  function is a published hash rule, so an examiner can recompute exactly
  which turns were due), plus rule triggers: every hard-gate block, every
  gateway violation, low-Alignment turns, and Consistency drops.
- **Review.** Reviewers (administrator or auditor roles only — content
  authors cannot supervise their own agents) see the full governance record
  for each sampled turn: the user prompt, the delivered response, the
  value-by-value evaluation, the enforcement decision, and the models
  involved. They **approve** or **override** each item; an override requires
  a written reason.
- **Evidence.** Every disposition is appended to the same tamper-evident,
  hash-chained audit trail as the record under review, attributed to the
  authenticated reviewer. Review is post-hoc supervision: an override does
  not retract a delivered response — it is the firm's documented
  determination about it.
- **Cadence.** The backlog alert (§1) enforces a review cadence floor: if
  sampled items sit unreviewed past the organization's limit, the
  organization is alerted daily until the queue is cleared.

## 4. Coverage reporting

A coverage report is available on demand and exportable as CSV (exports are
themselves logged for chain of custody). It states, for any date range: total
governed turns, how many were sampled and why, dispositions, median review
latency, and per-reviewer counts — the evidence that the supervisory
procedure operates, not merely exists.

## 5. Escalation

SAFi surfaces and records; the operating firm owns escalation. The expected
path: an alert or an overridden review item is assessed by the firm's
compliance owner; systemic findings (a degrading agent, a policy gap) lead to
policy or agent changes — which are themselves versioned and take effect
under the same governance pipeline; suspected security events are recorded in
the incident registry, which tracks the firm's notification obligations.

## 6. Responsibilities

| Role | Responsibility |
|---|---|
| Organization administrator | Owns monitoring thresholds, sampling rules, and the webhook endpoint; changes are evidence-logged |
| Reviewers (admin / auditor) | Disposition sampled turns; provide written reasons for overrides |
| Operating firm | Escalation, staffing the review function, and adequacy of sampling rates for its regulatory context |
| SAFi platform | Evaluates every turn, enforces sampling atomically with each record, journals alerts, preserves all evidence tamper-evidently |
