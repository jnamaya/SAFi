---
title: SAFi Explained: Personas (Ethical Profiles)
slug: concepts-personas
tags: ["safi", "concepts", "personas"]
summary: Operational personas and role-based configurations used by SAFi.
version: 1.0
---

# SAFi Explained: Personas (Ethical Profiles)

### **Core Concept: The Purpose of Personas**

**Q: What problem do Personas solve in SAFi?**

A: Personas solve the problem of an AI lacking a clear direction or "compass." Values can be complex, and simply giving an AI rules is not enough. A Persona provides a guiding purpose (a _teleology_) by defining a complete and coherent ethical character for the AI to embody, ensuring its actions are consistent and aligned.

**Q: What is a Persona in SAFi?**

A: A Persona in SAFi is the practical application of an **Ethical Profile**. This profile is a structured, machine-readable blueprint for the AI's character, defined in a configuration file (like values.py). It makes abstract values operational.

### **The Four Components of a Persona Profile**

**Q: What are the four key parts of a Persona or Ethical Profile?**

A: Each profile contains four key components that shape the AI's behavior:

1. **Worldview:** The AI's foundational perspective and the core principles from which it reasons.
2. **Style:** The specific voice, tone, and character for communication.
3. **Rules (will_rules):** Non-negotiable, hard-coded boundaries that must never be violated.
4. **Values (values list):** A weighted list of nuanced ethical principles that guide judgment and auditing.

### **How Personas Interact with SAFi Faculties**

**Q: How does a Persona profile direct the SAFi faculties?**

A: Each part of the profile directly instructs a specific faculty in the SAFi loop:

- The **Intellect** uses the Worldview and Style to generate its initial draft response.
- The **Will** acts as a gatekeeper, strictly enforcing the Rules.
- The **Conscience** audits the final output against the nuanced Values list.
- The **Spirit** integrates the Conscience's audit to track long-term alignment and provides coaching feedback to the Intellect, closing the loop.

### **Benefits of the Persona-Driven Approach**

**Q: Why are Personas important for SAFi?**

A: Personas make SAFi both **flexible and auditable**. Instead of hard-wiring a single, universal ethic, SAFi can embody different, context-appropriate roles like a "Fiduciary," "Health Navigator," or "Jurist." This approach turns abstract values into concrete, operational roles, allowing SAFi to function as a faithful and transparent moral actor.

---

## Cross refs
- 02 Faculties Values and Profiles
