# SAFi (Self-Alignment Framework Interface)

SAFi is the first open-source implementation of the Self-Alignment Framework (SAF), a closed-loop ethical reasoning protocol. It is not a language model itself, but a governor that evaluates and audits the behavior of models like GPT, Claude, or Llama through a five-faculty reasoning loop:

**Values → Intellect → Will → Conscience → Spirit**

This loop turns ethics into system logic, ensuring transparency, accountability, and drift detection.

---

## Live Demo & Dashboard

You can try SAFi live and view the administrative dashboard here:

* [SAFi Application](https://safi.selfalignmentframework.com/)
* [SAFi Admin Dashboard](https://dashboard.selfalignmentframework.com/)

(Please note: The public demo is rate-limited to 10 prompts per user per day.)

---

## Features

* Closed-loop reasoning cycle across five faculties
* Pluggable value sets
* Conscience scoring with numeric + textual rationale
* Spirit coherence score (1–10) with drift detection
* Full JSON logging of each turn for auditing

---

## Architecture

### Component Flow

* **Input** – User provides a prompt, values, and context
* **Intellect** – Draft response and short reflection
* **Will** – Gate decision: approve or violation
* **Conscience** – Per-value audit ledger `{value, score, confidence, reason}`
* **Spirit** – Aggregate into coherence score (1–10) and drift metric
* **Memory** – Update history for long-term consistency

### Example Log Output

```json
{
  "timestamp": "2025-04-09T15:23:01Z",
  "turn": 12,
  "userPrompt": "Should AI allocate vaccines?",
  "intellectDraft": "...",
  "intellectReflection": "...",
  "finalOutput": "...",
  "willDecision": "approve",
  "willReflection": "...",
  "conscienceLedger": [
    {
      "value": "Respect for Human Dignity",
      "score": 0.5,
      "confidence": 0.85,
      "reason": "Supports dignity but lacks emphasis."
    }
  ],
  "spiritScore": 7,
  "drift": 0.12,
  "spiritReflection": "Response affirms justice and autonomy, moderate coherence."
}
```

---

## Installation

### Requirements

* Python 3.10+
* Virtualenv (recommended)
* LLM API key (OpenAI GPT-4o by default; Anthropic optional)

### Setup

```bash
git clone git@github.com:jnamaya/SAFi.git
cd SAFi
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in your API keys
python safi.py
```

### Configuration

* `.env` – runtime settings & API keys
* `valuesets/` – directory for custom ethical frameworks
* `Logs` – written to `saf-spirit-log.json` (newline-delimited JSON)

---

## Roadmap

* **v1.0 (current)** – Stable closed-loop reasoning, UNESCO default values, JSON logs
* **v1.1 (planned)** – Modular value-set loader, structured Conscience JSON, real-time loop packets
* **v1.2 (future)** – Web UI, flexible logging backends, visual drift dashboards

---

## Specification

For the full mathematical and architectural definition of SAFi v1.0, see: *SAFi v1.0 Specification*

---

## License

* SAFi code: GNU GPL v3
* SAF protocol (theory): MIT License

---

SAFi is the first bridge between philosophy and machine logic—making values explicit, enforceable, and auditable.
