#  SAFi

# SAFi

**SAFi** (Self-Alignment Framework Interface) is a modular, open-source **AI reasoning framework** designed to ensure ethical integrity through structured, self-correcting decision-making. It enables AI systems—especially large language models—to evaluate, refine, and align their outputs with a consistent ethical framework.

SAFi is based on the [Self-Alignment Framework](https://selfalignmentframework.com/), a closed-loop ethical architecture composed of five interdependent components: **Values → Intellect → Will → Conscience → Spirit**. Each component contributes to morally coherent responses by simulating an internal ethical dialogue within the AI.

This pilot implementation uses a Catholic value set for demonstration purposes. However, **SAFi is value-agnostic** and can be configured to support **any clearly defined ethical system**, making it ideal for responsible AI development across diverse philosophical, cultural, or institutional contexts.


---

## 🚀 What  SAFi Does

 SAFi helps AI systems think and act ethically by:

1. **Reflecting** on prompts using a selected value set  
2. **Blocking** ethically misaligned outputs  
3. **Evaluating** decisions against each value  
4. **Scoring** overall moral coherence  
5. **Logging** the full process for transparency

---

## 🔁  SAFi Reasoning Loop

1. **User Input** – You ask a question or give a prompt.  
2. **Intellect** – The system reasons through the value set and generates a response + reflection.  
3. **Will** – Checks if the response violates any values. If so, it's blocked.  
4. **Conscience** – Audits the response, evaluating how well it affirms or violates each value.  
5. **Spirit** – Assigns a 1–5 alignment score based on moral coherence.  
6. **Logging** – All steps are saved to `saf-spirit-log.json` in the root of the server. 

---

## 🧪 Installing  SAFi on Your Own Server 

### Requirements:
1. A Linux-based dedicated server (e.g., Ubuntu)
2. An OpenAI API key
3. A domain name *(optional, for custom deployment)*

The frontend of the system uses the [Hugging Face Chat UI](https://github.com/huggingface/chat-ui). It’s simple to install after your server is ready. Run:

```bash
git clone https://github.com/huggingface/chat-ui
cd chat-ui
npm install
```

---

## 🔄 Setting Up Hugging Face Chat UI

Once you have Hugging Face's Chat UI installed, follow these steps to add  SAFi functionality:

1. **Replace the endpoint file**  
   Download the `endpointOai.ts` file from the `Modules` folder in this repo and replace the one located in:

```
/chat-ui/src/lib/server/endpoints/openai/endpointOai.ts
```

This injects  SAFi logic into the OpenAI endpoint.

2. **Create your environment file**  
In the root of the `chat-ui` folder, create a new file called `.env.local` and paste the following code:

<details>
<summary>📋 Click to view .env.local example</summary>

```env
OPENAI_API_KEY=

ANTHROPIC_API_KEY=

MODELS=`[
  { "name": "gpt-4o", "displayName": "GPT 4o", "endpoints": [{ "type": "openai" }] },
  { "name": "claude-3-5-sonnet-20241022", "displayName": "Claude 3.5 Sonnet", "endpoints": [{ "type": "anthropic" }] }
]`

OPENID_CONFIG=`{
  "PROVIDER_URL": "https://accounts.google.com",
  "CLIENT_ID": "",
  "CLIENT_SECRET": "",
  "SCOPES": "openid profile email"
}`

PUBLIC_APP_NAME= SAFi
PUBLIC_APP_VERSION=0.1
PUBLIC_APP_ASSETS= SAFi
PUBLIC_APP_COLOR=blue
PUBLIC_APP_DESCRIPTION= SAFi uses the Self-Alignment Framework to think, filter, reflect, and log its decisions ethically.
PUBLIC_APP_DATA_SHARING="Your conversations are private and never used for training. Spirit-level summaries may be logged locally for ethical alignment."
PUBLIC_APP_DISCLAIMER=" SAFi is a prototype. Responses are AI-generated and should be used with discernment and personal judgment."
```

</details>

👉 **Add your OpenAI API key** where indicated. Anthropic support is currently being tested —  SAFi may still route all calls through OpenAI depending on your endpoint configuration.

> 💬 *Note:* I'm still working on making Chat UI support multiple models from the same endpoint cleanly. This setup is a workaround. If you're more experienced with routing logic or model registration, feel free to suggest improvements or contribute via pull request!

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

 SAFi was created by Nelson as a prototype for ethically grounded AI systems. This implementation uses Catholic values for testing, but the framework is designed to be value-neutral, modular, and universally applicable.

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

