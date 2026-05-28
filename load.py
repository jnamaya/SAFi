import requests
import concurrent.futures
import time
import statistics

# CONFIGURATION
BASE_URL = "http://127.0.0.1:5001"
CONCURRENT_USERS = 80  # Matches your DB pool size
PROMPT = "Hello, are you active?"

def simulate_user(user_id):
    """
    Runs a single user flow using the robust 'requests.Session' object.
    """
    session = requests.Session()
    
    try:
        # --- STEP 1: LOGIN ---
        # requests automatically handles redirects and cookies
        login_url = f"{BASE_URL}/api/login/demo"
        resp = session.get(login_url)
        
        if resp.status_code not in [200, 302]:
            try:
                err = resp.text[:200]
            except:
                err = "Unknown"
            return f"Login Failed (HTTP {resp.status_code}) - {err}"
        
        # DEBUG: Verify we actually hold the cookie now
        if not session.cookies:
            return "Login Failed (No Cookies Saved)"

        # FIX: The server sends 'Secure' cookies (for HTTPS), but we are testing on HTTP.
        # We must strip the secure flag so 'requests' will send them back over plain HTTP.
        for cookie in session.cookies:
            cookie.secure = False

        # --- STEP 2: CREATE CONVERSATION ---
        chat_url = f"{BASE_URL}/api/conversations"
        resp = session.post(chat_url)
        
        if resp.status_code != 201:
            try:
                err = resp.text[:200]
            except:
                err = "Unknown"
            return f"Chat Create Failed (HTTP {resp.status_code}) - {err}"
            
        data = resp.json()
        conversation_id = data.get('id')

        # --- STEP 3: SEND PROMPT ---
        prompt_url = f"{BASE_URL}/api/process_prompt"
        payload = {"message": PROMPT, "conversation_id": conversation_id}
        
        start_time = time.time()
        resp = session.post(prompt_url, json=payload)
        elapsed = time.time() - start_time
        
        if resp.status_code == 200:
            return elapsed # Return the time taken (float)
        elif resp.status_code == 429:
            return "Rate Limited (429)"
        else:
            # Capturing the response text for debugging 500s
            try:
                error_detail = resp.json().get('error', resp.text[:200])
            except:
                error_detail = resp.text[:200]
            return f"Prompt Failed (HTTP {resp.status_code}) - {error_detail}"

    except Exception as e:
        return f"Exception: {str(e)}"

def main():
    print(f"--- Starting Synchronous Benchmark: {CONCURRENT_USERS} Users ---")
    
    # We use ThreadPoolExecutor to run these in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as executor:
        # Map user_ids to the simulate_user function
        futures = {executor.submit(simulate_user, i): i for i in range(CONCURRENT_USERS)}
        
        results = []
        errors = []
        
        for future in concurrent.futures.as_completed(futures):
            user_id = futures[future]
            result = future.result()
            
            if isinstance(result, float):
                results.append(result)
                print(f"User {user_id}: SUCCESS ({result:.2f}s)")
            else:
                errors.append(result)
                print(f"User {user_id}: {result}")

    # --- REPORT ---
    print("\n--- Results ---")
    print(f"Total Requests: {CONCURRENT_USERS}")
    print(f"Successful:     {len(results)}")
    print(f"Failed:         {len(errors)}")
    
    if results:
        print(f"Avg Latency:    {statistics.mean(results):.2f}s")
        print(f"Max Latency:    {max(results):.2f}s")
    
    # If all failed, show the most common error
    if not results and errors:
        print(f"Most common error: {max(set(errors), key=errors.count)}")

if __name__ == "__main__":
    main()