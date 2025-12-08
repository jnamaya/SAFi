import json
import os
import sys

# Add the parent directory to sys.path to allow importing from safi_app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.values import load_custom_persona, list_custom_personas

def test_file_loading():
    print("--- Testing Core Logic ---")
    # Determine the directory relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    custom_dir = os.path.join(base_dir, "core", "personas", "custom")
    os.makedirs(custom_dir, exist_ok=True)
    
    # Create a dummy agent
    dummy_agent = {
        "key": "test_agent",
        "name": "Test Agent",
        "description": "A unit test agent",
        "values": [{"name": "Testing", "weight": 1.0}],
        "rules": ["Do pass tests"]
    }
    
    file_path = os.path.join(custom_dir, "test_agent.json")
    print(f"Writing test agent to: {file_path}")
    
    with open(file_path, "w") as f:
        json.dump(dummy_agent, f)
        
    # Test List
    profiles = list_custom_personas()
    found = any(p['key'] == 'test_agent' for p in profiles)
    if found:
        print("✅ List Custom Personas Passed")
    else:
        print("❌ List Custom Personas FAILED")
        print(f"Found profiles: {profiles}")
    
    # Test Load
    loaded = load_custom_persona("test_agent")
    if loaded and loaded['name'] == "Test Agent":
        print("✅ Load Custom Persona Passed")
    else:
        print("❌ Load Custom Persona FAILED")
        
    # Cleanup
    if os.path.exists(file_path):
        os.remove(file_path)
        print("✅ Cleanup Passed")

if __name__ == "__main__":
    test_file_loading()
