import os
import sys
import traceback
import aiohttp
import asyncio
from http import HTTPStatus

from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes
from flask import Flask, request, Response

# --- Configuration ---
# In production, these should be loaded from environment variables
APP_ID = os.environ.get("MicrosoftAppId", "")
APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
# NEW: Load the Tenant ID. Required for Single Tenant (Internal) bots.
APP_TENANT_ID = os.environ.get("MicrosoftAppTenantId", None)

# POINT TO THE NEW BOT ENDPOINT ON THE BACKEND
# IMPORTANT: Update the port if your backend runs on a different port than 5001
SAFI_API_URL = os.environ.get("SAFI_API_URL", "http://localhost:5001/api/bot/process_prompt")
# Policy API key for the backend's /api/bot endpoint (minted in the SAFi
# policy UI, checked against the api_keys table). Never hardcode it.
SAFI_BOT_SECRET = os.environ.get("SAFI_BOT_POLICY_API_KEY", "")
SAFI_PERSONA = os.environ.get("SAFI_BOT_PERSONA", "safinstitute_org_health")  # The persona this bot will assume

# Create Flask app
app = Flask(__name__)

# Create adapter
# UPDATED: We pass the Tenant ID to settings. If it's None (Multi-tenant), it works as before.
# If it's set (Single Tenant), it restricts auth to that tenant.
settings = BotFrameworkAdapterSettings(
    APP_ID, 
    APP_PASSWORD,
    channel_auth_tenant=APP_TENANT_ID
)
adapter = BotFrameworkAdapter(settings)

# Error handler
async def on_error(context: TurnContext, error: Exception):
    print(f"\n [on_turn_error] unhandled error: {error}", file=sys.stderr)
    traceback.print_exc()
    await context.send_activity("The bot encountered an error or bug.")

adapter.on_turn_error = on_error

# --- The Bot Logic ---
class SafiTeamsBot:
    async def on_turn(self, turn_context: TurnContext):
        if turn_context.activity.type == ActivityTypes.message:
            # 1. Get user input
            user_text = turn_context.activity.text
            
            # Remove the @mention if present (Teams sends it in the text)
            if turn_context.activity.recipient:
                user_text = user_text.replace(f"<at>{turn_context.activity.recipient.name}</at>", "").strip()
            
            # 2. Prepare payload for Safi API
            # Updated to match the new 'bot/process_prompt' endpoint schema
            payload = {
                "message": user_text,  # Changed from 'user_prompt' to 'message'
                "user_id": turn_context.activity.from_property.id,
                "conversation_id": turn_context.activity.conversation.id,
                "persona": SAFI_PERSONA 
            }

            # 3. Add Security Header
            headers = {
                "X-API-KEY": SAFI_BOT_SECRET,
                "Content-Type": "application/json"
            }

            # 4. Show typing indicator
            await turn_context.send_activity(Activity(type=ActivityTypes.typing))
            
            # 5. Call Safi Backend
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(SAFI_API_URL, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            safi_data = await resp.json()
                            
                            # Send the governed response back to Teams
                            reply_text = safi_data.get("finalOutput", "[Error: No output from Safi]")
                            await turn_context.send_activity(reply_text)
                        else:
                            error_text = await resp.text()
                            print(f"Safi API Error: {resp.status} - {error_text}", file=sys.stderr)
                            await turn_context.send_activity(f"Error communicating with Safi Logic ({resp.status}): {error_text}")
            except Exception as e:
                print(f"Safi API Connection Exception: {e}", file=sys.stderr)
                await turn_context.send_activity(f"Connection error: {str(e)}")

        elif turn_context.activity.type == ActivityTypes.conversation_update:
            # Welcome message
            for member in turn_context.activity.members_added:
                if member.id != turn_context.activity.recipient.id:
                    await turn_context.send_activity(
                        "Hello! I am the Accion Compliance Assistant, an AI system. "
                        "You are interacting with artificial intelligence, not a human. "
                        "Ask me about IT SOPs, Microsoft 365, or Procurement."
                    )

bot = SafiTeamsBot()

# --- Flask Routes ---

@app.route("/api/messages", methods=["POST"])
def messages():
    """
    Main endpoint for Microsoft Teams to send activities to the bot.
    """
    if "application/json" in request.headers["Content-Type"]:
        body = request.json
    else:
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    async def aux_func(turn_context):
        await bot.on_turn(turn_context)

    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = adapter.process_activity(activity, auth_header, aux_func)
        loop.run_until_complete(task)
        
        return Response(status=HTTPStatus.OK)
    except Exception as e:
        traceback.print_exc()
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

if __name__ == "__main__":
    try:
        # Run on a different port to avoid conflict with Gunicorn (default 8000/5000)
        app.run(debug=True, port=3978)
    except Exception as e:
        print(e)
