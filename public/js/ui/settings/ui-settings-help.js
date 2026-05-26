/**
 * Help Tab — User-facing guide for SAFi.
 * Written for a general audience: no backend or technical references.
 */

export function renderSettingsHelpTab() {
    const container = document.getElementById('tab-help');
    if (!container) return;

    container.innerHTML = `
        <div class="max-w-3xl">

            <div class="mb-8">
                <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-2">Help & User Guide</h1>
                <p class="text-gray-500 dark:text-gray-400 text-base">Everything you need to know to get the most out of SAFi.</p>
            </div>

            <div class="bg-gray-50 dark:bg-neutral-800 rounded-xl p-4 mb-8 border border-gray-200 dark:border-neutral-700">
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">On this page</p>
                <div class="grid grid-cols-2 gap-1 text-sm">
                    <a href="#help-overview"    class="text-green-600 dark:text-green-400 hover:underline py-0.5">Overview</a>
                    <a href="#help-agents"      class="text-green-600 dark:text-green-400 hover:underline py-0.5">Agents</a>
                    <a href="#help-chat"        class="text-green-600 dark:text-green-400 hover:underline py-0.5">Chat</a>
                    <a href="#help-policies"    class="text-green-600 dark:text-green-400 hover:underline py-0.5">Policies</a>
                    <a href="#help-org"         class="text-green-600 dark:text-green-400 hover:underline py-0.5">Organization</a>
                    <a href="#help-models"      class="text-green-600 dark:text-green-400 hover:underline py-0.5">AI Models</a>
                    <a href="#help-roles"       class="text-green-600 dark:text-green-400 hover:underline py-0.5">Roles & Permissions</a>
                    <a href="#help-faq"         class="text-green-600 dark:text-green-400 hover:underline py-0.5">FAQ</a>
                </div>
            </div>

            <div id="help-overview" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">What is SAFi?</h2>
                </div>
                <div class="pl-11 space-y-3 text-base text-gray-600 dark:text-gray-400">
                    <p>SAFi (Self-Alignment Framework Interface) is the governance engine powering this application. It acts as a strict safety layer between you and the AI agents.</p>
                    <p>Rather than hoping an agent behaves appropriately, SAFi structurally forces it to follow a specific set of rules and values. This ensures the agents are reliable, stay strictly on-topic, and actively prevent the generation of harmful or unauthorized content.</p>
                    <div class="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-3 mt-2">
                        <p class="text-green-800 dark:text-green-300 font-medium text-xs">💡 Good to know</p>
                        <p class="text-green-700 dark:text-green-400 text-sm mt-1">If an agent refuses a request or redirects the conversation, it is because SAFi’s safety layer detected a rule violation. This protects the integrity of the workspace.</p>
                    </div>
                </div>
            </div>

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-agents" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Agents</h2>
                </div>
                <div class="pl-11 space-y-4 text-base text-gray-600 dark:text-gray-400">
                    <p>An <strong class="text-gray-900 dark:text-white">Agent</strong> is an AI assistant designed for a specific purpose. Each agent has a name, a description, a defined scope, and a set of values that guide how it responds.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Types of agents</p>
                        <div class="space-y-2">
                            <div class="flex gap-3 bg-gray-50 dark:bg-neutral-800 rounded-lg p-3">
                                <span class="text-lg">🏛️</span>
                                <div>
                                    <p class="font-medium text-gray-900 dark:text-white text-sm">Built-in Agents</p>
                                    <p class="text-sm mt-0.5">Pre-configured agents that come with the platform (like the Socratic Tutor). These are ready to use immediately.</p>
                                </div>
                            </div>
                            <div class="flex gap-3 bg-gray-50 dark:bg-neutral-800 rounded-lg p-3">
                                <span class="text-lg">✨</span>
                                <div>
                                    <p class="font-medium text-gray-900 dark:text-white text-sm">Custom Agents</p>
                                    <p class="text-sm mt-0.5">Agents created by your organization's admins using the Agent Wizard. These are built specifically for your team's needs.</p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">How to select an agent</p>
                        <ol class="list-decimal list-inside space-y-1 text-sm">
                            <li>Open the Settings panel and go to <strong class="text-gray-900 dark:text-white">Agents</strong>.</li>
                            <li>Browse the available agent cards. Each card shows the agent's name, description, and its core values.</li>
                            <li>Click <strong class="text-gray-900 dark:text-white">Select</strong> on the agent you want to use.</li>
                            <li>Return to the chat — your selected agent will be active immediately.</li>
                        </ol>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Creating a custom agent <span class="text-xs font-normal text-gray-400">(Admins & Editors only)</span></p>
                        <p class="text-sm">Click <strong class="text-gray-900 dark:text-white">Create Agent</strong> on the Agents page to open the Agent Wizard. You'll be guided through:</p>
                        <ul class="list-disc list-inside text-sm mt-1 space-y-0.5">
                            <li><strong class="text-gray-900 dark:text-white">Identity</strong> — Name, description, and avatar</li>
                            <li><strong class="text-gray-900 dark:text-white">Purpose</strong> — What the agent is for and what topics it covers</li>
                            <li><strong class="text-gray-900 dark:text-white">Values</strong> — The principles the agent is evaluated against</li>
                            <li><strong class="text-gray-900 dark:text-white">Guardrails</strong> — Specific rules and boundaries for the agent's behavior</li>
                            <li><strong class="text-gray-900 dark:text-white">Policy</strong> — The governance policy that governs the agent</li>
                        </ul>
                    </div>
                </div>
            </div>

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-chat" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-purple-600 dark:text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Using the Chat</h2>
                </div>
                <div class="pl-11 space-y-4 text-base text-gray-600 dark:text-gray-400">

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Sending a message</p>
                        <p class="text-sm">Type your message in the input box at the bottom of the screen and press <strong class="text-gray-900 dark:text-white">Enter</strong> or click the send button. The agent will respond based on its defined purpose and values.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Analyzing Documents</p>
                        <p class="text-sm">You can attach files (like PDFs or text documents) to your messages using the attachment icon. The agent will read the document and analyze it, provided the content falls within the agent's defined scope and expertise.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Cancelling a response</p>
                        <p class="text-sm">While the agent is generating a response, the send button turns <strong class="text-red-600 dark:text-red-400">red</strong> and shows a stop icon. Click it to cancel the current response immediately.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Suggested follow-ups</p>
                        <p class="text-sm">After each response, the agent may suggest follow-up questions to help guide the conversation. Click any suggestion to send it as your next message.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Conversation history</p>
                        <p class="text-sm">Your past conversations are saved and accessible from the left sidebar in the chat view. Click on any conversation to continue where you left off.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Out-of-scope requests</p>
                        <p class="text-sm">If you ask the agent something outside its defined scope, it will politely let you know and redirect the conversation. This is the governance layer doing its job — the agent is staying true to its purpose.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Compliance Audits</p>
                        <p class="text-sm">Each response includes a compliance score indicating how well it aligned with the agent's values. You can view this by expanding the response details. Scores range from excellent to neutral to violation — violations trigger a retry or a redirect.</p>
                    </div>
                </div>
            </div>

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-policies" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-yellow-600 dark:text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Policies</h2>
                </div>
                <div class="pl-11 space-y-4 text-base text-gray-600 dark:text-gray-400">
                    <p>A <strong class="text-gray-900 dark:text-white">Policy</strong> is the set of values, rules, and principles that an agent is held to. Every agent is linked to a policy, and every response is evaluated against it before it reaches you.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">What's in a policy?</p>
                        <div class="space-y-2">
                            <div class="flex gap-2 text-sm">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Worldview</strong> — A description of the principles that should guide every response.</div>
                            </div>
                            <div class="flex gap-2 text-sm">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Values</strong> — Specific dimensions the agent is scored on (e.g., Accuracy, Integrity, Safety). Each value has a weight that reflects its importance.</div>
                            </div>
                            <div class="flex gap-2 text-sm">
                                <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                                <div><strong class="text-gray-900 dark:text-white">Rules</strong> — Hard lines the agent will never cross, regardless of how a request is framed.</div>
                            </div>
                        </div>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Creating and managing policies <span class="text-xs font-normal text-gray-400">(Admins & Editors only)</span></p>
                        <p class="text-sm">Go to <strong class="text-gray-900 dark:text-white">Policies</strong> in the sidebar to view, create, or edit policies. When creating a policy, you can define its values and rules from scratch or start from the default SAFi template.</p>
                    </div>

                    <div class="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3">
                        <p class="text-yellow-800 dark:text-yellow-300 font-medium text-xs">⚠️ One policy, many agents</p>
                        <p class="text-yellow-700 dark:text-yellow-400 text-sm mt-1">A single policy can be assigned to multiple agents. Updating a policy affects all agents that use it, so edit with care.</p>
                    </div>
                </div>
            </div>

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-org" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-orange-600 dark:text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Organization</h2>
                </div>
                <div class="pl-11 space-y-3 text-base text-gray-600 dark:text-gray-400">
                    <p>The <strong class="text-gray-900 dark:text-white">Organization</strong> settings are where admins manage the workspace, users, and global AI behavior.</p>
                    <div class="space-y-2 text-sm">
                        <div class="flex gap-2">
                            <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                            <div><strong class="text-gray-900 dark:text-white">Domain Verification</strong> — Admins can verify a company domain (via TXT record) so anyone with a matching email address automatically joins the workspace.</div>
                        </div>
                        <div class="flex gap-2">
                            <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                            <div><strong class="text-gray-900 dark:text-white">AI Governance</strong> — Sliders to configure global AI behavior. You can adjust the <em>Organizational Authority</em> (Agent Autonomy vs. Strict Compliance) and <em>Ethical Memory</em> (how heavily the AI weighs past interactions).</div>
                        </div>
                        <div class="flex gap-2">
                            <span class="text-green-600 dark:text-green-400 font-bold mt-0.5">→</span>
                            <div><strong class="text-gray-900 dark:text-white">Members</strong> — View and manage everyone in the workspace, change their roles, or remove them entirely.</div>
                        </div>
                    </div>
                </div>
            </div>

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-models" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-indigo-600 dark:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">AI Models</h2>
                </div>
                <div class="pl-11 space-y-3 text-base text-gray-600 dark:text-gray-400">
                    <p>The <strong class="text-gray-900 dark:text-white">AI Models</strong> page is where admins configure which underlying LLM powers the platform's conversational capabilities.</p>
                    <p class="text-sm">Here, admins select the <strong>Response Generator</strong>. This is the primary model responsible for generating the text you see in the chat. The backend governance layers (the Policy Gatekeeper and Compliance Auditor) operate independently to audit this model's outputs.</p>
                    <p class="text-sm text-gray-400">Model configuration is for admins only. If you're a regular user, the models are already set up and ready to go.</p>
                </div>
            </div>

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-roles" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-pink-100 dark:bg-pink-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-pink-600 dark:text-pink-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Roles & Permissions</h2>
                </div>
                <div class="pl-11 text-base text-gray-600 dark:text-gray-400">
                    <p class="mb-3 text-sm">SAFi uses four roles to control what each person can see and do.</p>
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

            <hr class="border-gray-200 dark:border-neutral-700 mb-10">

            <div id="help-faq" class="mb-10 scroll-mt-4">
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-8 h-8 rounded-lg bg-teal-100 dark:bg-teal-900/30 flex items-center justify-center flex-shrink-0">
                        <svg class="w-4 h-4 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-gray-900 dark:text-white">Frequently Asked Questions</h2>
                </div>
                <div class="pl-11 space-y-1" id="faq-list">

                    ${faqItem("Why did the agent refuse my request?",
                        "Agents are scoped to a specific purpose. If your request falls outside that scope, the agent will decline and explain its boundaries. This is intentional — it means the governance layer is working. Try rephrasing your question to stay within the agent's topic area.")}

                    ${faqItem("Why is the agent's response different from what I expected?",
                        "Each response is evaluated against the agent's policy before it's sent to you. If the first draft didn't meet the standard, the agent generates a revised response automatically. What you see is always the version that passed the evaluation.")}

                    ${faqItem("Can I use the same agent for different topics?",
                        "Each agent is designed for a specific purpose, so it works best when you stick to its intended topic area. If you need help with something different, check whether another agent covers that topic or ask your admin about creating a new one.")}

                    ${faqItem("What does the compliance score mean?",
                        "After each response, SAFi scores it against the agent's values on a scale from excellent (+1) to violation (-1). A high score means the response aligned well with the agent's purpose and principles. A low score would have triggered a retry — you only see responses that passed.")}

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

            <div class="mt-4 pt-6 border-t border-gray-200 dark:border-neutral-700 text-center text-xs text-gray-400 dark:text-gray-500">
                SAFi — Self-Alignment Framework &nbsp;·&nbsp;
                <a href="https://github.com/jnamaya/SAFi" target="_blank" rel="noopener" class="hover:text-green-500 transition-colors">GitHub</a>
            </div>

        </div>
    `;

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
                <span class="text-base font-medium text-gray-900 dark:text-white">${question}</span>
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