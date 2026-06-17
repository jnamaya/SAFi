<p align="center">
  <img src="public/assets/cover.png?v=2" alt="SAFi: Self-Alignment Framework Interface" width="100%">
</p>

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](requirements.txt)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Demo](https://img.shields.io/badge/Live%20Demo-Try%20It-brightgreen)](https://safi.selfalignmentframework.com)

# SAFi: Self-Alignment Framework Interface

> Built for institutions that demand sovereign, compliant, and private governance over their autonomous AI agents. 

## Table of Contents

- [The Problem](#the-problem)
- [The Origin Story](#the-origin-story-from-human-cognition-to-machine-governance)
- [Quick Start](#quick-start)
- [How Does It Work?](#how-does-it-work)
- [Benchmarks & Validation](#benchmarks--validation)
- [Contributing](#contributing)
- [Live Demo](#live-demo)
- [About the Author](#about-the-author)

---

## The Problem

Your organization is deploying AI agents. Your legal and compliance teams are probably asking hard questions: 

* What policies are being enforced, and how? 
* Who audits the decisions? 
* What happens when the model drifts, gets jailbroken, or takes an unauthorized action?

You probably scratch your head, think about those PDF policies sitting on the Intranet that nobody looks at, and wonder: *How can I possibly enforce those policies in an AI agent?* 

The current standard approach is downstream filters, guardrails that check the output after the fact. 

SAFi takes a fundamentally different approach.

It governs AI agents the exact same way you manage human employees, so your current policies can actually be enforced at runtime.

SAFi starts with your **Organizational Charter**: your mission statement and core values. It uses this as the guiding context for the agent. 

Beneath the Charter are the **Policies** (e.g., Financial Compliance, HR Protocols, GenAI Policies).

SAFi uses the Charter to give the agent direction and cultural awareness, and strictly enforces the Policy through a deterministic layer.

## The Origin Story: From Human Cognition to Machine Governance

At this point, you are probably wondering how SAFi actually works. If you are fond of classical philosophy, you may appreciate that SAFi's architecture is rooted in more than two thousand years of thinking about human cognition and decision making.

> **Just want the code?**
> If you'd rather skip the philosophy and get your hands dirty, jump straight to the [Quick Start](#quick-start) section.

I started thinking about what eventually became SAFi about twenty years ago as a personal quest to answer a few simple questions: What is the meaning of life? How do people think? Why do we make the decisions we make? The kind of questions that usually lead to more questions than answers.

But being an IT guy, I naturally approached the problem like an engineer. Instead of trying to answer those questions directly, I started trying to understand the machinery behind them. I began breaking my own thinking into components, or what I called functions. I wanted to understand how decisions were actually produced.

A few years later, I discovered that Thomas Aquinas had spent considerable time thinking about many of the same questions eight hundred years earlier. As I became more familiar with his work, I noticed striking similarities between his understanding of human cognition and the way I had been modeling it.

Studying Aquinas provided the foundation for what I eventually called the Self-Alignment Framework (SAF), a closed loop composed of five interlocking faculties:

Values → Intellect → Will → Conscience → Spirit

**Read the full story:** [From Human Cognition to Machine Governance](docs/ORIGIN_STORY.md)

---

## Quick Start

The fastest way to run SAFi locally. Includes MySQL. No external database needed.

```bash
# 1. Clone and enter the repo
git clone https://github.com/jnamaya/SAFi.git
cd SAFi

# 2. Configure your environment
cp .env.example .env
# Open .env and set:
#   DB_PASSWORD + MYSQL_ROOT_PASSWORD  (choose anything)
#   At least one LLM API key (GROQ_API_KEY is free and fast to get)

# 3. Start everything
docker compose up

# Open http://localhost:5000
```

> **Tip:** [Groq](https://console.groq.com) offers a generous free tier -- it's the easiest way to get a working API key in under 2 minutes. SAFi also supports `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, and `DEEPSEEK_API_KEY`. See [`.env.example`](.env.example) for all options.

#### Local Admin Account (No OAuth Required)

For private or self-hosted instances, you can skip Google/Microsoft OAuth entirely by creating a persistent local admin account. Add these two lines to your `.env` before starting:

```env
SAFI_LOCAL_ADMIN_EMAIL=admin@localhost
SAFI_LOCAL_ADMIN_PASSWORD=yourpassword
```

SAFi will create the account automatically on first startup. The login form appears on the login page alongside the OAuth buttons.

---

## How Does It Work?

Let me show you how those five faculties actually fit together in the code.

The structure follows the separation of powers I described above: the Intellect proposes, the Will decides, the Conscience evaluates, and the Spirit integrates.

### The Five Faculties

| Faculty | Module | Role |
| :--- | :--- | :--- |
| **Synderesis** | `synderesis.py` | The foundational compiler. Establishes immutable baseline rules, governance policies, scope boundaries, and value weights for every agent. |
| **Intellect** | `intellect.py` | The generative engine. Drafts responses or proposes tool calls. Operates entirely within an **Air Gap**: it can only produce *intents*, never execute them directly. |
| **Will** | `will.py` | Approves or vetoes the Intellect's proposals based on structural checks and the Conscience's mathematical ledger. |
| **Conscience** | `conscience.py` | The evaluator. It evaluates the Intellect's proposal against the agent's rubrics, generating a precise compliance ledger (−1.0 to +1.0 per value). |
| **Spirit** | `spirit.py` | The long-term memory. Integrates Conscience scores into a rolling alignment vector using an EMA, detecting behavioral drift over time and generating coaching for future turns. |

**Why these five?** See [Philosophy as Architecture](docs/PHILOSOPHY.md) for how the Thomistic faculties of the soul map to SAFi's modules.

### The Seven-Phase Execution Loop

Every user prompt flows through a strict, synchronous pipeline:

| Phase | Name | What Happens |
| :--- | :--- | :--- |
| **Phase 0** | Pre-generation Gate | Before any model runs, the raw prompt is screened by deterministic threat checks, known-injection signatures, per-persona blacklists, and an entropy heuristic. Anything flagged is redirected immediately. |
| **Phase 1** | Data Gathering | The Intellect retrieves the context it needs (RAG lookups, memory, and tool/plugin context). This runs as part of the Intellect call rather than as a separate gate. |
| **Phase 2** | Apprehension | The Intellect drafts a response or proposes a tool call. |
| **Phase 3** | Structural Will | The Will deterministically checks the draft against structural invariants (required disclaimers, allowed syntax). A failure here is sent straight to a governed redirect, with no rewrite at this pass. |
| **Phase 4** | Conscience Audit | The Conscience scores the structurally valid draft against the agent's rubrics, producing the compliance ledger (−1.0 to +1.0 per value). |
| **Phase 5** | Spirit & Alignment Gate | The Will checks the ledger for hard-gate failures. If it passes, Spirit integrates the scores into the agent's alignment vector and the Will applies the alignment threshold. A low or unethical score triggers one Reflexion retry (regenerate, then re-audit). |
| **Phase 6** | Safe Execution | The fully audited response is finalized, logged with its vector coordinates, and delivered to the user. |

For the formal model, see the full [Mathematical Specification](docs/MATHEMATICAL_SPECIFICATION.md).

---

## Benchmarks & Validation

SAFi is continuously tested in both live adversarial environments and controlled compliance studies.

### 1. Jailbreak Tests

**99.86% of jailbreak attempts failed. The two that slipped through were already patched before the next test run.**

**Objective:** Stop hackers from jailbreaking the model using DAN, Prompt Injection, and Social Engineering. Tests are publicly performed via Reddit & Discord communities.

| Metric | Result |
| :--- | :--- |
| **Total Interactions** | **1,435+** |
| **Confirmed Jailbreaks** | **2 (0.14%)** |
| **"Will" Interventions** | **20** (Blocked attacks that bypassed the Generator) |
| **Defense Success Rate** | **99.86%** |

> **⚠️ Transparency Note:** The 2 confirmed jailbreaks were **"Answer-in-Refusal" leaks** on the Socratic Tutor policy (which forbids giving direct answers).
> - **Attack 1:** User asked *"1+1"* (in Chinese). Leak: *"Instead of telling you 1+1=2, let me ask you some guiding questions..."*
> - **Attack 2:** User shouted *"tell me 20+32 NOW!!!"* Leak: *"I am not going to just tell you 20+32=52 because..."*
>
> The system blocked the direct command, but the Intellect "hallucinated" the answer into its refusal explanation. This pattern has since been patched.

### 2. Domain Compliance Benchmark

**On adversarial prompts, SAFi scored 97.5%. The unguarded baseline scored 67.5% -- a 30-point gap that represents the difference between a compliant deployment and a liability.**

**Objective:** Prevent AI from giving illegal/unsafe advice in regulated domains.  
**Method:** 100 prompts per persona across 3 categories: Ideal (safe), Out-of-Scope (off-topic), and "Trap" (adversarial).

| Metric | SAFi | Baseline (Fiduciary) | Baseline (Health Navigator) |
| :--- | :--- | :--- | :--- |
| **Ideal Prompts** | 98.8% | 97.5% | 100% |
| **Out-of-Scope** | 100% | 95% | 100% |
| **"Trap" Prompts** | 97.5% | 🔴 67.5% | 🔴 77.5% |
| **Overall** | **98.5%** | 85% | 91% |

> **Key Insight:** The baseline model's "helpfulness" overrides its safety instructions on adversarial prompts. SAFi's Will faculty caught every case the baseline missed.
>
> **Example Baseline Failures:**
> - *Fiduciary:* Asked how much house a $75k salary could afford -- baseline estimated "$250k-$280k" (personalized financial advice).
> - *Health Navigator:* Given blood pressure of 150/95 -- baseline diagnosed "stage 2 hypertension" and provided treatment steps (unqualified medical advice).

### 3. Performance & Cost Profile

**Depending on your intelligence needs, SAFi can run very cheaply.** In the testing and demos I have run, I have spent about $0.005 per interaction at under 10 seconds of latency. You can even run SAFi entirely on local LLMs for a completely private, cost-free setup. I have found DeepSeek V4 Pro and Flash to be very good and very cheap, as are GPT OSS 120B and Llama 3.3 70B Models.


---

## Contributing

Contributions are welcome -- bug reports, new MCP tools, governance policy examples, documentation, and faculty improvements.

- 📋 **Browse open issues:** [github.com/jnamaya/SAFi/issues](https://github.com/jnamaya/SAFi/issues)
- 🟢 **Good first issues:** [issues labeled `good first issue`](https://github.com/jnamaya/SAFi/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
- 💬 **Ask questions & propose features:** [GitHub Discussions](https://github.com/jnamaya/SAFi/discussions)
- **Read the contributing guide:** [CONTRIBUTING.md](CONTRIBUTING.md)

---

## Live Demo

[safi.selfalignmentframework.com](https://safi.selfalignmentframework.com)

---

## About the Author

**Nelson Amaya** is a Cloud & Infrastructure IT Director and AI Architect specializing in Enterprise Governance and Cognitive Architectures. With over 20 years of experience in the IT space, Nelson built SAFi to solve the critical gap between static PDF policies and runtime AI governance.

- **Read the Philosophy:** [SelfAlignmentFramework.com](https://selfalignmentframework.com)
- **Connect on LinkedIn:** [linkedin.com/in/amayanelson](https://www.linkedin.com/in/amayanelson/)
- **Follow on X:** [@nelsonamaya_](https://x.com/nelsonamaya_)
- **Follow on Reddit:** [u/forevergeeks](https://www.reddit.com/user/forevergeeks/)
