"""Local-model catalogue and hardware probe for the SAFi appliance.

Standard library only, by design. safi-model-fetch runs this during first-boot
setup, before the app virtualenv has been shown to be healthy, so importing
flask/pydantic here would turn a download problem into a startup problem.
The wizard imports the same module to render the model picker, which is why the
two agree on the catalogue by construction.

The catalogue itself is data, not code: see local-models.json next to this file
(installed to /etc/safi/local-models.json).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

CATALOGUE_PATH = Path("/etc/safi/local-models.json")

# Where to look for the catalogue, in order. The staged path is a build-time
# fallback for an image whose 070 hook has not yet moved the file into /etc.
CATALOGUE_CANDIDATES = (
    "/etc/safi/local-models.json",
    "/usr/local/sbin/safi-appliance-stage/local-models.json",
)

# Slack on top of weights + backend assets. Covers the partially-written file
# during a resumed download, the extract, and ordinary log/cache growth. Without
# it a disk that is *exactly* big enough fills to 100% mid-fetch and takes
# MariaDB down with it.
DISK_SLACK_BYTES = 1 << 30

# Ceiling on weight size as a fraction of RAM for the CPU path.
#
# Without a GPU, generation is memory-bandwidth bound: every token re-reads the
# whole weight file, so tokens/sec tracks bandwidth/weights and a 20 GB model on
# a 32 GB box is a slideshow even though it technically fits with room for the
# KV cache. This is a stated heuristic, not a measurement -- we have no
# tokens/sec figures for these quantisations across supported CPUs -- so it is
# deliberately generous at half of RAM, and a detected GPU is what lifts it.
CPU_WEIGHT_FRACTION = 0.5

# Above this, warn that CPU inference will be slow even when it fits.
SLOW_CPU_WARNING_BYTES = 4_000_000_000

_GIB = 1 << 30
_GIB_DECIMAL = 1_000_000_000


def human_bytes(value: int) -> str:
    """Render a byte count the way the picker labels it.

    Decimal GB, not GiB: these are download sizes and VRAM figures, which every
    vendor states in decimal, and a model that says "5 GB" on its HuggingFace
    page should not read as "4.7 GB" here.
    """
    if value is None or value < 0:
        return "unknown"
    if value >= _GIB_DECIMAL:
        return f"{value / _GIB_DECIMAL:.1f} GB"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.0f} MB"
    return f"{value} B"


def ram_gb(value: int) -> str:
    """RAM the way an operator specs a VM, i.e. GiB."""
    if value is None or value < 0:
        return "unknown"
    return f"{value / _GIB:.1f} GiB"


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------

def catalogue_path() -> Path:
    """Resolve the catalogue, tolerating a partially installed image.

    Read on every call rather than captured at import, so SAFI_CATALOGUE can
    point the wizard and the test suite at a build-host copy.
    """
    override = os.environ.get("SAFI_CATALOGUE")
    if override:
        return Path(override)
    for candidate in CATALOGUE_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)
    return Path(CATALOGUE_CANDIDATES[0])


def load_catalogue(path: Path | str | None = None) -> dict:
    if path is None:
        path = catalogue_path()
    with open(path, encoding="utf-8") as handle:
        catalogue = json.load(handle)
    if catalogue.get("schema") != 1:
        raise ValueError(f"unsupported catalogue schema: {catalogue.get('schema')!r}")
    return catalogue


def models(catalogue: dict) -> list[dict]:
    return list(catalogue.get("models", []))


def model_by_id(catalogue: dict, model_id: str) -> dict | None:
    for entry in models(catalogue):
        if entry.get("id") == model_id:
            return entry
    return None


def backend_by_id(catalogue: dict, backend_id: str) -> dict | None:
    return catalogue.get("backends", {}).get(backend_id)


def backend_asset_bytes(backend: dict) -> int:
    return sum(int(a.get("size", 0)) for a in backend.get("assets", []))


def backend_download_bytes(catalogue: dict, backend_id: str) -> int:
    """Bytes a first-time fetch adds for the backend, on top of the model.

    The CPU tarball is already on the ISO, so a CPU fetch downloads nothing
    extra; a CUDA fetch pulls both the server and the split-out cudart archive.
    """
    backend = backend_by_id(catalogue, backend_id)
    if not backend or backend.get("on_iso"):
        return 0
    return backend_asset_bytes(backend)


# --------------------------------------------------------------------------
# hardware probe
# --------------------------------------------------------------------------

def _memtotal_bytes() -> int:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _cpu_flags() -> set[str]:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("flags"):
                    return set(line.split(":", 1)[1].split())
    except OSError:
        pass
    return set()


def _nvidia_gpu() -> dict:
    """Probe NVIDIA via nvidia-smi.

    Every failure mode is reported rather than collapsed into "no GPU": the
    appliance ships no NVIDIA driver of its own, so a box can have a passthrough
    GPU whose driver did not load, and silently falling back to CPU there would
    offer a 20 GB CPU download on a machine that should have been a fast 32B.
    """
    if not shutil.which("nvidia-smi"):
        return {"vendor": None, "usable": False, "reason": "no NVIDIA GPU detected"}
    try:
        raw = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True).stdout
    except subprocess.TimeoutExpired:
        return {"vendor": "nvidia", "usable": False,
                "reason": "nvidia-smi timed out; the GPU driver is not responding"}
    except (subprocess.CalledProcessError, OSError) as exc:
        return {"vendor": "nvidia", "usable": False,
                "reason": f"nvidia-smi failed: {exc}"}

    best = None
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        name, driver, vram_mib = parts
        match = re.match(r"(\d+)", driver)
        if not match:
            continue
        candidate = {
            "vendor": "nvidia",
            "name": name,
            "driver_major": int(match.group(1)),
            "vram_bytes": int(float(vram_mib) * 1024 * 1024),
            "usable": True,
        }
        # Take the largest card: a box with a small display GPU plus a big
        # compute card should be sized for the one we can offload to.
        if best is None or candidate["vram_bytes"] > best["vram_bytes"]:
            best = candidate
    if best is None:
        return {"vendor": "nvidia", "usable": False,
                "reason": "nvidia-smi returned no usable GPU row"}
    return best


def detect_hardware(disk_path: str = "/var/lib") -> dict:
    """Describe the box well enough to recommend a model.

    Never raises. A probe failure degrades to a zero field, which the fit check
    then reads as "cannot confirm" and refuses to recommend against -- setup has
    to stay reachable on a machine we cannot fully interrogate.
    """
    flags = _cpu_flags()
    try:
        disk_free = shutil.disk_usage(disk_path).free
    except OSError:
        disk_free = 0

    gpu = _nvidia_gpu()
    if not gpu.get("usable") and Path("/sys/class/kfd").exists():
        # Detect it so the picker can say "AMD GPU seen, not supported by this
        # build" instead of pretending the machine has no accelerator.
        gpu = {"vendor": "amd", "usable": False, "vram_bytes": 0,
               "reason": "AMD GPU detected; this appliance build ships an NVIDIA CUDA backend only"}

    return {
        "ram_bytes": _memtotal_bytes(),
        "cpu_count": os.cpu_count() or 0,
        "avx2": "avx2" in flags,
        "avx512": "avx512f" in flags,
        "disk_free_bytes": disk_free,
        "gpu": gpu,
    }


def describe_hardware(hardware: dict) -> str:
    """One-line summary for the read-only strip above the picker."""
    parts = [f"{ram_gb(hardware.get('ram_bytes', 0))} RAM",
             f"{hardware.get('cpu_count', 0)} CPU threads"]
    if hardware.get("avx512"):
        parts.append("AVX-512")
    elif hardware.get("avx2"):
        parts.append("AVX2")
    else:
        parts.append("no AVX2 (slow inference)")
    gpu = hardware.get("gpu") or {}
    if gpu.get("usable"):
        parts.append(f"{gpu.get('name', 'GPU')} {ram_gb(gpu.get('vram_bytes', 0))} VRAM")
    elif gpu.get("vendor") == "amd":
        parts.append("AMD GPU (unsupported)")
    else:
        parts.append("no usable GPU")
    return " · ".join(parts)


# --------------------------------------------------------------------------
# backend + fit
# --------------------------------------------------------------------------

def select_backend(catalogue: dict, hardware: dict, prefer_cpu: bool = False) -> str:
    """Pick the richest backend this box can actually load.

    Thresholds come from each backend's min_driver in the catalogue, so adding
    a CUDA 14 tier is a data change. The newest satisfied tier wins, which is
    what makes a r580+ host take 13.4 while a r535 host takes 12.8.
    """
    if prefer_cpu:
        return "cpu"
    gpu = hardware.get("gpu") or {}
    if not gpu.get("usable"):
        return "cpu"
    driver = gpu.get("driver_major") or 0
    eligible = [
        (int(spec.get("min_driver", 0)), backend_id)
        for backend_id, spec in catalogue.get("backends", {}).items()
        if spec.get("gpu") and driver >= int(spec.get("min_driver", 0))
    ]
    if not eligible:
        return "cpu"
    return max(eligible)[1]


def backend_reason(catalogue: dict, hardware: dict, backend_id: str) -> str:
    """Why the chosen backend is what it is, for display under the picker."""
    gpu = hardware.get("gpu") or {}
    backend = backend_by_id(catalogue, backend_id) or {}
    if backend_id == "cpu":
        if gpu.get("usable"):
            return f"CPU only (driver {gpu.get('driver_major', '?')} below this backend's minimum)"
        return gpu.get("reason") or "CPU only"
    return f"{backend.get('label', backend_id)} on {gpu.get('name', 'GPU')}"


def estimate_ram(model: dict, catalogue: dict) -> int:
    ctx = int(catalogue.get("context_size", 8192))
    return int(model["size"]) + int(model["kv_bytes_per_token"]) * ctx \
        + int(catalogue.get("overhead_bytes", 0))


def estimate_vram(model: dict, catalogue: dict) -> int:
    """VRAM for full offload: weights + KV, no OS overhead.

    This is the real gate for any GPU path. The catalogue's min_vram is the
    operator-declared floor, which for the large models is set to this same
    figure; for the small ones it is 0, meaning "a GPU is optional" -- and that
    must not be read as "any GPU will do", or a 2 GB card would be offered full
    offload of a 2.5 GB model.
    """
    ctx = int(catalogue.get("context_size", 8192))
    return int(model["size"]) + int(model["kv_bytes_per_token"]) * ctx


def evaluate_models(catalogue: dict, hardware: dict, backend_id: str) -> list[dict]:
    """Annotate every model with whether it fits here, and how.

    Returns a list sorted smallest first. Exactly one entry is marked
    recommended: the largest that fits, because within a fixed box the biggest
    model that fits is the one the operator actually wants.
    """
    ram = hardware.get("ram_bytes", 0)
    vram = (hardware.get("gpu") or {}).get("vram_bytes", 0) or 0
    disk_free = hardware.get("disk_free_bytes", 0)
    gpu_ok = backend_id != "cpu"
    results = []

    for model in models(catalogue):
        size = int(model["size"])
        need_ram = estimate_ram(model, catalogue)
        need_vram = max(int(model.get("min_vram", 0) or 0), estimate_vram(model, catalogue))
        ram_ok = bool(ram) and ram >= int(model["min_ram"])
        # Two separate tests: enough RAM to hold it, and small enough that the
        # CPU can actually stream it at a usable rate.
        cpu_speed_ok = size <= int(ram * CPU_WEIGHT_FRACTION)
        fits_cpu = ram_ok and cpu_speed_ok
        fits_gpu = gpu_ok and bool(vram) and vram >= need_vram
        need_disk = size + backend_download_bytes(catalogue, backend_id) + DISK_SLACK_BYTES
        fits_disk = bool(disk_free) and disk_free >= need_disk
        fits = (fits_cpu or fits_gpu) and fits_disk

        reasons = []
        notes = []
        if not (fits_cpu or fits_gpu):
            if gpu_ok:
                reasons.append(f"needs {ram_gb(need_vram)} VRAM, this GPU has {ram_gb(vram)}")
            elif not ram_ok:
                reasons.append(f"needs ~{ram_gb(int(model['min_ram']))} RAM, this VM has {ram_gb(ram)}")
            else:
                reasons.append(
                    f"its {human_bytes(size)} of weights would not stream at a usable rate "
                    f"from {ram_gb(ram)} of RAM on the CPU; a GPU would lift this")
        elif gpu_ok and not fits_gpu and fits_cpu:
            notes.append("This GPU is too small to hold it, so it will run on the CPU.")
        elif not gpu_ok and size >= SLOW_CPU_WARNING_BYTES:
            notes.append("No GPU detected, so generation will be slow.")
        if not fits_disk:
            reasons.append(f"needs {human_bytes(need_disk)} free disk, {human_bytes(disk_free)} available")

        results.append({
            "id": model["id"],
            "alias": model["alias"],
            "label": model["label"],
            "summary": model.get("summary", ""),
            "size": size,
            "size_human": human_bytes(size),
            "disk_human": human_bytes(need_disk),
            "ram_human": ram_gb(int(model["min_ram"])),
            "vram_human": ram_gb(need_vram),
            "placement": "gpu" if fits_gpu else "cpu",
            "fits": fits,
            "reasons": reasons,
            "notes": notes,
            "recommended": False,
        })

    fitting = [r for r in results if r["fits"]]
    if fitting:
        largest = max(fitting, key=lambda r: r["size"])
        largest["recommended"] = True
    return results
