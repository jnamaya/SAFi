import * as ui from './../ui.js';
import * as api from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';

export function renderSuccessStep(container, policyData, generatedCredentials) {
    if (!generatedCredentials) {
        container.innerHTML = `<div class="text-red-500 text-center">Error: No credentials returned.</div>`;
        return;
    }

    const { policy_id, api_key } = generatedCredentials;

    // Comes from the server (Config.WEB_BASE_URL), never hardcoded and never
    // window.location.origin: the mobile shell serves from capacitor://localhost,
    // which is not an address any bot can post to. The fallback is only for a
    // response predating this field.
    const endpointUrl = generatedCredentials.endpoint_url
        || `${window.location.origin}/api/bot/process_prompt`;
    // Correct-but-unreachable is the confusing case worth naming out loud.
    const isLocal = generatedCredentials.is_public_url === false;

    const isMasked = api_key.includes('*');

    container.innerHTML = `
        <div class="text-center py-8">
            <div class="w-20 h-20 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-6">
                <svg class="w-10 h-10 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h2 class="text-3xl font-bold mb-2 text-gray-900 dark:text-white">Policy Active!</h2>
            <p class="text-gray-500 text-lg">Your governance firewall is ready.</p>
        </div>

        <div class="bg-gray-50 dark:bg-neutral-800 p-6 rounded-xl border border-gray-200 dark:border-neutral-700 text-left">
            <h4 class="font-bold text-lg mb-4 text-gray-800 dark:text-gray-200">Integration Credentials</h4>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-4">
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">Endpoint</label>
                    <code class="block p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-xs truncate text-gray-600 dark:text-gray-300" title="${escapeHtml(endpointUrl)}">${escapeHtml(endpointUrl)}</code>
                    ${isLocal ? `
                    <p class="text-xs text-amber-600 dark:text-amber-400 mt-1">
                        This is a local address. It is correct for testing from
                        this machine, but Teams and Slack call in from the
                        internet and cannot reach it — see step 3 below.
                    </p>` : ''}
                </div>
                <div>
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">API Key</label>
                    <div class="flex gap-2">
                        <code id="display-api-key" class="flex-1 p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-sm text-green-600 font-bold truncate">${api_key}</code>
                        <button id="btn-copy-key" class="px-3 bg-gray-200 hover:bg-gray-300 dark:bg-neutral-700 dark:hover:bg-neutral-600 rounded text-black dark:text-white font-bold transition-colors">Copy</button>
                        <button id="btn-rotate-key" class="px-3 bg-red-100 hover:bg-red-200 text-red-700 rounded font-bold transition-colors text-xs" title="Generate a new key (Old one stops working)">Rotate</button>
                    </div>
                    ${isMasked ? '<p id="key-warning" class="text-xs text-red-500 mt-1 font-bold">⚠️ Key is hidden. If lost, click Rotate to generate a new one.</p>' : ''}
                </div>
            </div>
            
        <div class="mt-8 space-y-6">
             <!-- STEP 1 — attach an agent. The only required step; everything
                  below is optional integration. -->
             <div class="bg-green-50 dark:bg-green-900/10 p-5 rounded-xl border border-green-200 dark:border-green-800">
                 <h4 class="font-bold text-green-900 dark:text-green-100 flex items-center gap-2">
                     <span class="w-6 h-6 rounded-full bg-green-600 text-white text-xs flex items-center justify-center font-bold shrink-0">1</span>
                     Attach an agent — required
                 </h4>
                 <p class="text-sm text-green-800 dark:text-green-200 mt-2">
                     A policy governs nothing until an agent uses it. Nothing else
                     on this page is needed to start.
                 </p>
                 <ol class="list-decimal list-outside ml-5 text-sm text-green-700 dark:text-green-300 mt-2 space-y-1">
                     <li>Go to <strong>Agents</strong> and create one, or edit an existing one.</li>
                     <li>In <strong>step 1</strong>, choose this policy: <code class="font-mono text-xs bg-white/60 dark:bg-black/30 px-1 rounded">${escapeHtml(policy_id)}</code></li>
                     <li>In <strong>step 2</strong>, pick its tools and knowledge base — this policy decides what is on offer there.</li>
                     <li>Chat with the agent. Every turn is scored against this policy's standards and appears in the <strong>Audit Hub</strong>.</li>
                 </ol>
                 <p class="text-xs text-green-700/80 dark:text-green-300/80 mt-3">
                     Editing the policy later re-governs every agent using it, on their next turn. No need to touch the agents again.
                 </p>
             </div>

             <!-- STEP 2 — the fastest possible proof the key works. This was
                  missing, and it is the check that isolates "my credentials are
                  wrong" from "my bot framework is wrong". -->
             <div class="border border-gray-200 dark:border-neutral-700 rounded-xl p-5">
                 <h4 class="font-bold text-gray-800 dark:text-gray-200 flex items-center gap-2">
                     <span class="w-6 h-6 rounded-full bg-gray-600 text-white text-xs flex items-center justify-center font-bold shrink-0">2</span>
                     Test the endpoint — 30 seconds
                 </h4>
                 <p class="text-sm text-gray-600 dark:text-gray-400 mt-2">
                     Run this before wiring up any chat platform. If it returns a
                     governed answer, your endpoint and key are correct and
                     anything that fails afterwards is on the platform side.
                 </p>
                 <div class="mt-3 rounded-lg overflow-hidden border border-gray-200 dark:border-neutral-700">
                     <div class="flex justify-end p-2 bg-[#2d2d2d]">
                         <button id="btn-copy-curl" class="text-xs text-gray-300 hover:text-white px-2 py-1 bg-white/10 rounded">Copy</button>
                     </div>
                     <pre id="curl-content" class="p-4 text-xs font-mono text-gray-300 bg-[#1e1e1e] whitespace-pre overflow-x-auto">curl -X POST ${escapeHtml(endpointUrl)} \\
  -H "X-API-KEY: ${escapeHtml(api_key)}" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "What are you allowed to help with?",
       "user_id": "test-user",
       "conversation_id": "test-1"}'</pre>
                 </div>
                 <ul class="text-xs text-gray-500 dark:text-gray-400 mt-3 space-y-1 list-disc list-outside ml-4">
                     <li><strong>200</strong> with a <code class="font-mono">finalOutput</code> field — working.</li>
                     <li><strong>401</strong> — the key is wrong, or was rotated after you copied it.</li>
                     <li><strong>Connection refused</strong> — SAFi is not reachable at that address from where you ran the command.</li>
                 </ul>
                 ${isMasked ? `
                 <p data-masked-notice class="text-xs text-amber-600 dark:text-amber-400 mt-2">
                     The key above is masked because it was created earlier and is
                     only shown once. Click <strong>Rotate</strong> to get a usable one.
                 </p>` : ''}
             </div>

             <!-- STEP 3 — platform integration. Prerequisites first: the
                  original guide handed over a Python file with no mention that
                  it needs a public HTTPS address and an Azure registration,
                  which is where people actually got stuck. -->
             <div class="border border-gray-200 dark:border-neutral-700 rounded-xl p-5">
                 <h4 class="font-bold text-gray-800 dark:text-gray-200 flex items-center gap-2">
                     <span class="w-6 h-6 rounded-full bg-gray-600 text-white text-xs flex items-center justify-center font-bold shrink-0">3</span>
                     Connect a chat platform — optional
                 </h4>
                 <p class="text-sm text-gray-600 dark:text-gray-400 mt-2">
                     Any client that can POST JSON works — the bot code below is one
                     example, not a requirement. Before you start, you need:
                 </p>
                 <ul class="text-sm text-gray-600 dark:text-gray-400 mt-2 space-y-1 list-disc list-outside ml-5">
                     <li>Somewhere to host the bot that Microsoft can reach over <strong>HTTPS</strong> — it is a separate service from SAFi.</li>
                     <li>An <strong>Azure Bot</strong> registration, for the app ID and password the code expects.</li>
                     <li>${isLocal
                        ? `A publicly reachable SAFi. Yours is currently at a local
                           address, so the bot cannot call it from Azure — put SAFi
                           behind a domain, or use a tunnel such as
                           <code class="font-mono text-xs">ngrok</code> while testing.`
                        : `Your SAFi endpoint, already public: <code class="font-mono text-xs">${escapeHtml(endpointUrl)}</code>`}</li>
                 </ul>
                 <p class="text-xs text-gray-500 dark:text-gray-400 mt-3">
                     Keep the key in an environment variable in real deployments —
                     it is inlined below only so the snippet runs as-is.
                     <strong>Set <code class="font-mono">SAFI_PERSONA</code> to your own agent's key</strong>;
                     the placeholder is a built-in demo agent that may not exist on your install.
                 </p>
             </div>

             <!-- Teams Integration Code -->
             <div class="border border-gray-200 dark:border-neutral-700 rounded-xl overflow-hidden">
                 <button class="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-neutral-800 hover:bg-gray-100 dark:hover:bg-neutral-700 transition-colors" onclick="document.getElementById('teams-code-block').classList.toggle('hidden')">
                     <span class="font-bold text-gray-700 dark:text-gray-200 flex items-center gap-2">
                        <svg class="w-5 h-5 text-[#464EB8]" fill="currentColor" viewBox="0 0 24 24"><path d="M12.5 12a.5.5 0 011 0v3.5a.5.5 0 01-1 0V12zm-3 0a.5.5 0 011 0v3.5a.5.5 0 01-1 0V12zm6 0a.5.5 0 011 0v3.5a.5.5 0 01-1 0V12z" /><path fill-rule="evenodd" d="M2.203 5.488A2.003 2.003 0 014.12 4h15.76a2.003 2.003 0 011.917 1.488l.006.024.004.024C23.006 8.526 21.6 13.905 17.062 17.5a2.004 2.004 0 01-1.25.438H8.188a2.004 2.004 0 01-1.25-.438C2.4 13.905.994 8.526 1.193 5.536l.004-.024.006-.024zm9.797 4.012a4.5 4.5 0 100 9 4.5 4.5 0 000-9z" /></svg>
                        Microsoft Teams Bot Example (Python)
                     </span>
                     <svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                 </button>
                 <div id="teams-code-block" class="hidden border-t border-gray-200 dark:border-neutral-700 bg-[#1e1e1e]">
                     <div class="flex justify-end p-2 bg-[#2d2d2d] border-b border-[#3e3e3e]">
                         <button id="btn-copy-code" class="text-xs text-gray-300 hover:text-white px-2 py-1 bg-white/10 rounded">Copy Code</button>
                     </div>
                     <pre id="py-code-content" class="p-4 text-xs font-mono text-gray-300 whitespace-pre overflow-x-auto max-h-96">import os
import sys
import traceback
import aiohttp
from http import HTTPStatus
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, ActivityTypes

# --- Configuration ---
APP_ID = os.environ.get("MicrosoftAppId", "")
APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
APP_TENANT_ID = os.environ.get("MicrosoftAppTenantId", None)

# SAFI CONFIGURATION (Auto-Generated)
SAFI_API_URL = os.environ.get("SAFI_API_URL", "${escapeHtml(endpointUrl)}")
SAFI_BOT_SECRET = os.environ.get("SAFI_BOT_SECRET", "${escapeHtml(api_key)}")

# CHANGE THIS to your own agent's key (Agents tab -> the agent -> its key).
# "fiduciary" is a built-in demo agent and may not be enabled on this install,
# in which case every message comes back as an unknown-persona error.
SAFI_PERSONA = os.environ.get("SAFI_PERSONA", "fiduciary")

app = Flask(__name__)
settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD, channel_auth_tenant=APP_TENANT_ID)
adapter = BotFrameworkAdapter(settings)

async def on_error(context: TurnContext, error: Exception):
    print(f"\\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()
    await context.send_activity("The bot encountered an error or bug.")
adapter.on_turn_error = on_error

class SafiTeamsBot:
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.type == ActivityTypes.message:
            user_text = turn_context.activity.text
            if turn_context.activity.recipient:
                user_text = user_text.replace(f"&lt;at&gt;{turn_context.activity.recipient.name}&lt;/at&gt;", "").strip()
            
            payload = {
                "message": user_text,
                "user_id": turn_context.activity.from_property.id,
                "conversation_id": turn_context.activity.conversation.id,
                "persona": SAFI_PERSONA 
            }
            
            headers = { "X-API-KEY": SAFI_BOT_SECRET, "Content-Type": "application/json" }
            await turn_context.send_activity(Activity(type=ActivityTypes.typing))
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(SAFI_API_URL, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            await turn_context.send_activity(data.get("finalOutput", "[Error: No output]"))
                        else:
                            await turn_context.send_activity(f"Safi Error ({resp.status}): {await resp.text()}")
            except Exception as e:
                await turn_context.send_activity(f"Connection error: {str(e)}")

        elif turn_context.activity.type == ActivityTypes.conversation_update:
            for member in turn_context.activity.members_added:
                if member.id != turn_context.activity.recipient.id:
                    await turn_context.send_activity("Hello! I am your AI Assistant.")

bot = SafiTeamsBot()

@app.route("/api/messages", methods=["POST"])
def messages():
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
    else:
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")
    
    # Run async loop for Flask
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task = adapter.process_activity(activity, auth_header, bot.on_turn)
        loop.run_until_complete(task)
        return Response(status=HTTPStatus.OK)
    except Exception as e:
        traceback.print_exc()
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

if __name__ == "__main__":
    app.run(debug=True, port=3978)</pre>
                 </div>
             </div>
        </div>

        <div class="mt-8 pt-6 border-t border-gray-200 dark:border-neutral-700 text-center mb-10 pb-10">
             <button onclick="window.location.reload()" class="px-8 py-3 bg-green-600 hover:bg-green-700 text-white rounded-lg font-bold shadow-lg transition-transform hover:scale-105">Finish Setup</button>
        </div>
    `;

    // --- EVENT LISTENERS ---
    const copyBtn = document.getElementById('btn-copy-key');
    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            const keyText = document.getElementById('display-api-key').innerText.trim();
            navigator.clipboard.writeText(keyText);
            ui.showToast('Copied!', 'success');
        });
    }

    const copyCurlBtn = document.getElementById('btn-copy-curl');
    if (copyCurlBtn) {
        copyCurlBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(document.getElementById('curl-content').innerText);
            ui.showToast('Command copied!', 'success');
        });
    }

    const copyCodeBtn = document.getElementById('btn-copy-code');
    if (copyCodeBtn) {
        copyCodeBtn.addEventListener('click', () => {
            const codeText = document.getElementById('py-code-content').innerText;
            navigator.clipboard.writeText(codeText);
            ui.showToast('Code Copied!', 'success');
        });
    }

    const rotateBtn = document.getElementById('btn-rotate-key');
    if (rotateBtn) {
        rotateBtn.addEventListener('click', async () => {
            if (!confirm("Are you sure? This will invalidate the old key immediatley. Any running bots will stop working until updated.")) return;

            rotateBtn.disabled = true;
            rotateBtn.innerText = "Generating...";

            try {
                // Use imported api client
                const resp = await api.rotateKey(policy_id);

                if (resp.ok && resp.credentials) {
                    const newKey = resp.credentials.api_key;

                    // 1. Update Display
                    const display = document.getElementById('display-api-key');
                    if (display) {
                        display.innerText = newKey;
                        display.classList.add('bg-green-50', 'text-green-700');
                        setTimeout(() => display.classList.remove('bg-green-50', 'text-green-700'), 500);
                    }

                    // 2. Remove Warning
                    const warning = document.getElementById('key-warning');
                    if (warning) warning.remove();

                    // 3. Update Python Code Snippet
                    const codeBlock = document.getElementById('py-code-content');
                    if (codeBlock) {
                        // Regex to replace the value in SAFI_BOT_SECRET line
                        codeBlock.innerText = codeBlock.innerText.replace(/SAFI_BOT_SECRET = os\.environ\.get\("SAFI_BOT_SECRET", ".*?"\)/, `SAFI_BOT_SECRET = os.environ.get("SAFI_BOT_SECRET", "${newKey}")`);
                    }

                    // 3b. And the curl command. Missing this was the whole point
                    // of rotating: the reader copies the test command, gets a
                    // 401 from the key they just replaced, and concludes the
                    // rotation broke something.
                    const curlBlock = document.getElementById('curl-content');
                    if (curlBlock) {
                        curlBlock.innerText = curlBlock.innerText.replace(
                            /X-API-KEY: [^"]*/, `X-API-KEY: ${newKey}`);
                    }

                    // 3c. The masked-key notices are now wrong — a real key exists.
                    document.querySelectorAll('[data-masked-notice]')
                        .forEach(el => el.remove());

                    ui.showToast('New Key Generated!', 'success');
                } else {
                    ui.showToast('Failed to rotate key', 'error');
                }
            } catch (e) {
                console.error(e);
                ui.showToast('Error rotating key: ' + e.message, 'error');
            } finally {
                rotateBtn.disabled = false;
                rotateBtn.innerText = "Rotate";
            }
        });
    }
}
