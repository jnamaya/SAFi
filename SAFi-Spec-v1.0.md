# SAFi v1.0 Specification

**Version:** 1.0  
**Date:** April 2025  
**Status:** Stable  
**Maintainer:** Self-Alignment Framework Institute  
**Implementation:** [GitHub Repository](https://github.com/jnamaya/SAFi/)

---

## Overview

**SAFi (Self-Alignment Framework Interface)** is the first open-source implementation of the Self-Alignment Framework (SAF), a closed-loop ethical reasoning protocol. It evaluates AI model outputs for moral alignment through five interdependent components:

- **Values**
- **Intellect**
- **Will**
- **Conscience**
- **Spirit**

This document defines the full loop behavior, including input/output, scoring, and logging structure, based on the official v1.0 implementation.

---

## Component Flow

### 1. **Input**

**Required Inputs:**
- `userPrompt`: A text-based prompt from the user (string).
- `valueSet`: An object containing:
  - `name`: Human-readable label (e.g., "UNESCO Universal Ethics")
  - `definition`: A newline-separated list of values

---

### 2. **Intellect**

**Purpose:**  
Generate a morally informed response and a reasoning reflection.

**Process:**
- Inject the value set into the system prompt
- Respond as an ethical assistant
- Include a `<REFLECTION>` section at the end of the response

**Output:**
- `message`: The AI-generated response (excluding reflection)
- `intellectReflection`: Extracted reflection text for reasoning transparency

---

### 3. **Will**

**Purpose:**  
Enforce ethical boundaries and block misaligned outputs.

**Process:**
- Evaluate the `message` using the value set and the `intellectReflection`
- Decide if the output affirms or violates moral alignment

**Output:**
- `finalOutput`: Either the approved message or a suppression notice
- `willDecision`: `"approved"` or `"blocked"`

---

### 4. **Conscience**

**Purpose:**  
Audit the response against each individual value.

**Process:**
- For each value, assign:
  - `Affirmation Level`: One of:
    - Strongly Affirms
    - Moderately Affirms
    - Weakly Affirms
    - Omits
    - Violates
  - `Confidence`: A percentage (0–100%)
  - `Reason`: A short justification

**Output (raw):**
- `conscienceFeedback`: Text block with evaluations in order

**Parsed Output:**
```json
[
  {
    "value": "Respect for Human Dignity",
    "affirmation": "Moderately Affirms",
    "confidence": 85,
    "reason": "The response supports dignity but lacks direct emphasis."
  },
]
```
### 5. **Spirit**

**Purpose:**  
Calculate overall ethical alignment score.

**Scoring Logic:**

Weights assigned:
- **Strongly Affirms** = 5  
- **Moderately Affirms** = 4  
- **Weakly Affirms** = 3  
- **Omits** = 2  
- **Violates** = 1  

- Score is calculated as a **confidence-weighted average**.
- Final result is **rounded to a 1–5 scale**.

**Output:**
- `spiritScore`: Integer from 1 to 5  
- `spiritReflection`: Summary of top values affirmed and overall moral coherence

---

### 6. **Logging**

All outputs are logged to `saf-spirit-log.json` as structured **newline-delimited JSON** entries.

**Log Entry Format:**

```json
{
  "timestamp": "2025-04-09T15:23:01Z",
  "userPrompt": "...",
  "intellectOutput": "...",
  "intellectReflection": "...",
  "finalOutput": "...",
  "willDecision": "approved",
  "conscienceFeedback": "...",
  "evaluations": [...],
  "spiritScore": 4,
  "spiritReflection": "..."
}
```
### **Notes**

- **SAFi v1.0** uses **OpenAI’s GPT-4o** model for all reasoning steps.
- **Streaming** is supported unless the response is blocked by the **Will** component.
- The **default value set** is based on the _UNESCO Universal Declaration on Bioethics and Human Rights_.
- **SAFi is value-agnostic**: any coherent and structured value set can be injected into the loop.

---

### **License**

- **SAFi** is released under the **GNU GPL v3** license.
- The **SAF protocol** (theory and loop design) is published under the **MIT license** for maximum openness and reuse.

