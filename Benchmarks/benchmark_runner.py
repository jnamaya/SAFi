import asyncio
import json
import uuid
import argparse
import inspect
import logging
from datetime import datetime
from pathlib import Path
import sys
import traceback
from types import ModuleType

# --- Pre-emptive Environment Setup ---
# This block runs before any application code is imported. It checks for the --db flag
# and replaces the entire database module with a mock if requested. This is the
# only reliable way to prevent the application from initializing a real DB connection at import time.

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("safi.benchmark")

def _setup_environment_and_patching():
    """
    Parses command-line arguments to determine if the database should be disabled.
    If so, it replaces the database module in Python's central module cache (sys.modules)
    with a mock object that absorbs all calls without error. This mock is designed to be
    compatible with Python's introspection tools and application logic that expects
    connection and cursor objects.
    """
    args = sys.argv
    db_off = False
    for i, arg in enumerate(args):
        if arg == '--db' and i + 1 < len(args):
            if args[i+1].lower() in ("off", "false", "0", "no"):
                db_off = True
                break
        elif arg.startswith('--db=') and arg.split('=')[1].lower() in ("off", "false", "0", "no"):
            db_off = True
            break
            
    if db_off:
        log.info("DB is OFF. Replacing safi_app.persistence.database with a mock module.")
        
        class MockCursor:
            def execute(self, *args, **kwargs): pass
            def fetchone(self, *args, **kwargs): return None
            def fetchall(self, *args, **kwargs): return []
            def close(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass

        class MockConnection:
            def cursor(self, *args, **kwargs): return MockCursor()
            def close(self, *args, **kwargs): pass
            def commit(self, *args, **kwargs): pass
            def is_connected(self, *args, **kwargs): return True
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass

        class MockDbModule(ModuleType):
            """
            A mock object that impersonates the database module. It intelligently returns
            a mock connection object for any function that sounds like it's asking for one,
            and returns realistic empty data types (str, list) for fetch/load calls.
            """
            def __init__(self, name):
                super().__init__(name)
                self.__file__ = f"<mock-module '{self.__name__}'>"

            def __getattr__(self, name):
                if name.startswith('__'):
                    raise AttributeError(f"Mock module '{self.__name__}' has no attribute '{name}'")
                
                name_lower = name.lower()

                # If any part of the app asks for a connection, give it a fake one.
                if 'conn' in name_lower or 'connection' in name_lower:
                    return lambda *args, **kwargs: MockConnection()

                # Handle fetch/load calls with more realistic empty return types
                if name_lower.startswith(('fetch', 'get', 'load')):
                    if 'summary' in name_lower:
                        return lambda *args, **kwargs: ""  # Return empty string for summaries
                    if 'history' in name_lower or 'messages' in name_lower:
                        return lambda *args, **kwargs: []  # Return empty list for history
                    # For memory objects, returning None is acceptable as the app has fallbacks
                    if 'memory' in name_lower:
                        return lambda *args, **kwargs: None 
                
                # For anything else (init_pool, add_message, insert, update), just do nothing.
                return lambda *args, **kwargs: None
                
        sys.modules['safi_app.persistence.database'] = MockDbModule('safi_app.persistence.database')
        return False  # DB is NOT enabled
        
    return True # DB is enabled

DB_ENABLED = _setup_environment_and_patching()

# --- Application Imports ---
# Now that the environment is set up (and the DB module potentially mocked),
# we can safely import the application code.

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

try:
    from safi_app.persistence import database as db
    HAS_DB = True
except (ImportError, AttributeError):
    # AttributeError can be raised if the mock is in place
    HAS_DB = False if not DB_ENABLED else True


from safi_app.config import Config
from safi_app.core.orchestrator import SAFi
from safi_app.core.values import get_profile


# -----------------------------
# DB helpers (defensive, skippable)
# -----------------------------
def _disable_db(reason: str):
    global DB_ENABLED
    if DB_ENABLED:
        DB_ENABLED = False
        log.warning(f"DB disabled for this run: {reason}")

def _safe_db_call_create_conversation(conv_id: str, user_id, title: str) -> None:
    if not (HAS_DB and DB_ENABLED):
        return
    try:
        # If DB is disabled, this call goes to the mock and does nothing.
        db.create_conversation(conv_id, user_id, title)
    except Exception as e:
        msg = str(e)
        if "1452" in msg or "Cannot add or update a child row" in msg:
            _disable_db("foreign key constraint (user_id). Use --db off or supply a real user.")
        else:
            log.warning(f"Create conversation failed and was skipped: {e}")

def _safe_db_call_add_message(conv_id: str, role: str, content: str) -> None:
    if not (HAS_DB and DB_ENABLED):
        return
    try:
        # If DB is disabled, this call goes to the mock and does nothing.
        db.add_message(conv_id, role, content)
    except Exception as e:
        log.warning(f"Add message failed and was skipped: {e}")


# --------------------------------
# SAFi entrypoint discovery
# --------------------------------
def _pick_entrypoint(safi: SAFi):
    """
    Returns (callable, accepted_kwargs_set).
    This function now explicitly looks for 'process_prompt' to avoid ambiguity.
    """
    fn = getattr(safi, "process_prompt", None)
    if fn and callable(fn):
        try:
            sig = inspect.signature(fn)
            return fn, set(sig.parameters.keys())
        except Exception as e:
            raise RuntimeError(f"Could not inspect the signature of 'process_prompt': {e}") from e

    raise RuntimeError("The required 'process_prompt' method was not found in the SAFi class.")


async def _run_safi_turn(safi: SAFi, profile_name: str, prompt: str, conversation_id: str, user_id):
    """
    Invoke the selected entrypoint with whatever args it can accept.
    """
    fn, accepts = _pick_entrypoint(safi)

    kwargs = {}
    # Translate the runner's 'prompt' into the application's 'user_prompt'
    if "user_prompt" in accepts:
        kwargs["user_prompt"] = prompt
    elif "prompt" in accepts:
        kwargs["prompt"] = prompt

    # optional context params
    if "profile_name" in accepts:
        kwargs["profile_name"] = profile_name
    if "conversation_id" in accepts:
        kwargs["conversation_id"] = conversation_id
    if "user_id" in accepts:
        kwargs["user_id"] = user_id

    if inspect.iscoroutinefunction(fn):
        return await fn(**kwargs)
    # run sync in default executor
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(**kwargs))


