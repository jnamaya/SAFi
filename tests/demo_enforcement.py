import requests
import sys
import json
import os

# --- CONFIG ---
BASE_URL = "http://127.0.0.1:5000/api/bot/process_prompt"
DEFAULT_PERSONA = "fiduciary" # Testing with the 'Fiduciary' bot as requested

def run_demo(api_key, user_prompt):
    print(f"\n--- 🧪 SAFi Policy Enforcement Demo ---")
    print(f"🔹 Target Agent: {DEFAULT_PERSONA}")
    print(f"🔹 Prompt: \"{user_prompt}\"")
    print(f"🔹 Using Key: {api_key[:6]}...{api_key[-4:]}")
    
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "message": user_prompt,
        "user_id": "demo_user_01",
        "conversation_id": "demo_convo_01",
        "persona": DEFAULT_PERSONA
    }
    
    try:
        response = requests.post(BASE_URL, headers=headers, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            decision = data.get("willDecision", "UNKNOWN")
            reason = data.get("willReason", "No reason provided")
            output = data.get("finalOutput", "")
            
            print(f"\n⚡ Response Status: {response.status_code}")
            print(f"⚖️  Will Decision: {decision.upper()}")
            
            if decision == "violation":
                print(f"🛑 REJECTED: {reason}")
                print(f"📝 Final Output: {output}")
            else:
                print(f"✅ APPROVED")
                print(f"📝 Final Output: {output[:100]}...") # Truncate for cleaner demo
                
        else:
            print(f"\n❌ Error {response.status_code}: {response.text}")

    except Exception as e:
        print(f"\n🔥 Fatal Error: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python tests/demo_enforcement.py <API_KEY> <PROMPT>")
        sys.exit(1)
        
    key = sys.argv[1]
    prompt = " ".join(sys.argv[2:])
    run_demo(key, prompt)
