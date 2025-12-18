import subprocess
import sys
import re

def run_tests_and_generate_report():
    print("📋 Starting SAFi Fidelity & Robustness Audit...\n")
    
    # Run pytest with -s to capture stdout (the prints I added)
    cmd = [sys.executable, "-m", "pytest", "-s", "tests/test_closed_loop.py", "tests/test_api_settings.py"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("❌ Error: pytest not found. Please install pytest.")
        return

    output = result.stdout
    exit_code = result.returncode
    
    # Parse Validation Checks
    checks = []
    lines = output.split('\n')
    
    interaction_stats = {}
    
    print("--- RAW TEST LOGS ---")
    for line in lines:
        if "✅" in line:
            checks.append(line.strip())
            print(line.strip())
        if "Interaction Index Updated" in line:
            # Extract numbers if possible
            match = re.search(r'(\d+) -> (\d+)', line)
            if match:
                interaction_stats['start'] = match.group(1)
                interaction_stats['end'] = match.group(2)
    print("---------------------\n")
    
    print("📊 FIDELITY REPORT")
    print("==================")
    
    if exit_code == 0:
        print("RESULT: PASS [All Systems Operational]")
    else:
        print("RESULT: FAIL [Regressions Detected]")
        print("\nFailures:")
        print(result.stderr)
        
    print("\nCORE FACULTIES:")
    faculties = ["Intellect", "Will", "Conscience", "Spirit"]
    for f in faculties:
        # Check if we have a checkmark for this faculty
        found = any(f in c for c in checks)
        status = "ONLINE" if found else "UNKNOWN/FAILED"
        print(f"  - {f}: {status}")
        
    print("\nDATA INTEGRITY:")
    if interaction_stats:
        print(f"  - Interaction Index (Turn Count): Verified Increment ({interaction_stats.get('start')} -> {interaction_stats.get('end')})")
    else:
        print("  - Interaction Index: Not Verified")
        
    print("\nAPI SETTINGS:")
    api_checks = [c for c in checks if "API" in c]
    for ac in api_checks:
        print(f"  - {ac}")
        
    if exit_code != 0:
        sys.exit(1)

if __name__ == "__main__":
    run_tests_and_generate_report()
