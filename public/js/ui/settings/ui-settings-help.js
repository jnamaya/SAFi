/**
 * Help Tab. A user guide, deliberately scoped to what a signed-in user can
 * actually do in the product (backlog 56). Product positioning, deployment,
 * and admin walkthroughs live in the GitHub docs, not here: a member reading
 * this page should never hit a section they cannot act on. The one exception
 * is the short "for administrators" pointer at the bottom.
 */

export function renderSettingsHelpTab() {
    const container = document.getElementById('tab-help');
    if (!container) return;

    container.innerHTML = `
        <div class="max-w-3xl">

            <div class="settings-page-header">
                <h1>Help &amp; User Guide</h1>
                <p>How to work with your agents, and what the scores and labels mean.</p>
            </div>

            <div class="bg-gray-50 dark:bg-neutral-800 rounded-xl p-4 mb-6 border border-gray-200 dark:border-neutral-700">
                <p class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">On this page</p>
                <div class="grid grid-cols-2 gap-1 text-sm">
                    <a href="#help-start"     class="text-green-600 dark:text-green-400 hover:underline py-0.5">Getting started</a>
                    <a href="#help-agents"    class="text-green-600 dark:text-green-400 hover:underline py-0.5">Agents</a>
                    <a href="#help-score"     class="text-green-600 dark:text-green-400 hover:underline py-0.5">The alignment score</a>
                    <a href="#help-chat"      class="text-green-600 dark:text-green-400 hover:underline py-0.5">Conversations</a>
                    <a href="#help-schedules" class="text-green-600 dark:text-green-400 hover:underline py-0.5">Scheduled updates</a>
                    <a href="#help-memory"    class="text-green-600 dark:text-green-400 hover:underline py-0.5">Agent memory</a>
                    <a href="#help-roles"     class="text-green-600 dark:text-green-400 hover:underline py-0.5">Roles</a>
                    <a href="#help-faq"       class="text-green-600 dark:text-green-400 hover:underline py-0.5">FAQ</a>
                </div>
            </div>

            <!-- Getting started: starts open -->
            <div id="help-start" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Getting started</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>You talk to SAFi through <strong class="text-gray-900 dark:text-white">agents</strong>: assistants your organization has set up for specific jobs. Every answer an agent gives is checked against your organization's values and standards before it reaches you.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Pick an agent</p>
                        <p>Open the <strong class="text-gray-900 dark:text-white">+</strong> menu next to the message box and choose an agent, or browse the cards under <strong class="text-gray-900 dark:text-white">Control Panel → Agents</strong>. The agent you pick stays active until you switch, and switching starts a new conversation.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Send a message</p>
                        <p>Type your question and press <strong class="text-gray-900 dark:text-white">Enter</strong>. While the agent is answering, the send button turns red; click it to stop the response.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Attach a document</p>
                        <p>Use the attachment icon to add a <strong class="text-gray-900 dark:text-white">PDF</strong>, <strong class="text-gray-900 dark:text-white">DOCX</strong>, <strong class="text-gray-900 dark:text-white">XLSX</strong>, <strong class="text-gray-900 dark:text-white">CSV</strong>, <strong class="text-gray-900 dark:text-white">TXT</strong> or <strong class="text-gray-900 dark:text-white">Markdown</strong> file, then ask about it. The agent reads the content as part of your message.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Listen instead of reading</p>
                        <p>Every response has an audio playback button. Useful for long answers or working hands-free.</p>
                    </div>

                </div>
            </div>

            <!-- Agents -->
            <div id="help-agents" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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

                    <p>Each agent is built for a specific purpose: a topic it knows, a tone it keeps, and boundaries it respects. Use the <strong class="text-gray-900 dark:text-white">Details</strong> button on an agent's card to see what it is for and which standards it answers under.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Staying in scope</p>
                        <p>If you ask something outside an agent's purpose, it will decline and say so. That is intentional: the agent is staying true to its job, not malfunctioning. For a different topic, switch to an agent that covers it.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Agents shared with you</p>
                        <p>Some agents reach you because a colleague shared them with you directly or with a group you belong to. They carry a <strong class="text-gray-900 dark:text-white">Shared with you</strong> label in the agent picker. If one disappears, the share was removed; ask the person who shared it.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Sharing your own agents</p>
                        <p>If you created an agent, the <strong class="text-gray-900 dark:text-white">Share</strong> button on its card lets you give people or groups in your organization access to use it. Sharing never allows editing.</p>
                    </div>

                </div>
            </div>

            <!-- The alignment score -->
            <div id="help-score" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">The alignment score</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>Every response is evaluated against the agent's values and standards, and the result shows on a chip under the answer. Expand the response details to see the value-by-value breakdown.</p>

                    <div class="space-y-2">
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Aligned</p>
                            <p class="mt-0.5">The response met the agent's standards.</p>
                        </div>
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Caution and Concern</p>
                            <p class="mt-0.5">The response fell short on one or more values. This is not an error. It is the system's honest mark on the answer you were given: read the breakdown to see where it fell short.</p>
                        </div>
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Audit pending</p>
                            <p class="mt-0.5">The evaluation is still running. The chip updates when it finishes.</p>
                        </div>
                    </div>

                    <p>Requests that breach the agent's scope or a non-negotiable standard are stopped before they reach you. A low score works differently: the agent is asked to correct itself first, and if the corrected draft is no better, you get the original answer with its real score rather than no answer at all.</p>

                </div>
            </div>

            <!-- Conversations -->
            <div id="help-chat" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Conversations</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">History</p>
                        <p>Past conversations live in the left sidebar. Click one to continue where you left off. You can rename or pin a conversation from its menu, and organize related conversations into projects.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Deleting</p>
                        <p>Delete a conversation from its menu in the sidebar. Deleted conversations cannot be recovered.</p>
                    </div>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Saving content</p>
                        <p>Use the save option on a response to keep it in your saved content, so you can find it later without scrolling through history.</p>
                    </div>

                </div>
            </div>

            <!-- Scheduled updates -->
            <div id="help-schedules" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Scheduled updates</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>An agent can run a prompt for you on a schedule: a morning briefing, daily readings, a weekly summary. The result is emailed to your account address and also appears in your conversation history.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Setting one up</p>
                        <ol class="list-decimal list-inside space-y-1">
                            <li>Go to <strong class="text-gray-900 dark:text-white">Scheduled Updates</strong> in the Control Panel.</li>
                            <li>Pick the agent and write the prompt it should run.</li>
                            <li>Choose the time, the days of the week, and your timezone.</li>
                        </ol>
                        <p class="mt-2">You can pause, edit, or delete a schedule at any time. Delivery goes only to the email on your own account. If the page says email is not configured, ask your administrator.</p>
                    </div>

                </div>
            </div>

            <!-- Agent memory -->
            <div id="help-memory" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Agent memory</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-4 text-sm text-gray-600 dark:text-gray-400">

                    <p>Some agents keep short working notes about what you are working on together, so you do not have to repeat context in every conversation.</p>

                    <div>
                        <p class="font-medium text-gray-900 dark:text-white mb-2">Seeing and deleting it</p>
                        <p>Go to <strong class="text-gray-900 dark:text-white">My Profile</strong> and open the <strong class="text-gray-900 dark:text-white">Agent Memory</strong> section. It shows, per agent, exactly what is remembered, with timestamps. You can delete individual items or everything an agent remembers about you.</p>
                        <p class="mt-2">Deleting is forward-looking: the agent stops using the memory from that point on. Past audit records keep what the agent saw at the time, which is what makes them trustworthy as records.</p>
                    </div>

                </div>
            </div>

            <!-- Roles -->
            <div id="help-roles" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                            </svg>
                        </div>
                        <h2 class="text-base font-semibold text-gray-900 dark:text-white">Roles</h2>
                    </div>
                    <svg class="section-chevron w-5 h-5 text-gray-400 flex-shrink-0 transition-transform duration-200" style="transform: rotate(-90deg)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </button>
                <div class="section-body hidden px-5 pb-5 pt-4 border-t border-gray-200 dark:border-neutral-700 space-y-3 text-sm text-gray-600 dark:text-gray-400">

                    <p>What you can see and do depends on your role in the organization.</p>

                    <div class="space-y-2">
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Member</p>
                            <p class="mt-0.5">Chat with agents, manage your own conversations, schedules, and memory.</p>
                        </div>
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Auditor</p>
                            <p class="mt-0.5">Everything a member has, plus read-only oversight: the Audit Hub and compliance views.</p>
                        </div>
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Editor</p>
                            <p class="mt-0.5">Builds and edits agents and policies.</p>
                        </div>
                        <div class="bg-gray-50 dark:bg-neutral-800 rounded-lg px-4 py-3">
                            <p class="font-medium text-gray-900 dark:text-white">Admin</p>
                            <p class="mt-0.5">Manages the organization: members, groups, models, and settings.</p>
                        </div>
                    </div>

                    <p>If an option you expect is missing (Create Agent, Edit Policy, Organization settings), your role likely does not include it. Ask your organization's admin.</p>

                </div>
            </div>

            <!-- FAQ -->
            <div id="help-faq" class="scroll-mt-4 border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden mb-3">
                <button class="section-toggle w-full flex items-center justify-between px-5 py-4 bg-white dark:bg-neutral-900 hover:bg-gray-50 dark:hover:bg-neutral-800 transition-colors text-left">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center flex-shrink-0">
                            <svg class="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                        "Agents are scoped to a specific purpose. If your request falls outside that scope, the agent declines and explains its boundaries. That is the governance layer working as intended. Try rephrasing within the agent's topic, or switch to an agent that covers yours.")}

                    ${faqItem("What does the alignment score mean?",
                        "Every response is scored against the agent's values and standards. Aligned means it met them; Caution or Concern means it fell short somewhere, and the expanded details show exactly where. The score always describes the answer you actually received.")}

                    ${faqItem("Someone shared an agent with me. Where do I find it?",
                        "Shared agents appear in your agent picker with a 'Shared with you' label, alongside your own agents. If it is missing, the share may have been removed, or it was shared with a group you are no longer in.")}

                    ${faqItem("Can I delete a conversation?",
                        "Yes. Find it in the left sidebar and use the delete option in its menu. Deleted conversations cannot be recovered.")}

                    ${faqItem("I'm not seeing an option I expect. Why?",
                        "Some features are only visible to certain roles. If you don't see Create Agent, Edit Policy, or Organization settings, your account is likely a Member or Auditor. Contact your organization's admin if you believe your access should be different.")}

                </div>
            </div>

            <!-- Admin pointer: the one non-user item, kept to three lines -->
            <div class="bg-gray-50 dark:bg-neutral-800 border border-gray-200 dark:border-neutral-700 rounded-xl p-4 mt-6">
                <p class="text-gray-700 dark:text-gray-300 font-medium text-sm">For administrators and editors</p>
                <p class="text-gray-600 dark:text-gray-400 text-sm mt-1">Building agents and policies, organization setup, models, and deployment are covered in the technical documentation in the <a href="https://github.com/jnamaya/SAFi" target="_blank" rel="noopener" class="text-green-600 dark:text-green-400 underline hover:text-green-500">GitHub repository</a>.</p>
            </div>

            <div class="mt-6 pt-6 border-t border-gray-200 dark:border-neutral-700 text-center text-xs text-gray-400 dark:text-gray-500">
                SAFi &nbsp;&middot;&nbsp;
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
