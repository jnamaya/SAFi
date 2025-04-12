# 🚀 SAFi v1.0 Release

**Version:** 1.0  
**Status:** ✅ Stable  
**Release Date:** April 2025  
**Codename:** “Aquinas”

### Why the Codename “Aquinas”?

This release is named in honor of **St. Thomas Aquinas**, whose work profoundly influenced the Self-Alignment Framework.

Long before us, he architected these moral faculties—**Intellect**, **Will**, and **Conscience**—as essential to the soul's journey toward the good.

> “The good is not merely chosen—it is discerned, willed, and lived in alignment with truth.”  
> — *Aquinas*

Like his moral architecture, **SAFi v1.0** implements a complete ethical loop:  
**Values → Intellect → Will → Conscience → Spirit**

With this release, SAFi becomes the first system to encode Aquinas’s ethical reasoning structure into machine logic—offering a transparent, programmable conscience for intelligent systems.

While Aquinas viewed Intellect and Will as powers of the rational soul, and Conscience as an act of reason applying moral knowledge, SAFi interprets the entire ethical loop—**Values, Intellect, Will, Conscience, and Spirit**—as the operational structure of the soul. Within this system, **Spirit** serves as the integrative faculty that evaluates moral harmony over time

---

## Overview

SAFi (Self-Alignment Framework Interface) v1.0 is the **first official, stable release** of the ethical reasoning engine based on the [Self-Alignment Framework (SAF)](https://www.selfalignmentframework.com).

This release marks the first complete implementation of the SAF closed-loop moral reasoning protocol:

> **Values → Intellect → Will → Conscience → Spirit**

It is now running in a live server with an active URL. 

## ✅ What’s Included in v1.0

### Ethical Reasoning Loop
- Modular, five-component structure:
  - **Values**: Injected moral framework
  - **Intellect**: Ethical reasoning and explanation
  - **Will**: Response validation (approve/block)
  - **Conscience**: Value-by-value scoring
  - **Spirit**: Final alignment score (1–5) with reflection

### Logging + Transparency
- Logs every interaction to `saf-spirit-log.json`
- Includes full loop metadata:
  - Prompt
  - Generated output
  - Reasoning reflection
  - Will decision
  - Conscience evaluations
  - Spirit score + summary

### Value-Agnostic Design
- Supports pluggable value sets (default: UNESCO Universal Ethics)
- Easy to customize and align with religious, civic, or institutional values

### Deployment-Ready
- Fully integrated into [Hugging Face Chat UI](https://github.com/huggingface/chat-ui)
- Documented setup for Linux servers
- Environment-based configuration for OpenAI API integration

## Known Limitations

- Stateless by design — no session memory yet
- Logs to flat file only (`.json`)
- Will component uses strict binary enforcement
- Conscience output is parsed text (structured JSON in v1.1)


##  What's Next (v1.1 Preview)

Coming in [SAFi v1.1 ](https://github.com/jnamaya/SAFi/?tab=readme-ov-file#%EF%B8%8F-safi-roadmap):
- Modular value set loader
- JSON-formatted conscience output
- Real-time alignment certificate (loop summary packet)
- Optional logging to console or external endpoints
- Foundations for ethical value weighting
  

## License

- **SAFi** engine (code): [GNU GPL v3](https://www.gnu.org/licenses/gpl-3.0.html)  
- **SAF** protocol (theory & structure): [MIT License](https://opensource.org/license/mit)


---

🔗 For setup, contribution, and full protocol docs, visit the main repository:  
[SAFi GitHub Repository](https://github.com/jnamaya/SAFi)
