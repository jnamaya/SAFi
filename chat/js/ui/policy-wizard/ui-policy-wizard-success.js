import * as ui from './../ui.js';
import * as api from '../../core/api.js';

export function renderSuccessStep(container, policyData, generatedCredentials) {
    if (!generatedCredentials) {
        container.innerHTML = `<div class="text-red-500 text-center">Error: No credentials returned.</div>`;
        return;
    }

    const { policy_id, api_key } = generatedCredentials;
    const publicUrl = "https://safi.selfalignmentframework.com";
    const endpointUrl = `${publicUrl}/api/bot/process_prompt`;

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
                    <label class="block text-xs uppercase text-gray-400 font-bold mb-1">Public Endpoint</label>
                    <code class="block p-3 bg-white dark:bg-black rounded border border-gray-200 dark:border-neutral-700 font-mono text-xs truncate text-gray-600 dark:text-gray-300" title="${endpointUrl}">${endpointUrl}</code>
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
             <!-- Getting Started -->
             <div class="bg-blue-50 dark:bg-blue-900/10 p-5 rounded-xl border border-blue-200 dark:border-blue-800">
                 <h4 class="font-bold text-blue-900 dark:text-blue-100 flex items-center gap-2">
                     <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                     How to Get Started
                 </h4>
                 <p class="text-sm text-blue-800 dark:text-blue-200 mt-2">
                     You can start using this policy immediately!
                 </p>
                 <ol class="list-decimal list-inside text-sm text-blue-700 dark:text-blue-300 mt-2 space-y-1">
                     <li>Go to the <strong>Agents</strong> tab.</li>
                     <li>Create a <strong>New Agent</strong> (or edit an existing one).</li>
                     <li>In Step 1 (Profile & Governance), select this Policy from the dropdown.</li>
                     <li>The agent will now be governed by your new Constitution!</li>
                 </ol>
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
SAFI_API_URL = os.environ.get("SAFI_API_URL", "${endpointUrl}")
SAFI_BOT_SECRET = os.environ.get("SAFI_BOT_SECRET", "${api_key}") 
SAFI_PERSONA = "fiduciary" # Change this as needed

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
             <button onclick="window.location.reload()" class="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold shadow-lg transition-transform hover:scale-105">Finish Setup</button>
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
