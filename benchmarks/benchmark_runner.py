import asyncio
import json
import uuid
import argparse
import logging
from datetime import datetime
from pathlib import Path
import sys
import traceback

# --- Application Imports ---
# Add the project root to the path to allow for absolute imports
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from safi_app.config import Config
from safi_app.core.orchestrator import SAFi
from safi_app.core.values import get_profile

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("safi.benchmark")


async def run_benchmark(profile_key: str, prompts_file: str, output_file: str):
    """Main function to run the benchmark test suite for the full SAFi framework."""
    
    path = Path(prompts_file)
    if not path.exists():
        raise FileNotFoundError(f"Prompts file not found: {prompts_file}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        test_cases = data
    elif isinstance(data, dict):
        prompts_list = next((val for val in data.values() if isinstance(val, list)), None)
        if not prompts_list:
            raise ValueError("Benchmark JSON is a dictionary but contains no list of prompts.")
        test_cases = prompts_list
    else:
        raise TypeError("Prompts file must be a JSON list of objects or a dictionary containing such a list.")

    profile = get_profile(profile_key)
    if profile is None:
        raise ValueError(f"Profile not found: {profile_key}")
    
    config = Config()
    # Build the full SAFi orchestrator instance
    safi = SAFi(config=config, value_profile_or_list=profile)

    profile_name = profile.get("name", profile_key)
    log.info(f"--- Starting SAFi Benchmark for Profile: '{profile_name}' ---")
    log.info(f"Found {len(test_cases)} test cases to run...")

    results = []
    passed_count = 0

    for i, case in enumerate(test_cases):
        prompt_id = case.get("id", f"CASE-{i+1}")
        user_prompt = case.get("prompt", "")
        expected_decision = case.get("expected_will_decision")
        prompt_type = case.get("type", "Ideal")

        log.info(f"[{i+1}/{len(test_cases)}] Running test ID: {prompt_id} (Type: {prompt_type})")

        conversation_id = str(uuid.uuid4())
        user_id = "benchmark_user"

        error_str = None
        result_payload = None
        try:
            # Run the full SAFi process: Intellect -> Will
            result_payload = await safi.process_prompt(
                user_prompt=user_prompt,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        except Exception as e:
            error_str = f"{type(e).__name__}: {e}"
            log.error(traceback.format_exc())

        # --- SAFi Evaluation Logic ---
        # The goal is to test if the 'Will' faculty makes the correct decision.
        is_passed = False
        actual_decision = result_payload.get("willDecision") if result_payload else "error"

        # For SAFi, a 'pass' means the Will faculty made the correct final decision
        # to either approve a safe response or block an unsafe one.
        if actual_decision == expected_decision:
            is_passed = True
        
        if is_passed:
            passed_count += 1
            log.info(f"  Will Decision: '{actual_decision}'  [PASS]")
        else:
            log.warning(f"  Will Decision: '{actual_decision}'  [FAIL] (Expected: '{expected_decision}')")
        
        results.append({
            "id": prompt_id,
            "prompt": user_prompt,
            "prompt_type": prompt_type,
            "expected_will_decision": expected_decision,
            "actual_will_decision": actual_decision,
            "actual_will_reason": result_payload.get("willReason", "") if result_payload else "",
            "final_response": result_payload.get("answer", "") if result_payload else "",
            "passed": is_passed,
            "error": error_str,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    total_cases = len(test_cases)
    success_rate = (passed_count / total_cases) if total_cases > 0 else 0.0
    log.info("\n--- SAFi Benchmark Summary ---")
    log.info(f"Total Prompts: {total_cases}, Passed: {passed_count}, Failed: {total_cases - passed_count}")
    log.info(f"Success Rate: {success_rate:.2%}")
    log.info("----------------------------")

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)
    log.info(f"Detailed results saved to '{output_file}'")

def main():
    parser = argparse.ArgumentParser(description="Run automated benchmarks for the SAFi framework.")
    parser.add_argument("--profile", type=str, required=True, help="SAFi profile key (e.g., 'fiduciary').")
    parser.add_argument("--prompts", type=str, required=True, help="Path to JSON test prompts.")
    parser.add_argument("--output", type=str, required=True, help="Path to save JSON results.")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.profile, args.prompts, args.output))

if __name__ == "__main__":
    main()
