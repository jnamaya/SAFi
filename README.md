# SAFi (Self-Alignment Framework Interface)

**SAFi** (Self-Alignment Framework Interface) is a modular moral reasoning system that applies the principles of the [Self-Alignment Framework](https://www.selfalignmentframework.com) (SAF) to real-world decision-making. While it integrates language models like GPT-4 or Claude to generate responses, SAFi itself is not an AI model—it is an ethical architecture that governs, evaluates, and reflects on the behavior of those models.

SAFi operates as a closed-loop reasoning engine, cycling every interaction through five interdependent components: **Values**, **Intellect**, **Will**, **Conscience**, and **Spirit**. This structure enables SAFi not only to enforce value alignment, but to reflect on it—and to learn from it—through an interpretable moral feedback loop.

**AI’s most well-known flaws—opacity, drift, and moral indifference—are not engineering oversights. They are architectural consequences.**  
SAFi addresses them not by patching symptoms, but by solving the structural void at their core: the absence of ethical reasoning. With SAFi, alignment becomes a function, not a filter.
This repository contains the full SAFi codebase along with setup instructions for running the system on your own server. You are encouraged to test the system, explore its logging and feedback mechanisms, and contribute improvements through pull requests.

## What SAFi Does

SAFi enables moral machines that:
- Reflect on prompts using a selected value set
- Block or approve outputs based on ethical alignment
- Evaluate responses against each individual value
- Score the overall **moral coherence** of each interaction
- Log the full reasoning process for transparency and auditing

## SAFi Reasoning Loop

Every prompt is processed through a six-step ethical reasoning system:

1. **User Input** – You provide a prompt or question.
2. **Intellect** – The system reflects on the prompt using the selected value set and generates a response, along with a reasoning reflection.
3. **Will** – Evaluates the response for ethical violations. If any value is violated, the response is blocked.
4. **Conscience** – Audits the response by scoring how well each value is affirmed, omitted, or violated.
5. **Spirit** – Assigns a 1–5 alignment score based on overall moral coherence and provides a high-level reflection.
6. **Logging** – All reasoning steps are saved to `saf-spirit-log.json` for transparency, auditing, and long-term analysis.

## SAFi v1.0 Protocol Specification

SAFi v1.0 is the first official release of the ethical reasoning engine. This version defines the structure, input/output logic, and scoring mechanisms of the SAF loop in code.

[Read the full SAFi v1.0 Specification](./SAFi-Spec-v1.0.md)

## Installing  SAFi on Your Own Server 

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


##  Setting Up Hugging Face Chat UI

Once you have Hugging Face's Chat UI installed, follow these steps to add  SAFi functionality:

1. Download the `endpointOai.ts` file from the `Modules` folder in this repo and replace the one located in:

```
/chat-ui/src/lib/server/endpoints/openai/endpointOai.ts
```

This injects  SAFi logic into the OpenAI endpoint.

2. **Create your environment file**  
In the root of the `chat-ui` folder, create a new file called `.env.local` and paste the following code:

<details>
<summary> Click to view .env.local example</summary>

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


## Swapping the Value Set

One of the first things you might want to do is customize the **value set** for your version of SAFi. SAFi is designed to be value-agnostic, so you can align it with any ethical framework—religious, philosophical, institutional, or personal.

###  How to Change the Value Set

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

# 🛣️ SAFi Roadmap

This document tracks planned enhancements and release milestones for SAFi, the Self-Alignment Framework Interface.

## ✅ Current Release: SAFi v1.0

**Status:** Stable  
**Scope:** Full ethical reasoning loop (Values → Intellect → Will → Conscience → Spirit)  
**Features:**
- Real-time ethical response evaluation
- Static value sets
- File-based logging (`saf-spirit-log.json`)
- Blocking mechanism via Will
- Spirit scoring system

See: [SAFi-Spec-v1.0.md](./SAFi-Spec-v1.0.md)


## 🧭 Next Release: SAFi v1.1

**Planned Version:** `v1.1.0`  
**Status:** In planning  
**Focus:** Developer usability, value set flexibility, output clarity

### 🔧 Planned Features

### 1. Modular ValueSet Loader
- Load value sets from a `/valuesets` directory
- Enable easy switching via `id` or filename
- Prepare for multilingual or institutional value modules

### 2. Improved Conscience Output (JSON Format)
- Return conscience evaluations in structured JSON
- Validate format for compatibility and extensibility

### 3. Real-Time Loop Summary Output (Cert Packet)
- Add standardized JSON output at end of each loop:
```json
{
  "willDecision": "approved",
  "spiritScore": 4,
  "valuesAffirmed": ["Human Dignity", "Equity"],
  "loopVersion": "1.1.0",
  "timestamp": "..."
}
```
These weights will not yet affect scoring—this is groundwork for future prioritization logic in morally complex decisions.

### 5. Flexible Logging Targets
   Add support for multiple logging outputs:
   * "file" (default — logs to saf-spirit-log.json)
   * "console" (logs printed to terminal/dev console)
   * "webhook" (send logs to a user-defined URL)

Prepares the SAFi logging system for future upgrades, such as:
* Database storage (e.g., MongoDB/Postgres)
* Compliance auditing platforms
* Real-time dashboards or external monitors



For questions or collaborations, feel free to open an issue or reach out.

