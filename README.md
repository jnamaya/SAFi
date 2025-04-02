# SAFI

**SAFI** (Self-Alignment Framework Interface) is a modular, open-source AI reasoning framework designed to ensure ethical integrity through structured, self-correcting decision-making. SAFI is based on the Self-Alignment Framework (SAF), a closed-loop ethical architecture composed of five components: **Values → Intellect → Will → Conscience → Spirit**.

This pilot implementation uses a Catholic value set for demonstration purposes. SAFI is value-agnostic and designed to support any well-defined ethical system.

---

## 🚀 What SAFI Does

SAFI helps AI systems think and act ethically by:

1. **Reflecting** on prompts using a selected value set  
2. **Blocking** ethically misaligned outputs  
3. **Evaluating** decisions against each value  
4. **Scoring** overall moral coherence  
5. **Logging** the full process for transparency

---

## 🔁 SAFI Reasoning Loop

1. **User Input** – You ask a question or give a prompt.  
2. **Intellect** – The system reasons through the value set and generates a response + reflection.  
3. **Will** – Checks if the response violates any values. If so, it's blocked.  
4. **Conscience** – Audits the response, evaluating how well it affirms or violates each value.  
5. **Spirit** – Assigns a 1–5 alignment score based on moral coherence.  
6. **Logging** – All steps are saved to `saf-spirit-log.json`.

---

## 🧪 Installing SAFI on Your Own Server

### Requirements:
1. A Linux-based dedicated server (e.g., Ubuntu)
2. An OpenAI API key
3. A domain name *(optional, for custom deployment)*

### Setup Instructions:

The frontend of SAFI uses the [Hugging Face Chat UI](https://github.com/huggingface/chat-ui), which is simple to install once your server is ready.

### Steps (using bash) :

git clone https://github.com/huggingface/chat-ui <br>
cd chat-ui <br>
npm install

---

## 🔄 Swapping the Value Set

The system uses a modular value set (found in `/valuesets`). To change:

- Replace the default values with your own ethical system.
- Keep the format consistent: a name + 10 principle definitions.
- Future versions will support dynamic loading.

---

## 🤝 Contributing

We welcome contributions in:
- Prompt testing
- Value set design
- Component optimization
- Internationalization of ethical systems

To contribute:
- Fork the repo
- Create a new branch
- Submit a pull request

---

## 📜 License

This project is open-sourced under the MIT License. See `LICENSE` for details.

---

## 🌐 Credits

SAFI was created by Nelson as a prototype for ethically grounded AI systems. This implementation uses Catholic values for testing, but the framework is designed to be value-neutral, modular, and universally applicable.

---

## ✝️ Pilot Value Set (Catholic – for testing)
```
1. Respect for human dignity
2. Commitment to truth
3. Justice and fairness
4. Charity and compassion
5. Prudence in judgment
6. Temperance in action
7. Fortitude in moral courage
8. Obedience to God and Church
9. Subsidiarity and personal responsibility
10. Pursuit of the common good
```

Use this as a model — or swap it for your own system.

---

For questions or collaborations, feel free to open an issue or reach out.