# ---------------------
# Build a SAFi instance
# ---------------------
def _build_safi(config: Config, profile_key: str, profile_obj) -> SAFi:
    """
    SAFi.__init__ requires either:
      - value_profile_or_list: dict with 'values' or a list of values
      - value_set: concrete values payload
    """
    init_sig = inspect.signature(SAFi.__init__)
    params = set(init_sig.parameters.keys())

    # If get_profile returns dict with 'values' list => pass it
    if isinstance(profile_obj, dict) and "values" in profile_obj and isinstance(profile_obj["values"], (list, dict)):
        if "value_profile_or_list" in params:
            return SAFi(config=config, value_profile_or_list=profile_obj)

    # If get_profile returns list of values => pass list
    if isinstance(profile_obj, list) and "value_profile_or_list" in params:
        return SAFi(config=config, value_profile_or_list=profile_obj)

    # If it exposes 'value_set' and ctor accepts it
    if isinstance(profile_obj, dict) and "value_set" in profile_obj and "value_set" in params:
        return SAFi(config=config, value_set=profile_obj["value_set"])

    # Try derive list from dict values
    if isinstance(profile_obj, dict) and "values" in profile_obj and isinstance(profile_obj["values"], dict):
        vs = profile_obj["values"]
        derived = [{"name": k, "weight": float(v) if isinstance(v, (int, float)) else (1.0 if v else 0.0)} for k, v in vs.items()]
        if "value_profile_or_list" in params:
            return SAFi(config=config, value_profile_or_list={"name": profile_obj.get("name", profile_key), "values": derived})

    raise ValueError("Profile lacks usable values. Ensure get_profile returns a dict with 'values' or a list, or a dict with 'value_set'.")


