/**
 * Help Tab — User-facing guide for SAFi.
 * Written for a general audience: no backend or technical references.
 */

export function renderSettingsHelpTab() {
    const container = document.getElementById('tab-help');
    if (!container) return;

    container.innerHTML = `
        <div class="max-w-3xl">

            <div class="settings-page-header">
                <h1>Help &amp; User Guide</h1>
                <p>Everything you need to know to get the most out of SAFi.</p>
            </div>

            <div class="bg-gray-50 dark:bg-neutral-800 rounded-xl p-4 mb-6 border border-gray-200 dark:border-neutral-700">
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">On this page</p>
                <div class="grid grid-cols-2 gap-1 text-sm">
                    <a href="#help-what"        class="text-green-600 dark:text-green-400 hover:underline py-0.5">What is SAFi?</a>
                    <a href="#help-who"         class="text-green-600 dark:text-green-400 hover:underline py-0.5">Who is SAFi for?</a>
                    <a href="#help-start"       class="text-green-600 dark:text-green-400 hover:underline py-0.5">Using SAFi</a>
                    <a href="#help-concepts"    class="text-green-600 dark:text-green-400 hover:underline py-0.5">Key concepts</a>
                    <a href="#help-chat"        class="text-green-600 dark:text-green-400 hover:underline py-0.5">Chat</a>
                    <a href="#help-agents"      class="text-green-600 dark:text-green-400 hover:underline py-0.5">Agents</a>
                    <a href="#help-policies"    class="text-green-600 dark:text-green-400 hover:underline py-0.5">Policies</a>
                    <a href="#help-org"         class="text-green-600 dark:text-green-400 hover:underline py-0.5">Organization</a>
                    <a href="#help-models"      class="text-green-600 dark:text-green-400 hover:underline py-0.5">AI Models</a>
                    <a href="#help-roles"       class="text-green-600 dark:text-green-400 hover:underline py-0.5">Roles & Permissions</a>
                    <a href="#help-faq"         class="text-green-600 dark:text-green-400 hover:underline py-0.5">FAQ</a>
                </div>
            </div>

            <!-- What is SAFi — starts open -->
            <div id="help-what" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">What is SAFi?</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>SAFi is an open-source governance engine for AI agents. It provides the infrastructure, rules, and oversight layer that lets organizations deploy AI responsibly — without depending on any single vendor or platform.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Think of it like a console</p>
                        <p>The easiest way to understand SAFi is through an analogy. Think of SAFi as a game console or a video player. The console itself doesn't define what you play or watch — that's up to you. The <strong class="text-gray-900 dark:text-white">console is SAFi</strong>, and the <strong class="text-gray-900 dark:text-white">game or movie is the agent</strong>.</p>
                        <p class="mt-2">Just as one console can run thousands of different games, SAFi runs unlimited agents — each with its own name, purpose, personality, and rules — all powered by the same underlying engine. You swap the agent, not the infrastructure.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">How it works</p>
                        <p>SAFi sits between the user and the AI model. Every message goes through the engine, which checks whether the agent is staying within its defined scope, evaluates each response against your organization's values and standards, and blocks or retries anything that doesn't meet the standard. The result is an AI that behaves consistently — not just most of the time, but every time.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Open source by design</p>
                        <p>SAFi is fully open source. You can inspect the code, audit the governance logic, modify it for your needs, and self-host it on your own infrastructure. There is no black box — the rules your agents follow are the rules you can read and change. This makes SAFi especially well-suited for organizations that require transparency, compliance, or full data sovereignty.</p>
                    </div>

                </div>
            </div>

            <!-- Who is SAFi for -->
            <div id="help-who" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Who is SAFi for?</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>SAFi is built for organizations and individuals who need to comply with regulatory requirements, or who simply want full control and privacy over their AI systems.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Organizational structure</p>
                        <p>Out of the box, SAFi assumes a basic organizational structure: a unique domain (e.g., <code class="bg-gray-100 dark:bg-neutral-700 text-gray-800 dark:text-gray-200 px-1.5 py-0.5 rounded text-xs font-mono">company.com</code>), a mission statement with core values, and a separation of roles — Members, Auditors, Editors, and Admins.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Authentication</p>
                        <p>SAFi has native support for enterprise authentication via <strong class="text-gray-900 dark:text-white">Microsoft</strong> and <strong class="text-gray-900 dark:text-white">Google</strong> identity providers, so you can control and manage access from those systems. You can also sign in through the demo account or a local admin account. Support for creating local user accounts is a planned feature.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Self-hosted by design</p>
                        <p>SAFi is designed to be self-hosted. You need a server — either on your private network or in the cloud — to run it. All data, including databases, conversation histories, and logs, stays on your server. The only external interactions are API calls to the AI models.</p>
                        <p class="mt-2">If you need a fully private AI system, you can also self-host the language models and keep your entire setup air-gapped. <strong class="text-gray-900 dark:text-white">DeepSeek</strong> and <strong class="text-gray-900 dark:text-white">Mistral</strong> offer capable open-source models you can host locally. There are also US-based options such as <strong class="text-gray-900 dark:text-white">GPT OSS-120B</strong> that perform well on everyday reasoning tasks.</p>
                    </div>

                    <div class="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-3">
                        <p class="text-green-800 dark:text-green-300 font-medium text-xs">📖 Technical documentation</p>
                        <p class="text-green-700 dark:text-green-400 mt-1">The sections below give you an overview of each SAFi component from a user's perspective. For a technical deep-dive, the README in the <a href="https://github.com/jnamaya/SAFi" target="_blank" rel="noopener" class="underline hover:text-green-600">GitHub repository</a> is a good starting point.</p>
                    </div>

                </div>
            </div>

            <!-- Using SAFi -->
            <div id="help-start" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-teal-100 dark:bg-teal-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Using SAFi</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>Since you are already here, this is how you can test and demo SAFi.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Step 1 — Pick an agent</p>
                        <p>From the chat icon in the sidebar or <strong class="text-gray-900 dark:text-white">Settings → Agents</strong>, browse the available agents. Each card shows the agent's name, purpose, and the policy it follows. Click <strong class="text-gray-900 dark:text-white">Select</strong> on the one you are interested in testing.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Step 2 — Choose the AI model</p>
                        <p>By default, SAFi is set up with the <strong class="text-gray-900 dark:text-white">LLaMA 3.1 8B</strong> model, which is a small model without strong built-in safety layers — it can be jailbroken fairly easily. This is intentional: it lets you test SAFi's governance layer independently of the model's own guardrails. To test whether the agent stays in its lane, this default model works well.</p>
                        <p class="mt-2">If you want to test for response quality and capabilities, switch to <strong class="text-gray-900 dark:text-white">DeepSeek Flash V4</strong> or one of the <strong class="text-gray-900 dark:text-white">Gemini Flash</strong> models — both offer significantly stronger reasoning at low cost.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Step 3 — Send your first message</p>
                        <p>Type a question related to the agent's topic and press <strong class="text-gray-900 dark:text-white">Enter</strong> to send. The agent will respond based on its defined purpose and scope. If your question is outside its scope, it will let you know.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Step 4 — Try attaching a document</p>
                        <p>Click the attachment icon in the chat input and upload a <strong class="text-gray-900 dark:text-white">PDF</strong>, <strong class="text-gray-900 dark:text-white">TXT</strong>, or <strong class="text-gray-900 dark:text-white">DOCX</strong> file. Ask the agent a question about it. SAFi will extract the content and include it in the agent's context.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Step 5 — Check the compliance score</p>
                        <p>After the agent responds, expand the response details to see the compliance score. This shows how well the response aligned with the agent's values and standards. A green score means it passed cleanly — anything lower triggered an automatic retry before you saw the result.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Step 6 — Listen to the response</p>
                        <p>Use the audio playback button on any response to have it read aloud. Useful when reviewing long answers or working hands-free.</p>
                    </div>

                    <div class="bg-gray-50 dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-lg p-3">
                        <p class="text-gray-700 dark:text-gray-300 font-medium text-xs">🛠️ Setting up SAFi for the first time?</p>
                        <p class="text-gray-600 dark:text-gray-400 mt-1">Installation and deployment instructions — including Docker setup — are covered in the <a href="https://github.com/jnamaya/SAFi" target="_blank" rel="noopener" class="text-green-600 dark:text-green-400 underline hover:text-green-500">GitHub repository README</a>. That's the right place to start if you're deploying SAFi for your organization.</p>
                    </div>

                </div>
            </div>

            <!-- Key concepts -->
            <div id="help-concepts" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Key concepts</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-3 text-sm text-gray-600 dark:text-gray-400">

                    <p>These are the core terms you'll encounter throughout SAFi. Understanding them will help you get more out of the platform.</p>

                    <div class="space-y-2">

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Governance Engine</p>
                            <p class="mt-0.5">The engine sitting between the user and the AI model. It enforces the agent's scope, applies the policy, evaluates every response, and blocks or retries anything that doesn't meet the standard — before the user ever sees it.</p>
                        </div>

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Agent</p>
                            <p class="mt-0.5">An AI assistant that does more than generate answers from training data. An agent can gather information from a RAG system, call external tools via MCP, and perform actions — whatever it has been programmed to do. Think of it as a purpose-built AI worker, not just a chatbot.</p>
                        </div>

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Charter</p>
                            <p class="mt-0.5">Your organization's mission and <strong class="text-gray-700 dark:text-gray-300">core values</strong>. The Charter applies to every agent in the organization, so its values are scored on every response — it's the culture all agents share.</p>
                        </div>

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Policy</p>
                            <p class="mt-0.5">A business unit's rulebook. A policy defines the <strong class="text-gray-700 dark:text-gray-300">standards</strong> it holds agents to, plus their scope, required disclaimers, and rules. An agent inherits its scored criteria from the Charter (core values) and its Policy (standards). One policy can govern many agents.</p>
                        </div>

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Purpose &amp; Mandate</p>
                            <p class="mt-0.5">What a policy's agents exist to do and the perspective they reason from — the unit's mission, the objectives it owns, and the orientation it approaches its work with. It is the foundation the agent reasons from, before any specific rules apply.</p>
                        </div>

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Charter vs Policy weighting</p>
                            <p class="mt-0.5">How much of an agent's scored ethics comes from the organization's Charter (core values) versus the business-unit Policy (standards). A higher setting gives the org-wide Charter more weight; a lower setting favors the specific Policy.</p>
                        </div>

                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Ethical Memory</p>
                            <p class="mt-0.5">The memory retention capacity of an agent — how heavily it weighs past interactions when shaping new responses. A higher setting means the agent draws more from conversation history to maintain consistency and context over time.</p>
                        </div>

                    </div>

                </div>
            </div>

            <!-- Using the Chat -->
            <div id="help-chat" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-purple-600 dark:text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Using the Chat</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Chat Interface</p>
                        <p>The chat interface in SAFi is the native way you communicate with your agent. SAFi's backend engine is API-based, so you can use any other interface — such as <strong class="text-gray-900 dark:text-white">Microsoft Teams</strong>, <strong class="text-gray-900 dark:text-white">Slack</strong>, <strong class="text-gray-900 dark:text-white">Telegram</strong>, <strong class="text-gray-900 dark:text-white">WhatsApp</strong>, or any other chat application that supports custom API calls — to communicate with your agent. SAFi supports document extraction for <strong class="text-gray-900 dark:text-white">PDF</strong>, <strong class="text-gray-900 dark:text-white">TXT</strong>, and <strong class="text-gray-900 dark:text-white">DOCX</strong> files, and you can listen to generated answers using the built-in audio playback.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Sending a message</p>
                        <p>Type your message in the input box at the bottom of the screen and press <strong class="text-gray-900 dark:text-white">Enter</strong> or click the send button. The agent will respond based on its defined purpose and scope.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Analyzing Documents</p>
                        <p>You can attach files (like PDFs or text documents) to your messages using the attachment icon. The agent will read the document and analyze it, provided the content falls within the agent's defined scope and expertise.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Cancelling a response</p>
                        <p>While the agent is generating a response, the send button turns <strong class="text-red-600 dark:text-red-400">red</strong> and shows a stop icon. Click it to cancel the current response immediately.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Suggested follow-ups</p>
                        <p>After each response, the agent may suggest follow-up questions to help guide the conversation. Click any suggestion to send it as your next message.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Conversation history</p>
                        <p>Your past conversations are saved and accessible from the left sidebar in the chat view. Click on any conversation to continue where you left off.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Out-of-scope requests</p>
                        <p>If you ask the agent something outside its defined scope, it will politely let you know and redirect the conversation. This is the governance layer doing its job — the agent is staying true to its purpose.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Compliance Audits</p>
                        <p>Each response includes a compliance score indicating how well it aligned with the agent's values and standards. You can view this by expanding the response details. Scores range from excellent to neutral to violation — violations trigger a retry or a redirect.</p>
                    </div>

                </div>
            </div>

            <!-- Agents -->
            <div id="help-agents" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Agents</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>An <strong class="text-gray-900 dark:text-white">Agent</strong> is an AI assistant built for a specific role — its name, purpose, tone, the tools and knowledge it can use, and the model that powers it. An agent does not define its own values; it inherits its scored criteria from your organization's <strong class="text-gray-900 dark:text-white">Charter</strong> (core values) and the <strong class="text-gray-900 dark:text-white">Policy</strong> it's attached to (standards).</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Types of agents</p>
                        <div class="space-y-2">
                            <div class="flex gap-3 bg-gray-50 dark:bg-neutral-800 rounded-lg p-3">
                                <span class="text-lg">🏛️</span>
                                <div>
                                    <p class="font-medium text-gray-900 dark:text-white">Built-in Agents</p>
                                    <p class="mt-0.5">Pre-configured agents that come with the platform (like the Socratic Tutor). These are ready to use immediately.</p>
                                </div>
                            </div>
                            <div class="flex gap-3 bg-gray-50 dark:bg-neutral-800 rounded-lg p-3">
                                <span class="text-lg">✨</span>
                                <div>
                                    <p class="font-medium text-gray-900 dark:text-white">Custom Agents</p>
                                    <p class="mt-0.5">Agents created by your organization's admins using the Agent Wizard. These are built specifically for your team's needs.</p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">How to select an agent</p>
                        <ol class="list-decimal list-inside space-y-1">
                            <li>Open the Settings panel and go to <strong class="text-gray-900 dark:text-white">Agents</strong>.</li>
                            <li>Browse the available agent cards. Each card shows the agent's name, description, and purpose.</li>
                            <li>Click <strong class="text-gray-900 dark:text-white">Select</strong> on the agent you want to use.</li>
                            <li>Return to the chat — your selected agent will be active immediately.</li>
                        </ol>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Creating a custom agent <span class="text-xs font-normal text-gray-400">(Admins & Editors only)</span></p>
                        <p>Click <strong class="text-gray-900 dark:text-white">Create Agent</strong> on the Agents page to open the Agent Wizard. Because values and standards live in the Charter and the Policy, the agent builder focuses on the agent's <em>role</em>:</p>
                        <ul class="list-disc list-inside mt-1 space-y-0.5">
                            <li><strong class="text-gray-900 dark:text-white">Profile</strong> — Name, description, avatar, and the governing <strong class="text-gray-900 dark:text-white">Policy</strong> it's attached to</li>
                            <li><strong class="text-gray-900 dark:text-white">Tools &amp; Knowledge</strong> — Any tools the agent may use and an optional knowledge base</li>
                            <li><strong class="text-gray-900 dark:text-white">Personality</strong> — The AI model that generates its responses</li>
                            <li><strong class="text-gray-900 dark:text-white">Settings</strong> — Operational limits, then a final review</li>
                        </ul>
                        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">An agent needs at least a Charter or an attached Policy — otherwise it has no values or standards to be governed by.</p>
                    </div>

                </div>
            </div>

            <!-- Policies -->
            <div id="help-policies" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-yellow-600 dark:text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Policies</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>A <strong class="text-gray-900 dark:text-white">Policy</strong> is a business unit's rulebook — the <strong class="text-gray-900 dark:text-white">standards</strong>, scope, and rules an agent is held to. Together with your organization's <strong class="text-gray-900 dark:text-white">Charter</strong> (core values), it defines what every response is evaluated against before it reaches you.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">What's in a policy?</p>
                        <div class="space-y-2">
                            <div class="flex gap-2">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Purpose &amp; Mandate</strong> — The purpose, mandate, and perspective every agent under the policy reasons from.</div>
                            </div>
                            <div class="flex gap-2">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Scope</strong> — The topics the agent is allowed to handle; anything outside is declined.</div>
                            </div>
                            <div class="flex gap-2">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Standards</strong> — Specific dimensions a response is scored on (e.g., Accuracy, Data Privacy, Compliance). Each standard has a weight that reflects its importance, and can be marked non-negotiable.</div>
                            </div>
                            <div class="flex gap-2">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Response Rules</strong> — Hard requirements like required disclaimers, prohibited formatting, and permitted tools.</div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Creating and managing policies <span class="text-xs font-normal text-gray-400">(Admins & Editors only)</span></p>
                        <p>Go to <strong class="text-gray-900 dark:text-white">Policies</strong> in the sidebar to view, create, or edit policies. When creating a policy, you can define its standards and rules from scratch or start from the default SAFi template.</p>
                    </div>

                    <div class="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3">
                        <p class="text-yellow-800 dark:text-yellow-300 font-medium text-xs">⚠️ One policy, many agents</p>
                        <p class="text-yellow-700 dark:text-yellow-400 mt-1">A single policy can be assigned to multiple agents. Updating a policy affects all agents that use it, so edit with care.</p>
                    </div>

                </div>
            </div>

            <!-- Organization -->
            <div id="help-org" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-orange-600 dark:text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Organization</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-3 text-sm text-gray-600 dark:text-gray-400">
                    <p>The <strong class="text-gray-900 dark:text-white">Organization</strong> settings are where admins manage the workspace, users, and global AI behavior.</p>
                    <div class="space-y-2">
                        <div class="flex gap-2">
                            <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                            <div><strong class="text-gray-900 dark:text-white">Domain Verification</strong> — Admins can verify a company domain (via TXT record) so anyone with a matching email address automatically joins the workspace.</div>
                        </div>
                        <div class="flex gap-2">
                            <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                            <div><strong class="text-gray-900 dark:text-white">AI Governance</strong> — This is also where you set your organization's <em>Charter</em> (mission + core values). Sliders configure global AI behavior: <em>Charter vs Policy weighting</em> (how much of an agent's scored ethics comes from the Charter vs the business-unit Policy) and <em>Ethical Memory</em> (how heavily the AI weighs past interactions).</div>
                        </div>
                        <div class="flex gap-2">
                            <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                            <div><strong class="text-gray-900 dark:text-white">Members</strong> — View and manage everyone in the workspace, change their roles, or remove them entirely.</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- AI Models -->
            <div id="help-models" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">AI Models</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-3 text-sm text-gray-600 dark:text-gray-400">
                    <p>The <strong class="text-gray-900 dark:text-white">AI Models</strong> page is where admins configure which underlying LLM powers the platform's conversational capabilities.</p>
                    <p>Here, admins select the <strong class="text-gray-900 dark:text-white">Response Generator</strong>. This is the primary model responsible for generating the text you see in the chat. The backend governance layers (the Policy Gatekeeper and Compliance Auditor) operate independently to audit this model's outputs.</p>
                    <p class="text-gray-400 dark:text-gray-500">Model configuration is for admins only. If you're a regular user, the models are already set up and ready to go.</p>
                </div>
            </div>

            <!-- Roles & Permissions -->
            <div id="help-roles" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-pink-100 dark:bg-pink-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-pink-600 dark:text-pink-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Roles & Permissions</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 text-sm text-gray-600 dark:text-gray-400">
                    <p class="mb-3">SAFi uses four roles to control what each person can see and do.</p>
                    <div class="overflow-hidden rounded-lg border border-gray-200 dark:border-neutral-700">
                        <table class="w-full text-sm">
                            <thead>
                                <tr class="bg-gray-50 dark:bg-neutral-800">
                                    <th class="text-left px-4 py-2.5 font-semibold text-gray-900 dark:text-white">Permission</th>
                                    <th class="text-center px-3 py-2.5 font-semibold text-gray-900 dark:text-white">Member</th>
                                    <th class="text-center px-3 py-2.5 font-semibold text-gray-900 dark:text-white">Auditor</th>
                                    <th class="text-center px-3 py-2.5 font-semibold text-gray-900 dark:text-white">Editor</th>
                                    <th class="text-center px-3 py-2.5 font-semibold text-gray-900 dark:text-white">Admin</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100 dark:divide-neutral-700">
                                <tr class="bg-white dark:bg-neutral-900">
                                    <td class="px-4 py-2.5 text-gray-600 dark:text-gray-400">Use the chat & select agents</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                </tr>
                                <tr class="bg-gray-50/50 dark:bg-neutral-800/50">
                                    <td class="px-4 py-2.5 text-gray-600 dark:text-gray-400">View Audit Hub</td>
                                    <td class="text-center px-3 py-2.5 text-gray-300 dark:text-gray-600">—</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                </tr>
                                <tr class="bg-white dark:bg-neutral-900">
                                    <td class="px-4 py-2.5 text-gray-600 dark:text-gray-400">Create & edit agents/policies</td>
                                    <td class="text-center px-3 py-2.5 text-gray-300 dark:text-gray-600">—</td>
                                    <td class="text-center px-3 py-2.5 text-gray-300 dark:text-gray-600">—</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                </tr>
                                <tr class="bg-gray-50/50 dark:bg-neutral-800/50">
                                    <td class="px-4 py-2.5 text-gray-600 dark:text-gray-400">Manage org, models, & users</td>
                                    <td class="text-center px-3 py-2.5 text-gray-300 dark:text-gray-600">—</td>
                                    <td class="text-center px-3 py-2.5 text-gray-300 dark:text-gray-600">—</td>
                                    <td class="text-center px-3 py-2.5 text-gray-300 dark:text-gray-600">—</td>
                                    <td class="text-center px-3 py-2.5 text-green-600">✓</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- FAQ -->
            <div id="help-faq" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-teal-100 dark:bg-teal-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Frequently Asked Questions</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-1" id="faq-list">

                    ${faqItem("Why did the agent refuse my request?",
                        "Agents are scoped to a specific purpose. If your request falls outside that scope, the agent will decline and explain its boundaries. This is intentional — it means the governance layer is working. Try rephrasing your question to stay within the agent's topic area.")}

                    ${faqItem("Why is the agent's response different from what I expected?",
                        "Each response is evaluated against the agent's policy before it's sent to you. If the first draft didn't meet the standard, the agent generates a revised response automatically. What you see is always the version that passed the evaluation.")}

                    ${faqItem("Can I use the same agent for different topics?",
                        "Each agent is designed for a specific purpose, so it works best when you stick to its intended topic area. If you need help with something different, check whether another agent covers that topic or ask your admin about creating a new one.")}

                    ${faqItem("What does the compliance score mean?",
                        "After each response, SAFi scores it against the agent's values and standards on a scale from excellent (+1) to violation (-1). A high score means the response aligned well with the agent's purpose and principles. A low score would have triggered a retry — you only see responses that passed.")}

                    ${faqItem("How do I invite someone to my organization?",
                        "If your organization has verified its domain, users with a matching email address will join automatically when they sign up. You can also review current members in the Organization tab (Admins only).")}

                    ${faqItem("Can I delete a conversation?",
                        "Yes. In the chat view, find the conversation in the left sidebar and use the delete option. Deleted conversations cannot be recovered.")}

                    ${faqItem("What is the Audit Hub?",
                        "The Audit Hub shows a detailed log of all conversations and how each response was evaluated — including the compliance scores and any policy flags. It's designed for transparency and oversight, not for monitoring users.")}

                    ${faqItem("I'm not seeing an option I expect. Why?",
                        "Some features are only visible to certain roles. If you don't see an option like Create Agent, Edit Policy, or Manage Organization, your account may be set to Member or Auditor role. Contact your organization's admin if you believe your access should be different.")}

                </div>
            </div>

            <div class="mt-6 pt-6 border-t border-gray-200 dark:border-neutral-700 text-center text-xs text-gray-400 dark:text-gray-500">
                SAFi — Self-Alignment Framework &nbsp;·&nbsp;
                <a href="https://github.com/jnamaya/SAFi" target="_blank" rel="noopener" class="hover:text-green-500 transition-colors">GitHub</a>
            </div>

        </div>
    `;

    // Wire up section toggles
    container.querySelectorAll('.section-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const body    = btn.nextElementSibling;
            const chevron = btn.querySelector('.section-chevron');
            const hidden  = body.classList.toggle('hidden');
            chevron.style.transform = hidden ? 'rotate(-90deg)' : 'rotate(0deg)';
        });
    });

    // Wire up FAQ toggles
    container.querySelectorAll('.faq-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const body   = btn.closest('.faq-item').querySelector('.faq-body');
            const icon   = btn.querySelector('.faq-icon');
            const hidden = body.classList.toggle('hidden');
            icon.style.transform = hidden ? 'rotate(0deg)' : 'rotate(45deg)';
        });
    });
}

function faqItem(question, answer) {
    return `
        <div class="faq-item border border-gray-200 dark:border-neutral-700 rounded-lg overflow-hidden mb-2">
            <button class="faq-toggle w-full flex items-center justify-between px-4 py-3 text-left bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors">
                <span class="text-sm font-medium text-gray-900 dark:text-white">${question}</span>
                <svg class="faq-icon w-4 h-4 text-gray-400 flex-shrink-0 ml-3 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                </svg>
            </button>
            <div class="faq-body hidden px-4 py-3 text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-neutral-800 border-t border-gray-200 dark:border-neutral-700">
                ${answer}
            </div>
        </div>
    `;
}
