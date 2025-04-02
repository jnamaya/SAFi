SAFI

SAFI (Self-Alignment Framework Interface) is a modular, open-source AI reasoning framework designed to ensure ethical integrity through structured, self-correcting decision-making. SAFI is based on the Self-Alignment Framework (SAF), a closed-loop ethical architecture composed of five components: Values → Intellect → Will → Conscience → Spirit.

This pilot implementation uses a Catholic value set for demonstration purposes. SAFI is value-agnostic and designed to support any well-defined ethical system.

🚀 What SAFI Does

SAFI helps AI systems think and act ethically by:

Reflecting on prompts using a selected value set

Blocking ethically misaligned outputs

Evaluating decisions against each value

Scoring overall moral coherence

Logging the full process for transparency

🔁 SAFI Reasoning Loop

User Input – You ask a question or give a prompt.

Intellect – The system reasons through the value set and generates a response + reflection.

Will – Checks if the response violates any values. If so, it's blocked.

Conscience – Audits the response, evaluating how well it affirms or violates each value.

Spirit – Assigns a 1–5 alignment score based on moral coherence.

Logging – All steps are saved to saf-spirit-log.json.


