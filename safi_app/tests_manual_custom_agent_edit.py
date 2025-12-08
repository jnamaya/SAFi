import json
import os
import sys

# Add the parent directory to sys.path to allow importing from safi_app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.values import load_custom_persona, list_custom_personas

def test_edit_flow():
    print("--- Testing Edit Logic ---")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    custom_dir = os.path.join(base_dir, "core", "personas", "custom")
    os.makedirs(custom_dir, exist_ok=True)
    
    # 1. Create Initial Agent
    agent_key = "test_edit_agent"
    file_path = os.path.join(custom_dir, f"{agent_key}.json")
    
    initial_agent = {
        "key": agent_key,
        "name": "Original Name",
        "description": "Original Description",
        "values": [],
        "rules": ["Rule 1"]
    }
    
    print(f"Creating initial agent at: {file_path}")
    with open(file_path, "w") as f:
        json.dump(initial_agent, f)
        
    # Verify Initial Load
    loaded = load_custom_persona(agent_key)
    if loaded['name'] == "Original Name":
        print("✅ Initial Create Passed")
    else:
        print("❌ Initial Create FAILED")
        return

    # 2. Simulate "Edit" - Overwrite file with new data
    updated_agent = initial_agent.copy()
    updated_agent['name'] = "Updated Name"
    updated_agent['rules'].append("Rule 2")
    
    print("Updating agent...")
    with open(file_path, "w") as f:
        json.dump(updated_agent, f)
        
    # Verify Update
    reloaded = load_custom_persona(agent_key)
    if reloaded['name'] == "Updated Name" and len(reloaded.get('will_rules', []) or reloaded.get('rules', [])) == 2:
        print("✅ Edit / Update Passed")
    else:
        print("❌ Edit / Update FAILED")
        print(f"Loaded: {reloaded}")
        
    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)
        print("✅ Cleanup Passed")

if __name__ == "__main__":
    test_edit_flow()
