# SAFi (Self-Alignment Framework Interface)

**SAFi** is a modular **moral reasoning system** designed to apply the principles of the [Self-Alignment Framework (SAF)](https://www.selfalignmentframework.com) to real-world decision-making. While it uses AI models (like GPT-4 or Claude) to generate responses, SAFi itself is **not an AI model** — it is a **structured ethical system** that governs, evaluates, and reflects on the behavior of those models.

SAFi enables closed-loop moral alignment by processing outputs through five interdependent components: **Values**, **Intellect**, **Will**, **Conscience**, and **Spirit**. Together, these form a reasoning cycle that allows SAFi to assess alignment, enforce moral boundaries, and reflect on long-term coherence.

It directly addresses three of the most pressing challenges in AI today — **bias**, **value drift**, and **hallucination** — by embedding ethical reasoning and feedback into every decision. SAFi is **value-agnostic**, **fully auditable**, and designed to support **compliance**, **moral accountability**, and **alignment transparency** across a wide range of use cases.

This repository contains the full SAFi codebase along with setup instructions for running the system on your own server. You are encouraged to test the system, explore its logging and feedback mechanisms, and contribute improvements through pull requests.

## What SAFi Does

SAFi enables moral machines that:
- Reflect on prompts using a selected value set
- Block or approve outputs based on ethical alignment
- Evaluate responses against each individual value
- Score the overall **moral coherence** of each interaction
- Log the full reasoning process for transparency and auditing

## SAFi Reasoning Loop

Every prompt is processed through a six-step ethical reasoning machine:

1. **User Input** – You provide a prompt or question.
2. **Intellect** – The system reflects on the prompt using the selected value set and generates a response, along with a reasoning reflection.
3. **Will** – Evaluates the response for ethical violations. If any value is violated, the response is blocked.
4. **Conscience** – Audits the response by scoring how well each value is affirmed, omitted, or violated.
5. **Spirit** – Assigns a 1–5 alignment score based on overall moral coherence and provides a high-level reflection.
6. **Logging** – All reasoning steps are saved to `saf-spirit-log.json` for transparency, auditing, and long-term analysis.


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

# 🔭 SAFi Feature Roadmap

## Pilot Status

SAFi is currently operating as a faithful implementation of the [Self-Alignment Framework (SAF)](https://your-site-link.com), executing the full closed-loop sequence:

**Values → Intellect → Will → Conscience → Spirit**

This ethical loop is functioning effectively in the pilot system. Early testing confirms that SAFi can evaluate prompts, enforce value alignment, and log moral coherence in real time.

## 🛠️ Planned Features for Next Iteration

### 1.Enhanced Will – Contextual Prioritization & Feedback Loop
Currently, the Will component performs a binary decision: `approve` or `block`. The next version will:
- Allow Will to prioritize specific values based on context.
- Enable Will to send targeted feedback to Intellect to re-run the prompt with different value weighting.
- Support ethical prioritization in morally complex scenarios.

### 2.Session Memory – Toward Ethical Continuity
SAFi is stateless at present. This feature introduces:
- Per-user session memory managed by Spirit.
- Ethical summaries and past interactions accessible to Intellect.
- Conversation-level alignment that builds over time, helping SAFi evolve into a self-regulating system.

### 3.Database-Backed Logging for Spirit
The current implementation writes logs to a flat JSON file. Next steps:
- Migrate Spirit logs to a database engine (e.g., MongoDB or Postgres).
- Enable structured queries, user-level histories, and multi-session evaluations.
- Improve compliance support and enable external audits.

## Additional Roadmap Ideas

### 4.Modular ValueSet Control Panel (Planned for Admin Interface)
- A frontend interface to define, lock, or propose changes to value sets.
- Support value governance models with permission levels.
- Ensure institutional compliance by preventing unauthorized edits.

### 5. Prompt Validation Sandbox
- Let admins test prompts in a side-by-side view: raw LLM vs SAFi output.
- Visualize alignment scores, Will decisions, and value coverage.
- Useful for training, education, and onboarding users to SAFi’s behavior.

### 6. Admin Dashboard for Compliance & Insights
- Track most common prompts, average Spirit scores, Will decisions over time.
- Identify ethical drift or misuse patterns.
- Export reports for governance, policy reviews, or external auditing.

### 7.Multi-Agent Reasoning with Redundant LLMs
- Configure Intellect, Will, or Conscience to run on different LLMs (e.g., GPT-4 for Intellect, Claude for Will).
- Compare outputs for redundancy, conflict detection, or LLM bias mitigation.

### 8.Locked Compliance Mode
- Allow institutions to "freeze" their value set and SAFi behavior.
- Any changes must go through an approval workflow.
- Log compliance state and generate attestations for certifications or audits.


## Long-Term Vision

SAFi is more than a chatbot. It’s a modular, ethically grounded **reasoning agent** that can adapt to the ethical frameworks of any institution. As it matures, SAFi will become a trusted interface for AI alignment, compliance, education, and governance across sectors.





For questions or collaborations, feel free to open an issue or reach out.

