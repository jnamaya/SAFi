#!/usr/bin/env python3
"""Download Gemma 4 31B and 26B-A4B GGUF models for SAFi appliance."""
import sys
import time
from pathlib import Path
from huggingface_hub import hf_hub_download

MODELS = [
    {
        "name": "Gemma 4 31B (Dense Flagship)",
        "repo_id": "unsloth/gemma-4-31B-it-GGUF",
        "filename": "gemma-4-31B-it-Q4_K_M.gguf",
        "target_dir": Path("/var/lib/safi/models/gemma-4-31b"),
    },
    {
        "name": "Gemma 4 26B A4B (MoE 4B active)",
        "repo_id": "unsloth/gemma-4-26B-A4B-it-GGUF",
        "filename": "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf",
        "target_dir": Path("/var/lib/safi/models/gemma-4-26b-a4b"),
    },
]

def main():
    print("=== Starting Gemma 4 Model Download ===", flush=True)
    for model in MODELS:
        t0 = time.time()
        print(f"\n--- Downloading {model['name']} ---", flush=True)
        print(f"Repo: {model['repo_id']}", flush=True)
        print(f"File: {model['filename']}", flush=True)
        print(f"Target: {model['target_dir']}", flush=True)
        
        model["target_dir"].mkdir(parents=True, exist_ok=True)
        
        destination = model["target_dir"] / model["filename"]
        if destination.exists() and destination.stat().st_size > 10_000_000_000:
            print(f"Target file already exists ({destination.stat().st_size} bytes). Verifying...", flush=True)
        
        path = hf_hub_download(
            repo_id=model["repo_id"],
            filename=model["filename"],
            local_dir=str(model["target_dir"]),
        )
        elapsed = time.time() - t0
        print(f"Successfully finished {model['name']} -> {path} ({elapsed:.1f}s)", flush=True)

    print("\n=== All Gemma 4 models downloaded successfully! ===", flush=True)

if __name__ == "__main__":
    main()
