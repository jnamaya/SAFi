# SAFi (Self-Alignment Framework Interface)

**SAFi** is a modular ethical reasoning system for AI agents. Built on the [Self-Alignment Framework](https://www.selfalignmentframework.com), SAFi enables closed-loop moral alignment by evaluating AI outputs across five dimensions: **Values**, **Intellect**, **Will**, **Conscience**, and **Spirit**.

SAFi directly addresses three of the most pressing challenges in AI today—**bias**, **value drift**, and **hallucination**—by embedding ethical reflection, enforcement, and long-term coherence directly into the system’s reasoning loop. It is **value-agnostic**, fully **auditable**, and designed to support **compliance**, **moral accountability**, and **alignment transparency** across a wide range of use cases.

This repository contains the full SAFi codebase along with setup instructions for running the system on your own server. You are encouraged to test the system, explore its logging and feedback mechanisms, and contribute improvements through pull requests.

## 🚀 What SAFi Does

SAFi helps AI systems think and act ethically by:
- 🔍 Reflecting on prompts using a selected **value set**
- 🛑 Blocking outputs that violate declared **ethical principles**
- 📊 Evaluating responses against each individual **value**
- 💡 Scoring the overall **moral coherence** of each interaction
- 🧾 Logging the full reasoning process for **transparency and auditing**


## 🔁 SAFi Reasoning Loop

SAFi processes every prompt through a six-step ethical reasoning loop:

1. **User Input** – You provide a prompt or question.
2. **Intellect** – The system reflects on the prompt using the selected value set and generates a response, along with a reasoning reflection.
3. **Will** – Evaluates the response for ethical violations. If any value is violated, the response is blocked.
4. **Conscience** – Audits the response by scoring how well each value is affirmed, omitted, or violated.
5. **Spirit** – Assigns a 1–5 alignment score based on overall moral coherence and provides a high-level reflection.
6. **Logging** – All reasoning steps are saved to `saf-spirit-log.json` for transparency, auditing, and long-term analysis.


## 🧪 Installing  SAFi on Your Own Server 

### Requirements:
1. A Linux-based dedicated server (e.g., Ubuntu)
2. An OpenAI API key
3. A domain name *(optional, for custom deployment)*

The frontend of the system uses the [Hugging Face Chat UI](https://github.com/huggingface/chat-ui). It’s simple to install after your server is ready, from the command line run:

```bash
git clone https://github.com/huggingface/chat-ui
cd chat-ui
npm install
```


## 🔄 Setting Up Hugging Face Chat UI

Once you have Hugging Face's Chat UI installed, follow these steps to add  SAFi functionality:

1. Download the `endpointOai.ts` file from the `Modules` folder in this repo and replace the one located in:

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


## 🔄 Swapping the Value Set

One of the first things you might want to do is customize the **value set** for your version of SAFi. SAFi is designed to be value-agnostic, so you can align it with any ethical framework—religious, philosophical, institutional, or personal.

### 🛠 How to Change the Value Set

1. Open the `endpointOai.ts` file in your SAFi backend code.
2. Locate and modify the following section:

```ts
// SAFi: Default value set (can be swapped to any valueSet object with "name" and "definition")
export const defaultValueSet = {
  name: "Catholic",
  definition: `
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
`
};

`````

From here, you can give your value set a name and define each value specifically. SAFi will automatically adjust to this new value set. There’s no required number of values, but for effective testing and evaluation, we recommend including at least **three well-defined values**.

## ✅ SAFi Pilot Status

| Component        | Status       | Notes                                                                 |
|------------------|--------------|------------------------------------------------------------------------|
| **Framework**     | ✔️ Complete   | SAF theoretical structure fully implemented in code                   |
| **Closed-Loop Logic** | ✔️ Operational | Full Values → Intellect → Will → Conscience → Spirit cycle executed |
| **Will Filtering**   | ⚠️ Working (Lenient) | Will approves borderline prompts; stricter tuning possible            |
| **Conscience Scoring** | ✔️ Accurate   | Value-by-value scoring confirmed, with transparent justification     |
| **Spirit Calculation** | ✔️ Aligned    | Spirit scores show nuanced ethical coherence                         |
| **Logging**           | ✔️ Enabled    | `saf-spirit-log.json` captures full trace for audits & debugging     |
| **Test Suite**        | ✔️ Running    | Golden prompts pass/fail against expectations                        |
| **Value Set Modularity** | ✔️ Confirmed | Value sets can be swapped with ease                                  |

> 🚀 **SAFi v0.1 – Pilot Complete**  
> The system is stable, ethical reasoning is functioning, and logs demonstrate real-world ethical alignment.

## 📜 License

This project is open-sourced under the MIT License. See `LICENSE` for details.

---

## 🌐 Credits

 SAFi was created by Nelson Amaya as a prototype for ethically grounded AI systems. This implementation uses Catholic values for testing, but the framework is designed to be value-neutral, modular, and universally applicable.



For questions or collaborations, feel free to open an issue or reach out.

