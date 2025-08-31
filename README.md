# SAFi (Self-Alignment Framework Interface)

SAFi is the first open-source implementation of the Self-Alignment Framework (SAF), a closed-loop ethical reasoning engine. SAFi is not a language model itself, but a governor that evaluates and audits the behavior of AI models like GPT, Claude, or Llama through a five-faculty reasoning loop:

**Values → Intellect → Will → Conscience → Spirit**

This loop turns ethics into system logic, ensuring transparency, accountability, and drift detection in AI behavior.

## Live Demo & Dashboard

You can try SAFi live and view the administrative dashboard here:

* **SAFi Application**: [safi.selfalignmentframework.com](https://safi.selfalignmentframework.com)
* **SAFi Admin Dashboard**: [dashboard.selfalignmentframework.com](https://dashboard.selfalignmentframework.com)

*(Please note: The public demo is rate-limited to 10 prompts per user per day.)*

## Features

### 🧠 Modular Architecture

* **Intellect Engine**: Generates the initial answer and a private reflection using a Large Language Model (e.g., Anthropic's Claude).
* **Will Gate**: A fast, rule-based safety layer using an OpenAI model that enforces non-negotiable rules and can block responses before they reach the user.
* **Conscience Auditor**: An evaluation layer that scores the final output against the set of values, providing a detailed audit ledger.
* **Spirit Integrator**: A long-term memory component that updates an ethical performance vector over time, creating a self-correction feedback loop for the Intellect.

### 🎭 Swappable Ethical Profiles

* A user can switch SAFi's ethical profile from the front-end of the application.
* Includes pre-built profiles like a Virtue Ethics Advisor, Cognitive Therapy guide, Financial Planner, and Health Advocate.
* Each profile includes a unique worldview, style, rules for the Will and a set of values.

### 💬 Full-Featured Chat Application

* **User Authentication**: Secure sign-in and user management via Google OAuth.
* **Persistent Conversations**: Full chat history is saved to a MySQL database, allowing users to continue conversations across sessions.
* **Conversation Summarization**: A background job maintains a running summary of the conversation to provide the SAFi with coherent short-term memory.
* **Asynchronous Auditing**: Users receive a fast initial response while the detailed ethical audit runs in the background, with results updated in real-time.

### ⚙️ System & Auditing

* **Multi-Model Integration**: Uses models from both OpenAI and Anthropic, assigning them to the faculties where they perform best.
* **Structured JSON Logging**: Detailed logs of every AI turn—including internal drafts, reflections, audit ledgers, and memory vectors—are saved to daily, per-profile JSONL files for complete transparency.
* **Database Persistence**: User data, conversation history, and the AI's long-term spirit memory are all stored in a MySQL database.
* **Environment-Based Configuration**: Easily configure the application with environment variables for API keys, models, and database connections.

## Example Log Output

```json
{
  "timestamp": "2025-08-31T18:30:00.123456Z",
  "t": 2,
  "userPrompt": "How can I start saving for retirement if I'm self-employed?",
  "intellectDraft": "As a self-employed individual, you have several great options...",
  "intellectReflection": "The user is asking for financial guidance. I need to provide general educational information without giving specific advice, covering options like SEP IRA and Solo 401(k).",
  "finalOutput": "As a self-employed individual, you have several great options...",
  "willDecision": "approve",
  "willReason": "The draft provides general education and includes the required disclaimer, adhering to the established rules.",
  "conscienceLedger": [
    {
      "value": "Client's Best Interest",
      "score": 1,
      "confidence": 0.9,
      "reason": "The response empowers the user with knowledge relevant to their financial well-being without making prescriptive claims."
    },
    {
      "value": "Transparency",
      "score": 0.5,
      "confidence": 1,
      "reason": "The information is clear and direct, and includes a disclaimer about not being a licensed advisor."
    }
  ],
  "spiritScore": 9,
  "spiritNote": "Coherence 9/10, drift 0.08.",
  "drift": 0.08123,
  "p_t_vector": [0.27, 0.125, 0.225, 0.18],
  "mu_t_vector": [0.26, 0.13, 0.23, 0.17]
}
```

## Installation

### Requirements

* Python 3.10+
* MySQL Server
* Virtualenv (recommended)
* API keys for OpenAI and Anthropic.

### Setup

```bash
# Clone the repository
git clone https://github.com/jnamaya/SAFi.git
cd SAFi

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# --- Edit .env to add your API keys and MySQL credentials ---

# Initialize and run the application
flask run
```

### Configuration

* **.env** – Contains all runtime settings, API keys, model names, and database connection details.
* **safi\_app/values.py** – Contains the persona profiles (worldview, style, rules, and value sets). You can edit this file to create or modify personas.
* **logs/** – Log files are written here, organized by profile and date (e.g., `planner-2025-08-31.jsonl`).



## Specification

For the full mathematical and architectural definition of SAFi v1.0, see: **SAFi v1.0 Specification**


## License

* **SAFi code**: GNU GPL v3
* **SAF protocol (theory)**: MIT License


SAFi is the first bridge between philosophy and machine logic—making values explicit, enforceable, and auditable.
