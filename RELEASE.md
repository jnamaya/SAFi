# 🚀 SAFi v1.0 Release

**Version:** 1.0  
**Status:** ✅ Stable  
**Release Date:** April 2025  
**Codename:** “Aquinas”

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
