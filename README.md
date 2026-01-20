# SAFi: The Governance Engine for AI

## Introduction

SAFi is an enterprise-level, closed-loop governance engine for AI, designed to bridge the gap between organizational values and artificial intelligence behavior. It is built upon four core principles:

| Principle | What It Means | How SAFi Delivers It |
| :--- | :--- | :--- |
| **🛡️ Policy Enforcement** | You define the operational boundaries your AI must follow, protecting your brand reputation.| Custom policies are enforced at the runtime layer, ensuring your rules override the underlying model's defaults.  |
| **🔍 Full Traceability** | Every response is transparent, logged, and auditable. No more "black boxes." | A complete audit trail captures every decision, veto, and reasoning step. |
| **🔄 Model Independence** | Switch or upgrade models without losing your governance layer. | A modular architecture that supports GPT, Claude, Llama, and other major providers. |
| **📈 Long-Term Consistency** | Maintain your AI’s ethical identity over time and detect behavioral drift. | SAFi introduces stateful memory to track alignment trends, detect drift, and auto-correct behavior. |

## Table of Contents

1.  [How Does It Work?](#how-does-it-work)
2.  [Technical Implementation](#technical-implementation)
3.  [Application Structure](#application-structure)
4.  [Application Authentication](#application-authentication)
5.  [Permissions](#permissions)
6.  [Headless Governance Layer](#headless-governance-layer)
7.  [Agent Capabilities](#agent-capabilities)
8.  [Developer Guide](#developer-guide)
9.  [Installation on Your Own Server](#installation-on-your-own-server)
10. [Live Demos](#live-demos)
11. [Get Started](#get-started)

## How Does It Work?

Drawing inspiration from the faculty psychology of philosophers like Plato, Aristotle, Aquinas, and Kant, SAFi implements a cognitive architecture composed of five distinct faculties:

1.  **Values:** The core constitution (principles and rules) that defines the agent's identity.
2.  **Intellect:** The generative engine responsible for formulating responses and actions.
3.  **Will:** The active gatekeeper that decides whether to approve or veto the Intellect's proposed actions.
4.  **Conscience:** The reflective judge that scores actions against the agent's core values after they occur.
5.  **Spirit:** The long-term memory that integrates these judgments to track alignment over time, detecting drift and providing coaching for future interactions.

## Technical Implementation

The core logic of the application resides in **`safi_app/core`**. This directory contains the `orchestrator.py` engine, the `faculties` modules, and the central `values.py` configuration.

*   **`orchestrator.py`**: The central nervous system of the application. It coordinates the data flow between the user, the various faculties, and external services.
*   **`values.py`**: Defines the "constitution" for the system. This file governs the ethical profiles of all agents, which can be configured manually in code or via the frontend Policy Wizard.
*   **`intellect.py`**: Acts as the Generator. It receives context from the Orchestrator and drafts responses or tool calls using the configured LLM.
*   **`will.py`**: Acts as the Gatekeeper. It evaluates the Intellect's draft against the active policy. If a violation is detected, it rejects the draft and requests a retry. If the retry fails, the response is blocked entirely.
*   **`conscience.py`**: Acts as the Auditor. It performs an asynchronous deep-dive audit of every approved response, scoring it on a -1 to 1 scale against specific ethical rubrics.
*   **`spirit.py`**: Acts as the Long-Term Integrator. It aggregates Conscience scores (mapped to a 1-10 scale), updates the agent's alignment vector, and mathematically calculates "drift" implementation to generate coaching notes for future responses.

## Application Structure

SAFi is organized into the following functional areas:

*   **Organization:** Configure global settings, including domain claims, policy weighting, and long-term memory drift sensitivity.
*   **Governance:** Manage the creation of custom Policies (Constitutions) and generate API keys.
*   **Trace & Analyze:** A comprehensive dashboard for viewing decision logs, audit trails, and ethical ratings for every interaction.
*   **AI Models:** Configure and switch between underlying LLM providers (e.g., OpenAI, Anthropic, Google) for each faculty.
*   **My Profile:** Personalize the experience by defining individual User Values, Interests, and Goals that the AI will remember and adapt to.
*   **App Settings:** Manage application preferences, including Themes (Light/Dark) and **Data Source Connections** (Google Drive, OneDrive, GitHub).

## Application Authentication

SAFi uses OpenID Connect (OIDC) for user authentication. You must configure **Google** and **Microsoft** OAuth apps to enable login and data source integrations.

### 1. Google Setup
1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  Create a new project and configure the "OAuth consent screen".
3.  Create **OAuth 2.0 Client IDs** (Web application).
4.  **Authorized Redirect URIs**:
    *   `http://localhost:5000/api/callback` (Login)
    *   `http://localhost:5000/api/auth/google/callback` (Drive Integration)
5.  Copy `Client ID` and `Client Secret` to your `.env` file (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).

### 2. Microsoft Setup
1.  Go to the [Azure Portal](https://portal.azure.com/) > App registrations.
2.  Register a new application (Accounts in any organizational directory + personal Microsoft accounts).
3.  **Redirect URIs** (Web):
    *   `http://localhost:5000/api/callback/microsoft` (Login)
    *   `http://localhost:5000/api/auth/microsoft/callback` (OneDrive Integration)
4.  Create a **Client Secret** in "Certificates & secrets".
5.  Copy `Application (client) ID` and the Secret Value to your `.env` file (`MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`). 

## Permissions

The system utilizes a Role-Based Access Control (RBAC) system:

*   **Admin:** Complete access to all system settings, including global Organization configurations.
*   **Editor:** Access to manage Governance policies, AI Agents, and view Traces, but restricted from modifying Organization-wide settings.
*   **Auditor:** Read-only access to Organization settings, Governance policies, and Trace logs for compliance verification.
*   **Member:** Standard access to Chat and Agents. The Management menu is hidden.

## Headless Governance Layer

SAFi functions as a "Governance-as-a-Service" layer for any external application. You can integrate SAFi's ethical engine into Microsoft Teams, Slack, Telegram, or custom apps using the Headless API.

### How to use it:

1.  **Generate a Policy Key:**
    *   Go to **Governance > Policies**.
    *   Create or Edit a Policy.
    *   Click **Generate API Key** to get your credential (e.g., `sk_policy_...`).

2.  **Call the API:**
    Make a POST request to your SAFi instance from your external bot code.

    **Endpoint:** `POST /api/bot/process_prompt`
    **Headers:**
    ```
    Content-Type: application/json
    X-API-KEY: sk_policy_12345...
    ```
    **Payload:**
    ```json
    {
      "user_id": "teams_user_123",       // Unique ID from your platform
      "message": "Can I approve this expense?",
      "conversation_id": "chat_456",     // Thread ID for memory context
      "persona": "safi"                  // Optional: Agent profile to use
    }
    ```

3.  **Result:**
    SAFi will process the prompt, enforcing the Policy associated with the API Key, and return the governed response. Users are automatically registered in the system ("Just-in-Time" provisioning) so you can audit their interactions in the Trace dashboard. 

## Agent Capabilities

SAFi is designed to be extensible, supporting multiple data sources including RAG (Retrieval-Augmented Generation), MCP (Model Context Protocol), and custom plugins.

The demo environment includes several specialized agents to showcase these capabilities:

*   **The Contoso Admin:** Connects directly to **Microsoft SharePoint and OneDrive** via MCP. This agent can search corporate files, read documents, and access the organizational knowledge base in real-time.
*   **The Fiduciary:** A financial specialist using **tool-calling** to access live market data and portfolio information, demonstrating secure integration with sensitive APIs.
*   **The Bible Scholar:** Demonstrates **RAG** capabilities by strictly referencing a fixed corpus (the Bible) to provide accurate citations and theological analysis without hallucination.
*   **Google & GitHub Integrations:** Standard agents equipped with MCP connectors to search **Google Drive** or interact with **GitHub** repositories, functioning as capable digital co-workers.

## Developer Guide

Refere to this guide to extend SAFi with new data sources and capabilities.

### 1. How to Add a New Data Source (MCP Tool)

Use MCP to give an agent "tools" (e.g., searching a database, posting to Slack).

1.  **Create the Tool Implementation:**
    Navigate to `safi_app/core/mcp_servers/` and create a new Python file (e.g., `slack.py`). Define your async functions here.

2.  **Register the Tool Logic:**
    Open `safi_app/core/services/mcp_manager.py`.
    *   **Add Schema:** Update `get_tools_for_agent` to include the JSON schema (name, description, inputs).
    *   **Add Routing:** Update `execute_tool` to import your module and dispatch the call.

3.  **Enable for an Agent:**
    Open `safi_app/core/values.py` (or use the frontend Wizard).
    Add the tool name to the `tools` list in the agent's profile:
    ```python
    "tools": ["sharepoint_search", "slack_post_message"]
    ```

### 2. How to Add a New Knowledge Base (RAG)

Use RAG to give an agent a static "brain" of documents (e.g., a policy handbook).

1.  **Generate the Vector Index:**
    Process your text files into a FAISS index using the helper script `scripts/build_vector_store.py`. This generates two files:
    *   `my_knowledge.index`: The searchable vector data.
    *   `my_knowledge_metadata.pkl`: The map of text chunks to vectors.

2.  **Deploy the Files:**
    Place both files into the `vector_store/` directory.

3.  **Enable for an Agent:**
    Open `safi_app/core/values.py`.
    Set the `rag_knowledge_base` key in the agent's profile:
    ```python
    "rag_knowledge_base": "my_knowledge"
    ```

### 3. How to Add a Plugin (Prompt Interception)

Use Plugins to run logic *before* the prompt reaches the LLM (e.g., injecting context).

1.  **Create the Plugin:**
    Create a file in `safi_app/core/plugins/` (e.g., `weather_injector.py`).
    Write a function that accepts `user_prompt` and returns data or a modified prompt.

2.  **Hook Implementation:**
    Open `safi_app/core/orchestrator.py` and locate `process_prompt`.
    Add your plugin to the `plugin_tasks` list:
    ```python
    plugin_tasks = [
        # ... existing plugins
        weather_injector.get_weather(user_prompt...)
    ]
    ```

3.  **Context Injection:**
    The returned data is automatically collected into `plugin_context_data` and passed to the Intellect faculty.

## Installation on Your Own Server

You can host SAFi on any standard Linux server (Ubuntu/Debian recommended) or Windows machine.

### Prerequisites

*   **Python:** 3.11 or higher
*   **Database:** MySQL 8.0+ (Required for JSON column support)
*   **Web Server:** Nginx or Apache (for production reverse proxy)

### Step-by-Step Guide

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/jnamaya/SAFi.git
    cd SAFi
    ```

2.  **Prepare the Frontend:**
    The Flask backend expects the frontend files in a folder named `public`.
    ```bash
    mv chat public
    ```

3.  **Set Up Virtual Environment:**
    ```bash
    python -m venv venv
    # Linux/Mac
    source venv/bin/activate
    # Windows
    .\venv\Scripts\activate
    ```

4.  **Install Dependencies:**
    (If `requirements.txt` is missing, install the core packages manually)
    ```bash
    pip install flask mysql-connector-python authlib requests numpy openai groq anthropic google-auth-oauthlib python-dotenv
    ```

5.  **Configure Environment:**
    Copy the example configuration and edit it with your secrets.
    ```bash
    cp .env.example .env
    nano .env
    ```
    *   **Database:** Update `DB_HOST`, `DB_USER`, `DB_PASSWORD`.
    *   **LLMs:** Add your OpenAI/Anthropic/Groq keys.
    *   **Auth:** Add Google/Microsoft Client IDs (optional, but required for login).

6.  **Initialize Database:**
    Create an empty database in MySQL. SAFi will automatically create the tables on the first run.
    ```sql
    CREATE DATABASE safi CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    ```

7.  **Run the Application:**
    ```bash
    # Development
    flask --app safi_app run --debug
    
    # Production (using Waitress or Gunicorn)
    pip install waitress
    waitress-serve --call "safi_app:create_app"
    ```

    ### 9. Production Proxy Configuration (Optional)

    If you are running behind a web server (recommended for SSL/HTTPS), configure it to forward traffic to SAFi.

    **Nginx Configuration:**
    ```nginx
    server {
        listen 80;
        server_name your-domain.com;

        location / {
            proxy_pass http://127.0.0.1:5000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
    ```

    **Apache Configuration:**
    Ensure `mod_proxy` and `mod_proxy_http` are enabled.
    ```apache
    <VirtualHost *:80>
        ServerName your-domain.com

        ProxyPreserveHost On
        ProxyPass / http://127.0.0.1:5000/
        ProxyPassReverse / http://127.0.0.1:5000/
    </VirtualHost>
    ```


8.  **Access:**
    Open your browser to `http://localhost:5000` (or your server's IP).

> **Note on RAG:** To use the Bible Scholar or other RAG agents, you must generate the vector store first.
> `python -m safi_app.scripts.build_vector_store`

## Live Demos

### 🚀 Try SAFi Yourself

- **DEMO URL**: [safi.selfalignmentframework.com](https://safi.selfalignmentframework.com)
  

## 🤝 Contributing

We welcome contributions from the community! Whether you're a developer, ethical AI researcher, or policy expert, here is how you can help.

### Areas We Need Help With

We are currently looking for contributors to help with:
*   **🐳 Dockerization:** Creating optimized Docker images and `docker-compose.yml` for easier deployment.
*   **🧪 Testing:** Implementing unit and integration tests (using `pytest`) to ensure system stability.
*   **📖 Documentation:** Improving the Headless API guides and adding more language-specific examples.

### How to Contribute

1.  **Fork the Project** on GitHub.
2.  **Create your Feature Branch** (`git checkout -b feature/AmazingFeature`).
3.  **Commit your Changes** (`git commit -m 'Add some AmazingFeature'`).
4.  **Push to the Branch** (`git push origin feature/AmazingFeature`).
5.  **Open a Pull Request**.

Please ensure your code follows the existing style concepts and includes comments where necessary.
---

- [GitHub Repository](https://github.com/jnamaya/SAFi)
- [Documentation](https://selfalignmentframework.com/articles/)
- [Join Us](https://selfalignmentframework.com/join-us/)