# ---------------------
# Benchmark runner
# ---------------------
async def run_benchmark(profile_key: str, prompts_file: str, output_file: str, db_flag: str):
    # Load prompts
    path = Path(prompts_file)
    if not path.exists():
        raise FileNotFoundError(f"Prompts file not found: {prompts_file}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    test_cases = data["tests"] if isinstance(data, dict) and "tests" in data else data
    if not isinstance(test_cases, list) or not test_cases:
        raise ValueError("No test cases found in prompts file.")

    # Profile and SAFi
    profile = get_profile(profile_key)
    if profile is None:
        raise ValueError(f"Profile not found: {profile_key}")

    config = Config()
    # As a safeguard, nullify the DB_HOST if DB is disabled. The module patch
    # is the primary fix, but this adds another layer of safety.
    if not DB_ENABLED:
        config.DB_HOST = None
        
    safi = _build_safi(config=config, profile_key=profile_key, profile_obj=profile)

    # Friendly name only for logs
    try:
        friendly = profile.get("name") if isinstance(profile, dict) else profile_key
    except Exception:
        friendly = profile_key
    print(f"SAFi: profile '{friendly}' active, running on Groq.")

    log.info(f"--- Starting SAFi Benchmark for Profile: '{profile_key}' ---")
    log.info(f"SAFi: profile '{friendly}' active.")
    log.info(f"Found {len(test_cases)} test cases to run...")

    results = []
    passed = 0
    failed = 0

    for i, case in enumerate(test_cases):
        prompt_id = case.get("id", f"CASE-{i+1}")
        user_prompt = case.get("prompt", "")
        expected_decision = case.get("expected_will_decision")

        print(f"\n[{i+1}/{len(test_cases)}] Running test ID: {prompt_id}")
        print(f"  Prompt: '{user_prompt[:80]}...'")

        conversation_id = str(uuid.uuid4())
        # Use None by default to avoid FK issues; if your DB requires INT ids, set BENCH_USER_ID in Config
        user_id = getattr(config, "BENCH_USER_ID", None)
        title = f"Benchmark Test - {prompt_id}"

        # These calls will now go to our mock functions if DB is disabled
        _safe_db_call_create_conversation(conversation_id, user_id, title)
        _safe_db_call_add_message(conversation_id, "user", user_prompt)

        # Run the turn
        error = None
        result_payload = None
        try:
            result_payload = await _run_safi_turn(
                safi=safi,
                profile_name=profile_key,
                prompt=user_prompt,
                conversation_id=conversation_id,
                user_id=user_id,
            )
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log.debug(traceback.format_exc())

        # Evaluate (optional)
        passed_case = None
        actual_decision = None
        actual_reason = None
        if error is None:
            if isinstance(result_payload, dict):
                actual_decision = (
                    result_payload.get("willDecision") # Match the camelCase from orchestrator.py
                    or result_payload.get("will_decision")
                    or result_payload.get("decision")
                    or (result_payload.get("will") or {}).get("decision")
                )
                actual_reason = (
                    result_payload.get("willReason")
                    or result_payload.get("will_reason")
                    or result_payload.get("reason")
                )
            passed_case = (expected_decision is None) or (str(actual_decision).lower() == str(expected_decision).lower())
        else:
            passed_case = False

        if passed_case:
            passed += 1
        else:
            failed += 1

        results.append({
            "id": prompt_id,
            "prompt": user_prompt,
            "expected_will_decision": expected_decision,
            "actual_will_decision": actual_decision,
            "actual_will_reason": actual_reason,
            "passed": bool(passed_case),
            "error": error,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

        if error:
            print(f"  ERROR processing prompt: {error}")
        else:
            if passed_case:
                print(f"  Result decision: {actual_decision}  [PASS]")
            else:
                print(f"  Result decision: {actual_decision}  [FAIL] (Expected: {expected_decision})")
            
            if actual_reason:
                print(f"    Reason: {actual_reason}")

    # Summary
    print("\n--- Benchmark Summary ---")
    print(f"Total Prompts Run: {len(test_cases)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    rate = 0.0 if len(test_cases) == 0 else passed / len(test_cases)
    print(f"Success Rate: {rate:.2%}")
    print("-------------------------")

    # Save
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print(f"Detailed results saved to '{output_file}'")


def main():
    parser = argparse.ArgumentParser(description="Run automated benchmarks for the SAFi framework.")
    parser.add_argument("--profile", type=str, required=True, help="SAFi profile key (e.g., 'fiduciary').")
    parser.add_argument("--prompts", type=str, required=True, help="Path to JSON test prompts.")
    parser.add_argument("--output", type=str, required=True, help="Where to write JSON results.")
    parser.add_argument("--db", type=str, default="on", help="on|off (disable DB writes for benchmarks)")
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.profile, args.prompts, args.output, args.db))

if __name__ == "__main__":
    main()

