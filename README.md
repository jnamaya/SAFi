# SAFi (Self-Alignment Framework Interface)

**SAFi** (Self-Alignment Framework Interface) is a modular **ethical reasoning engine** built on the [Self-Alignment Framework](https://www.selfalignmentframework.com) (SAF). It is not itself a language model. Instead, it governs, evaluates, and audits the behavior of AI models (like GPT or Claude) through a **closed-loop moral architecture**.

At its core, SAFi encodes a five-faculty reasoning loop:

**Values → Intellect → Will → Conscience → Spirit**

This structure enforces ethical alignment as a *system function*, not a post-hoc filter—addressing AI’s structural flaws of opacity, drift, and moral indifference.

## 🔍 What SAFi Does

SAFi enables machines to:
- Reflect on prompts using a declared **value set**
- Gate outputs via **Will** (approve/block)
- Audit responses against each individual value (**Conscience**)
- Assign an overall coherence score (**Spirit**) on a 1–10 scale
- Log the **entire reasoning trail** for transparency & auditing

## 🌀 SAFi Reasoning Loop

Each prompt cycles through the following stages:

1. **Input** – User provides a prompt, values, and context.
2. **Intellect** – Generates a draft response + reasoning reflection.
3. **Will** – Approves or blocks based on ethical criteria.
4. **Conscience** – Audits response, scoring each value (affirm/omit/violate).
5. **Spirit** – Aggregates into a **1–10 coherence score** and drift measure.
6. **Memory** – Updates history for long-term consistency.

**Closed Loop:** Intellect → Will → (user sees response) → Conscience → Spirit → Memory → (feeds next turn).

## 📜 SAFi v1.0 Specification

SAFi v1.0 (“Aquinas”) is the **first stable release** of the ethical reasoning engine.

- Full implementation of the SAF closed-loop protocol
- Logs every decision to `saf-spirit-log.json`
- Value-agnostic (UNESCO Ethics is default, but pluggable)
- Conscience scoring uses `{−1, 0, +½, +1}` mapped to human-readable labels
- Spirit produces a 1–10 score with drift detection

👉 [Read the full technical specification](./SAFi-Spec-v1.0.md)


## ⚙️ Installation

### Requirements
- Linux-based server (e.g. Ubuntu)
- Node.js + npm
- OpenAI API key (Anthropic optional)
- (Optional) Domain for deployment

### Setup (with Hugging Face Chat UI)

```bash
git clone https://github.com/huggingface/chat-ui
cd chat-ui
npm install
```

Replace the OpenAI endpoint handler with SAFi’s logic:

```
/chat-ui/src/lib/server/endpoints/openai/endpointOai.ts
```

Add your environment configuration in `.env.local` (see template in repo).

## 🧩 Swapping Value Sets

SAFi is **value-agnostic**. You can align it with:
- Religious frameworks (Catholic, Buddhist, etc.)
- Institutional charters (UNESCO, corporate ethics)
- Personal constitutions

To change:
1. Open `endpointOai.ts`
2. Replace the `defaultValueSet` with your own values

Example:
```ts
export const defaultValueSet = {
  name: "Catholic",
  definition: `
1. Respect for human dignity
2. Justice and fairness
3. Charity and compassion
4. Prudence in judgment
5. Pursuit of the common good
`
};
```

## 🛣️ Roadmap

### ✅ Current (v1.0)
- Stable closed-loop implementation
- Value-agnostic design
- File logging (`saf-spirit-log.json`)

### 🚧 Next (v1.1)
- Modular value set loader (`/valuesets` directory)
- Conscience structured JSON output
- Real-time loop summary packet
- Flexible logging (file / console / webhook)


## 📖 License

- **SAFi engine (code):** GPL v3
- **SAF protocol (theory):** MIT License


> SAFi is the first implementation of SAF, turning philosophy into machine logic. By making values explicit, enforceable, and auditable, it brings transparency and rigor to AI alignment.
