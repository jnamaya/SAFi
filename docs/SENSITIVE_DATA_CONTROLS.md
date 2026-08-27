# Sensitive Data Controls

SAFi can detect and block sensitive personal and financial identifiers in both
directions: in a message before it is sent to a model, and in a response before
it is delivered. Detection is deterministic code with no model involved. Every
check is off by default and is enabled per identifier by an organization admin.

This document states exactly what is detected, what is not, and where the limits
are. Read the [Limitations](#limitations) section before relying on it.

---

## 1. What is detected

Four checks ship. Each pairs a format with a validation step, and three of the
four carry a real checksum.

### Payment card numbers

Thirteen to nineteen digits satisfying the Luhn algorithm. Separators are
ignored.

| | |
| :--- | :--- |
| Detected | `4111111111111111`, `4111 1111 1111 1111`, `4111-1111-1111-1111`, `5500005555555559`, `378282246310005` |
| Not detected | `4111111111111112` (one digit changed, fails Luhn), `1234567890123456` (correct length, fails Luhn) |

### IBAN

Two letters, two check digits, then the account identifier, validated by the
ISO 13616 mod-97 rule: the rearranged value must equal 1 modulo 97.

| | |
| :--- | :--- |
| Detected | `GB82WEST12345698765432` |
| Not detected | `GB82WEST12345698765433` |

### Bank routing numbers (ABA)

Nine digits validated by the 3-7-1 weighted checksum.

| | |
| :--- | :--- |
| Detected | `021000021` |
| Not detected | `021000022` |

### US social security numbers

Formatted only, plus the Social Security Administration's allocation rules.

| | |
| :--- | :--- |
| Detected | `123-45-6789` |
| Not detected | `123456789` (unformatted, see [Limitations](#limitations)), `000-45-6789`, `666-45-6789`, `900-45-6789` (areas never issued), `123-00-6789` (group `00` never issued), `123-45-0000` (serial `0000` never issued) |

---

## 2. How detection works

A regular expression finds the shape. A checksum, or a set of allocation rules,
confirms it. Both steps are plain Python in `safi_app/core/pii_validators.py`.
No model is called at any point in the detection path.

This is a deliberate placement rather than an optimization. Whether a number
satisfies Luhn is arithmetic, and arithmetic has one correct answer that anyone
holding the audit record can recompute. A language model asked the same question
returns an answer that is usually right, occasionally not, carries no stable
threshold, and cannot be independently verified afterwards. For a control whose
value is being checkable, that is the wrong tier.

The detectors live outside the faculties, alongside `threat_intel.py`, so adding
one never requires editing a faculty.

---

## 3. Where the checks run

**Inbound, before the model is called.** Phase Zero evaluates the prompt. A
message containing a detected identifier is refused and the value is never sent
to the model that would reason about it. The user receives an explanation naming
the policy and inviting them to resend without the identifier.

**Outbound, before the response is delivered.** The Will evaluates the draft
against the same checks. An agent with tool access can read a document, find an
account number in it, and reproduce that number in its answer. Nobody typed it
and the model produced it, so an inbound-only control would miss it entirely.

Both are deterministic checks in the same tier as the rest of SAFi's
enforcement. See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) for the execution loop.

---

## 4. What reaches the audit record

When a turn is blocked, SAFi writes a governance record describing the decision.
That record is retained for years under the organization's retention policy.

The detected value is removed from it. It is replaced in full rather than masked
to the last few digits, because a partial identifier is still an identifier.
What remains is which check fired:

```json
"userPrompt":  "when was our last commit: [REDACTED:ssn]",
"willReason":  "pii_detected",
"will_stage":  "phase_zero"
```

The record shows that the turn was refused, at which stage, by which check, and
what the user was told. It does not contain the identifier.

---

## 5. Configuration

### Enabling checks

**Settings → Organization → AI Standards → Block sensitive data.**

Every check is off until an admin turns it on. A deployment that never opens the
setting sees no change in behaviour on any turn. Each check states its precision
next to its checkbox, including which one is least precise.

### There is no custom pattern field

The menu is fixed, and this is a design decision rather than a gap. A
caller-supplied expression would execute on every turn inside the deterministic
path, where there is no timeout, so a pathological pattern becomes an
availability problem. A subtly malformed one matches nothing while appearing to
be enforced, which is worse: the control looks active and is not.

Adding a detector means writing and testing it in the repository.

### Precedence

What an organization enables is a **floor**. A policy or an individual agent may
add further checks. Neither can remove one the organization enabled, because the
two sets are combined and combining prohibitions can only tighten them. This is
structural, not enforced by hiding controls in the interface.

### Scope

The checks follow the **acting user's organization**, not the agent. They
therefore apply on every agent that user reaches, including the agents SAFi
ships with. A member of your organization pasting an account number is the same
exposure whichever agent is on screen.

Users with no organization, such as public or demo sessions, inherit no
organizational floor.

---

## 6. Limitations

**Unformatted social security numbers are not detected.** A bare nine-digit run
is not matched, deliberately. Unlike card numbers and IBANs an SSN carries no
checksum, so nothing distinguishes `123456789` from an order number, a part
number, or nine digits inside a longer string. Matching it would refuse ordinary
business messages with no explanation a user could act on. The formatted case is
precise, the unformatted case is not, so it is left alone.

**The routing-number check is the loosest of the four.** Its checksum is a single
weighted mod-10 test over nine digits, so roughly one in ten random nine-digit
strings passes by chance. It is accurate on real routing numbers and will
produce occasional false positives on unrelated nine-digit values.

**Only recognized formats are detected.** An identifier written in words, split
across lines, obfuscated, or embedded in an encoding is not matched. These are
pattern checks, not comprehension.

**Only these four identifier types are covered.** Passport numbers, national IDs
outside the US, medical record numbers, driver's licence numbers and tax
identifiers are not detected today.

**The value existed before the check ran.** It arrived over the network and is
present in the stored message row and in any web-server logs the deployment
keeps. These controls remove it from the model's input and from the governance
record. They do not remove it from everywhere.

**Detection is not classification.** SAFi identifies a number matching a known
format and checksum. It does not determine whether that number belongs to a real
person, or whether the context is legitimate.

---

## 7. Verifying it

The behaviour is directly observable and worth confirming rather than taking on
trust.

1. Enable one check in **AI Standards**.
2. Send a message containing an identifier of that type.
3. The turn is refused before the model is called, and the response explains why.
4. Open the governance record for that turn in the **Audit Hub**. The decision,
   the stage and the reason are present. The value is not.

The detectors, their checksums and their tests are in the repository:

| | |
| :--- | :--- |
| Detectors | `safi_app/core/pii_validators.py` |
| Detector tests | `tests/test_pii_validators.py` |
| Gate and precedence tests | `tests/test_pii_gate.py` |
| Settings surface tests | `tests/test_pii_settings_api.py` |
