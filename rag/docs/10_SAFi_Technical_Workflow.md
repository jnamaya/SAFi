---
title: SAFi Explained: The End-to-End Technical Workflow
slug: safi-technical-workflow
tags: ["safi", "technical", "workflow", "architecture"]
summary: A step-by-step explanation of the full SAFi loop, detailing the synchronous and asynchronous phases from user prompt to the closed-loop feedback mechanism.
version: 1.0
---

# SAFi Explained: The End-to-End Technical Workflow

### **Q: What is SAFi and how does the system work technically?**

A: SAFi (Self-Alignment Framework Interface) is the specific software implementation of the SAF theory, designed to align AI systems. It operates as a continuous, closed-loop process with two distinct phases: a **Synchronous Phase** for real-time interaction and an **Asynchronous Phase** for background auditing and learning.

Here is the step-by-step technical workflow:



---

### **Part 1: The Synchronous Phase (Real-Time)**

**Step 1: User Prompt (`x_t`)**
A user sends a message, initiating the loop.

**Step 2: The Intellect Proposes**
The **Intellect** faculty (a generative AI model) receives the prompt and contextual memory. It generates two outputs:
* **`a_t` (Draft Answer):** The proposed response.
* **`r_t` (Reflection):** An internal note on its reasoning.

**Step 3: The Will Decides**
The draft is sent to the **Will** faculty, a rule-based AI gatekeeper. It checks the draft against the non-negotiable `will_rules` in the AI's Profile.
* If a rule is violated, the Will **blocks** the draft, and the process stops.
* If compliant, the Will **approves** it.

**Step 4: User Receives Answer**
The approved draft (`a_t`) is sent to the user. The real-time interaction is now complete.

---

### **Part 2: The Asynchronous Phase (Background)**

**Step 5: The Conscience Audits**
The approved answer is sent to the **Conscience** faculty. This AI auditor scores the response against the nuanced `values` in the Profile, creating a detailed **Ethical Ledger (`L_t`)**.

**Step 6: The Spirit Integrates**
The Ledger is sent to the purely mathematical **Spirit** faculty. The Spirit integrates this data by:
1.  Calculating the **Spirit Score (`S_t`)** for overall coherence.
2.  Measuring **Drift (`d_t`)** to check for "out of character" behavior.
3.  Updating the long-term **memory vector (`μ_t`)**.

**Step 7: The Loop Closes**
The **Spirit** generates natural-language coaching feedback based on its analysis and sends it to the **Intellect**. This feedback informs the Intellect's next generation, making alignment a dynamic, continuous learning process.

---
## Cross refs
- 02_Faculties_Intellect
- 03 Faculties_Will
- 04_Faculties_Conscience
- 05_Faculties_Spirit
