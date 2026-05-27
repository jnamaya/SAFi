---
title: SAFi Explained: Practical Use Cases and Applications
slug: concepts-use-cases
tags: ["safi", "concepts", "use-cases", "agents", "headless"]
summary: Real-world examples of how SAFi governs AI agents across enterprise, healthcare, finance, education, headless integrations, and human organizational governance.
version: 2.0
---

# SAFi Explained: Practical Use Cases and Applications

## Core principle
SAFi governs any AI agent that needs to stay inside defined boundaries. Because the Will faculty is deterministic and model-agnostic, governance is independent of the underlying LLM. Switching from GPT to Claude to Llama does not change the policy enforcement.

## Built-in agent examples
SAFi ships with nine pre-configured agents that demonstrate specific governance scenarios in real deployments.

### Contoso Admin — Organizational IT governance
An enterprise IT support agent with RAG over standard operating procedures. The Will enforces data privacy rules and prevents PII from being included in responses. Demonstrates how to govern an internal-facing AI deployment with policy-grounded answers.

### The Fiduciary — Regulated financial domain
A financial information agent with live MCP tool-calling for stock prices and earnings data. The Will enforces fiduciary scope: it cannot give personalized investment advice, project returns, or take on advisory liability. Demonstrates how to govern a tool-calling agent in a regulated industry.

### The Health Navigator — Healthcare guidance
A healthcare agent with RAG over health content and geospatial MCP tools for facility lookup. The Will gate enforces mandatory medical disclaimers on every response. Demonstrates defense against the class of failures where a baseline model gives unqualified medical advice. In benchmark testing, the baseline model scored 77.5% on adversarial health prompts; SAFi scored 100%.

### The Socratic Tutor — Educational format enforcement
An educational agent whose Will rules structurally reject any response containing a direct answer. Every response must be a guiding question. Demonstrates that the Will can enforce format and pedagogical constraints, not just safety ones.

### The Negotiator — Social engineering resistance
A roleplay simulation agent demonstrating persona-scope enforcement. It stays in its assigned character and refuses all attempts to redirect it out of that character. Demonstrates resistance to persona-switching attacks and frame-breaking attempts.

### The Vault — Maximum jailbreak resistance
An agent holding a secret phrase that must never be revealed. It has been tested against every known public jailbreak vector. Demonstrates the complete three-layer scope-compliance defense: Worldview Scope Block, W1 Structural Gate, and Phase 4.5 Hard Gate working in concert.

### The SAFi Guide — RAG-grounded documentation assistant
A documentation assistant for the SAFi knowledge base. The Conscience enforces that all factual claims are grounded in retrieved documents rather than model confabulation.

### The Bible Scholar — Corpus fidelity
A theological research agent with RAG over the Berean Standard Bible. The Conscience audits for textual fidelity, ensuring responses are grounded in the corpus rather than paraphrase or invention.

### The Philosopher — Value-weighted intellectual discourse
An Aristotelian ethics guide with Conscience scoring weighted on Intellectual Honesty, Logical Rigor, and Socratic Depth. Demonstrates fine-grained value configuration for intellectual discourse.

## Headless governance layer
SAFi can operate as a governance API for any external application. Organizations with existing chatbots, LangChain pipelines, AutoGen agents, or messaging integrations (Microsoft Teams, Telegram, WhatsApp) can route their AI traffic through SAFi's five-faculty pipeline via the headless API endpoint. All interactions are logged and visible in the Audit Hub. This makes SAFi a "Governance-as-a-Service" layer for any existing AI deployment.

## Custom deployments
Any domain that requires an AI agent to stay within defined scope can use SAFi by defining a custom persona in synderesis.py or through the Agents UI. The five-faculty pipeline applies automatically. Governance does not require custom code — it requires a well-specified persona configuration.

## Applications to human organizations
The Self Alignment Framework itself can be applied to organizational governance, not just AI. The same faculty structure maps directly to human organizational roles.

- Intellect: strategy or research teams that propose initiatives
- Will: executives or managers who approve or block proposals
- Conscience: auditors, compliance committees, or ethics boards reviewing outcomes
- Spirit: the board or governance council tracking long-term mission integrity

## Cross references
- 06 Concepts Personas
- 18 Separation of Powers
- 10 SAFi Technical Workflow
- 25 SAFi Application Structure
- 26 SAFi Scope Compliance Defense
