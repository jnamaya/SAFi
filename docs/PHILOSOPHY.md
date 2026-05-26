# SAFi: Philosophy as Architecture

## Why Thomistic Philosophy?

SAFi's cognitive architecture is derived from the **Thomistic faculties of the soul** as described by Thomas Aquinas. This is not decoration -- it is a structural borrowing. Just as airplanes were inspired by birds but don't use feathers, SAFi is inspired by the *structure* of the human mind but is a concrete software implementation.

The key insight: classical philosophy had already solved the problem of **how a unified agent can maintain consistent values while acting in a dynamic world**. Aquinas described a set of distinct, specialized faculties -- each with a separate role, each checking the others. That structure maps directly to the challenge of building a governed AI agent.

## The Mapping

| Thomistic Faculty | Classical Role | SAFi Module | Software Role |
| :--- | :--- | :--- | :--- |
| **Synderesis** | The innate knowledge of first moral principles. Cannot be corrupted by circumstance. | `synderesis.py` | The immutable constitution compiler. Defines governance policies, value weights, and scope boundaries before any prompt is processed. Read-only at runtime. |
| **Intellect** | The faculty that apprehends truth and drafts judgments. | `intellect.py` | The generative engine. Drafts responses and proposes tool calls. Operates entirely within an Air Gap -- it can only produce *intents*, never execute them. |
| **Will** | The faculty of rational appetite. Executes only what reason has approved. | `will.py` | The blind, deterministic gatekeeper. Pure Python with zero LLM calls. Approves or vetoes the Intellect's proposals based on structural checks and the Conscience's mathematical ledger. |
| **Conscience** | The faculty that applies general moral principles to particular acts, rendering a verdict. | `conscience.py` | The analytical auditor. A secondary LLM call that scores each draft against the agent's value rubrics, generating a precise compliance ledger (−1.0 to +1.0 per value dimension). |
| **Habitus / Spirit** | The stable disposition formed by repeated acts -- the character of the agent over time. | `spirit.py` | The long-term integrator. Tracks alignment as a rolling mathematical vector using exponential moving averages, detecting behavioral drift and generating coaching for future turns. |

## Why This Solves a Real Engineering Problem

Monolithic LLMs face an inherent tension: the same model that generates a response must also evaluate whether that response is compliant. This is like asking a witness to be their own judge. The model's "helpfulness" training routinely overrides its safety instructions on adversarial prompts -- SAFi's benchmarks document this: unguarded baselines fail adversarial prompts at a 30-point higher rate.

The Thomistic separation is the answer. By splitting **generation** (Intellect) from **evaluation** (Conscience) from **execution** (Will), SAFi eliminates the conflict. The Will faculty enforces structural invariants using pure deterministic Python -- no LLM, no semantic vulnerability, no way to social-engineer it.

The result is a governance layer that is **model-independent**: the same deterministic gates fire regardless of whether the underlying LLM is GPT-5, Claude, or an open-source fine-tune. You can swap the model without rewriting the governance.

## Further Reading

- [Mathematical Specification](MATHEMATICAL_SPECIFICATION.md) -- formal type system, Spirit EMA formulas, Will gate logic, Phase Zero entropy heuristics
- [SAFi Self-Alignment Framework](https://selfalignmentframework.com) -- the philosophical foundation in full
