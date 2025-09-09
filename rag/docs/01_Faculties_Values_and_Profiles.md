---
title: SAFi Explained: Values
slug: faculties-values-and-profiles
tags: ["safi", "faculties", "personas", "values"]
summary: Foundational values and ethical profiles that condition SAFi's reasoning and persona behavior.
version: 1.0
---

# SAFi Explained: Values

### **Core Concept: The Role of Values in SAFi**

**Q: What is the difference between SAFi's faculties and its values?**

A: In the Self-Alignment Framework Interface (SAFi), the faculties (Intellect, Will, Conscience, and Spirit) define the **"How"**—the fixed, repeatable process of alignment. The Values define the **"What"**—the subjective ethical content and principles that the process operates on. Values are the ethical setpoint for the entire system.

**Q: Who is responsible for deciding the values a SAFi system uses?**

A: The responsibility lies with the human individual or institution that implements the system. SAFi is a tool designed for alignment; the user provides the core principles for the system to align with.

### **The SAFi Profile: Making Values Operational**

**Q: How does SAFi translate abstract principles into machine instructions?**

A: SAFi transforms abstract values into a structured, machine-readable object called a **profile**. This profile serves as the master blueprint for the AI’s ethical character and behavior. Each profile is a code dictionary (found in values.py) containing several key components.

**Q: What are the key components of a SAFi profile?**

A: A SAFi profile contains the following components:

- **worldview**: The AI's "constitution." It is a detailed narrative that defines the AI’s core purpose, goals, and the fundamental principles from which it should reason. It is the primary directive for the **Intellect** faculty.
- **style**: Defines the AI’s persona and tone (e.g., “Empathetic, clear, and educational”). It instructs the **Intellect** on how to communicate.
- **will_rules**: The "Letter of the Law." This is a list of clear, non-negotiable rules and hard-coded guardrails that the **Will** faculty enforces to prevent forbidden actions.
- **values (list)**: The "Spirit of the Law." This is a list of broader ethical principles, each assigned a numerical weight. This list is used by the **Conscience** for its nuanced audit and by the **Spirit** to calculate long-term performance.

### **How the Profile Instructs the SAFi Faculties**

**Q: How does each part of a profile correspond to a specific SAFi faculty?**

A: Each component of a profile is a static piece of data that directly instructs a faculty in the SAFi loop:

1. The **Intellect** reads the worldview and style to generate its initial response.
2. The **Will** uses the will_rules as its strict, unchanging checklist to approve or block the response.
3. The **Conscience** evaluates the final output against the weighted values list to create its audit.
4. The **Spirit** uses the weights from the values list in its mathematical formulas to update the AI’s long-term memory.


## Cross refs
- 07 Concepts Personas
