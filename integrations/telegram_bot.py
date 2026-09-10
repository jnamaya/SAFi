import os
import requests
import logging
import re
import html
from flask import Flask, request

app = Flask(__name__)

# --- Configuration ---
# All secrets come from the environment (systemd unit loads /var/www/safi/.env
# via EnvironmentFile, or export them before running). Never hardcode them.
SAFI_API_URL = os.environ.get("SAFI_API_URL", "http://localhost:5001/api/bot/process_prompt")
SAFI_BOT_SECRET = os.environ.get("SAFI_BOT_POLICY_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

PERSONA = os.environ.get("SAFI_BOT_PERSONA", "bible_scholar")
BOT_HANDLE = "BibleScholarBot"
TRIGGER_WORD = "/safi"

logging.basicConfig(level=logging.INFO)

# --- HELPER: CONVERT MARKDOWN TO TELEGRAM HTML ---
def format_for_telegram(text):
    """
    Converts Markdown text to Telegram-supported HTML safely.
    Crucially, it escapes special characters (Example: '&' -> '&amp;') 
    BEFORE applying formatting tags to prevent 'Bad Request' errors.
    """
    if not text: return ""

    # 1. ESCAPE TEXT FIRST
    # This ensures 'Bread & Fish' becomes 'Bread &amp; Fish' so Telegram doesn't crash.
    text = html.escape(text, quote=False)

    # 2. Apply inline styles (Bold, Italic, Code, Underline)
    # The regex matches the *escaped* text, so we can safely wrap matches in <b> tags.
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)   # **Bold**
    text = re.sub(r'__(.*?)__', r'<u>\1</u>', text)       # __Underline__
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)   # `Code`
    text = re.sub(r'(?<!^)\*(.*?)\*(?!$)', r'<i>\1</i>', text) # *Italic*

    lines = text.split('\n')
    formatted_lines = []
    
    in_code_block = False

    for line in lines:
        stripped = line.strip()
        
        # --- A. Code Blocks ---
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        
        if in_code_block:
            # Text is already escaped from step 1, just wrap in pre
            formatted_lines.append(f"<pre>{line}</pre>")
            continue

        # --- B. Tables ---
        # Note: 'strip' might remove the escaped pipe if not careful, 
        # but html.escape doesn't touch '|', so we are safe.
        if '|' in line and not line.startswith('http') and len(line) > 2:
            if re.match(r'^\|?[\s\-\:]+\|?$', stripped): continue
            
            parts = [p.strip() for p in stripped.strip('|').split('|')]
            
            if len(parts) >= 2:
                if len(parts) == 2:
                    formatted_lines.append(f"• <b>{parts[0]}</b>: {parts[1]}")
                else:
                    row_block = f"\n<b>{parts[0]}</b>"
                    for p in parts[1:]:
                        if p: row_block += f"\n  └ {p}"
                    formatted_lines.append(row_block)
            continue

        # --- C. Headers ---
        if stripped.startswith('#'):
            clean_header = stripped.lstrip('#').strip()
            prefix = "\n\n" if formatted_lines else ""
            formatted_lines.append(f"{prefix}<b>{clean_header}</b>")
            continue

        # --- D. Lists ---
        if re.match(r'^[\*\-]\s', line):
            clean_item = re.sub(r'^[\*\-]\s', '• ', line)
            formatted_lines.append(clean_item)
            continue

        # --- E. Blockquotes ---
        # Since we escaped text, '>' became '&gt;'
        if line.startswith('&gt; '):
            formatted_lines.append(f"<blockquote>{line.replace('&gt; ', '', 1)}</blockquote>")
            continue

        # --- F. Regular Text ---
        formatted_lines.append(line)

    result = "\n".join(formatted_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

@app.route("/telegram", methods=['POST'])
def telegram_webhook():
    data = request.json
    if not data or "message" not in data: return "OK", 200

    msg = data["message"]
    chat_id = msg["chat"]["id"] 
    chat_type = msg["chat"]["type"] 
    text = msg.get("text", "")
    user_name = msg["from"].get("first_name", "Unknown")

    if not text: return "OK", 200

    # /start welcome (private chats): includes the EU AI Act Art. 50(1)
    # AI-interaction disclosure — must be shown at first interaction.
    if text.strip().split("@")[0] == "/start":
        requests.post(TELEGRAM_SEND_URL, json={
            "chat_id": chat_id,
            "text": ("👋 Welcome! I am the Bible Scholar, an AI assistant — "
                     "you are chatting with artificial intelligence, not a human. "
                     "Ask me anything about scripture, or use /safi in group chats."),
            "disable_web_page_preview": True
        })
        return "OK", 200

    should_reply = False
    if chat_type == "private":
        should_reply = True
    else:
        text_lower = text.lower()
        if TRIGGER_WORD in text_lower:
            should_reply = True
        elif "reply_to_message" in msg:
            replied_user = msg["reply_to_message"]["from"].get("username", "")
            if replied_user.lower() == BOT_HANDLE.lower():
                should_reply = True
        if not should_reply:
            entities = msg.get("entities", [])
            for entity in entities:
                if entity["type"] == "mention":
                    offset, length = entity["offset"], entity["length"]
                    if text[offset:offset+length].lower() == f"@{BOT_HANDLE}".lower():
                        should_reply = True
                        break

    if not should_reply:
        print(f"IGNORED: {text}")
        return "OK", 200

    clean_text = text.replace(f"@{BOT_HANDLE}", "").replace(TRIGGER_WORD, "").strip()
    if not clean_text: return "OK", 200

    print(f"ACCEPTED: '{clean_text}' from {user_name}")

    payload = {
        "message": clean_text,
        "user_id": str(msg["from"]["id"]),
        "user_name": user_name,
        "conversation_id": str(chat_id),
        "persona": PERSONA
    }
    
    headers = {"X-API-KEY": SAFI_BOT_SECRET}

    try:
        resp = requests.post(SAFI_API_URL, json=payload, headers=headers)
        if resp.status_code == 200:
            safi_data = resp.json()
            raw_output = safi_data.get("finalOutput", "...")
            
            # 1. Format the main text safely
            reply_text = format_for_telegram(raw_output)
            
            sources = safi_data.get("sources", [])
            if sources:
                reply_text += "\n\n📚 <b>References:</b>"
                for s in sources:
                    if isinstance(s, str): 
                        # Use html.escape on the link to be safe
                        safe_s = html.escape(s)
                        if s.startswith("http"): reply_text += f"\n• <a href='{safe_s}'>Link</a>"
                        else: reply_text += f"\n• {safe_s}"
                    elif isinstance(s, dict): 
                        # CRITICAL: Escape the Title to prevent crashes
                        title = html.escape(s.get('title', 'Link'))
                        url = s.get('url', '#') # URLs are usually fine, but title needs escaping
                        reply_text += f"\n• <a href='{url}'>{title}</a>"
        else:
            reply_text = "⚠️ The scholar is currently unavailable."
    except Exception as e:
        print(f"Error: {e}")
        reply_text = "Connection failed."

    # Added error checking for the Telegram response
    tg_resp = requests.post(TELEGRAM_SEND_URL, json={
        "chat_id": chat_id,
        "text": reply_text,
        "parse_mode": "HTML", 
        "disable_web_page_preview": True 
    })
    
    if tg_resp.status_code != 200:
        print(f"TELEGRAM ERROR {tg_resp.status_code}: {tg_resp.text}")

    return "OK", 200

if __name__ == "__main__":
    app.run(port=4001)