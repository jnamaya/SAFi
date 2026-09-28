"""Pure-logic tests for the appliance local-model catalogue and hardware probe.

safi_local.py is stdlib-only appliance code that lives outside the app package,
so it is loaded here by path rather than imported normally. That is the same
importlib mechanism safi-browser-setup.py uses at runtime.
"""
import importlib.util
import json
from pathlib import Path

import pytest

STAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "deploy/iso/config/includes.chroot/usr/local/sbin/safi-appliance-stage"
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, STAGE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safi_local = _load("safi_local_under_test", "safi_local.py")


@pytest.fixture
def catalogue():
    return safi_local.load_catalogue(STAGE_DIR / "local-models.json")


def _hw(ram=0, vram=0, disk=500 << 30, driver=None, usable=False, vendor=None):
    return {
        "ram_bytes": ram,
        "cpu_count": 8,
        "avx2": True,
        "avx512": True,
        "disk_free_bytes": disk,
        "gpu": {"vendor": vendor, "usable": usable, "vram_bytes": vram,
                "driver_major": driver, "name": "test gpu", "reason": ""},
    }


# --------------------------------------------------------------------------
# catalogue integrity
# --------------------------------------------------------------------------

def test_every_model_is_fully_pinned(catalogue):
    for model in catalogue["models"]:
        assert model["url"].startswith("https://"), model["id"]
        assert len(model["sha256"]) == 64, model["id"]
        assert int(model["sha256"], 16) >= 0, model["id"]
        assert model["size"] > 0, model["id"]
        assert model["alias"].startswith("safi-"), model["id"]
        assert model["kv_bytes_per_token"] > 0, model["id"]


def test_every_backend_asset_is_fully_pinned(catalogue):
    for backend_id, backend in catalogue["backends"].items():
        for asset in backend["assets"]:
            assert asset["url"].startswith("https://"), backend_id
            assert len(asset["sha256"]) == 64, (backend_id, asset["name"])
            assert asset["size"] > 0, (backend_id, asset["name"])


def test_model_ids_and_aliases_are_unique(catalogue):
    ids = [m["id"] for m in catalogue["models"]]
    aliases = [m["alias"] for m in catalogue["models"]]
    assert len(ids) == len(set(ids))
    assert len(aliases) == len(set(aliases))


def test_every_backend_carries_an_id_matching_its_key(catalogue):
    # safi-model-fetch reports the chosen backend into the status file with
    # backend["id"]. A backend spec without one crashes every fetch at the first
    # progress write, which is how this was originally found.
    for key, backend in catalogue["backends"].items():
        assert backend["id"] == key


def test_qwen3_0_6b_is_retired_not_offered(catalogue):
    # It leaked the reflection contract 6/6 and used a real tool 0/6. It must
    # not creep back into the picker as a "small" option.
    assert "qwen3-0.6b" not in [m["id"] for m in catalogue["models"]]
    assert "qwen3-0.6b" in catalogue["retired"]


def test_cpu_backend_ships_on_the_iso(catalogue):
    assert catalogue["backends"]["cpu"]["on_iso"] is True
    assert safi_local.backend_download_bytes(catalogue, "cpu") == 0


def test_cuda_backend_downloads_both_archives(catalogue):
    # llama.cpp split cudart out of the server archive. Fetching only the
    # server yields a ggml-cuda.so that cannot resolve libcudart and fails at
    # the first GPU layer load, so both must be counted.
    assets = catalogue["backends"]["cuda-12.8"]["assets"]
    assert len(assets) == 2
    assert any("cudart-" in a["url"] for a in assets)
    assert any("cudart-" not in a["url"] for a in assets)
    total = safi_local.backend_download_bytes(catalogue, "cuda-12.8")
    assert total > 700_000_000


# --------------------------------------------------------------------------
# backend selection
# --------------------------------------------------------------------------

def test_no_gpu_selects_cpu(catalogue):
    assert safi_local.select_backend(catalogue, _hw(ram=16 << 30)) == "cpu"


def test_old_driver_falls_back_to_cpu(catalogue):
    hw = _hw(vram=24 << 30, driver=525 - 1, usable=True, vendor="nvidia")
    assert safi_local.select_backend(catalogue, hw) == "cpu"


def test_mid_driver_selects_cuda_12_8(catalogue):
    hw = _hw(vram=24 << 30, driver=535, usable=True, vendor="nvidia")
    assert safi_local.select_backend(catalogue, hw) == "cuda-12.8"


def test_new_driver_selects_cuda_13_4(catalogue):
    hw = _hw(vram=24 << 30, driver=580, usable=True, vendor="nvidia")
    assert safi_local.select_backend(catalogue, hw) == "cuda-13.4"


def test_brand_new_driver_takes_the_newest_tier(catalogue):
    hw = _hw(vram=80 << 30, driver=595, usable=True, vendor="nvidia")
    assert safi_local.select_backend(catalogue, hw) == "cuda-13.4"


def test_prefer_cpu_overrides_a_usable_gpu(catalogue):
    hw = _hw(vram=24 << 30, driver=580, usable=True, vendor="nvidia")
    assert safi_local.select_backend(catalogue, hw, prefer_cpu=True) == "cpu"


def test_broken_nvidia_driver_is_not_treated_as_cpu_only_quietly(catalogue):
    hw = _hw(vram=24 << 30, driver=None, usable=False, vendor="nvidia")
    hw["gpu"]["reason"] = "nvidia-smi timed out; the GPU driver is not responding"
    assert safi_local.select_backend(catalogue, hw) == "cpu"
    assert "not responding" in safi_local.backend_reason(catalogue, hw, "cpu")


# --------------------------------------------------------------------------
# fit evaluation
# --------------------------------------------------------------------------

def test_4b_is_the_recommendation_on_a_small_vm(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=8 << 30), "cpu")}
    assert results["qwen3-4b"]["recommended"] is True
    assert results["qwen3-4b"]["fits"] is True


def test_a_cpu_box_is_not_offered_a_model_it_cannot_stream(catalogue):
    # 32 GiB of RAM can hold the 32B's 19.8 GB of weights, but CPU generation
    # re-reads the whole weight file per token. Recommending it here would be
    # technically true and practically useless.
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=32 << 30), "cpu")}
    assert results["qwen3-32b"]["fits"] is False
    assert results["qwen3-14b"]["recommended"] is True
    assert "would not stream at a usable rate" in results["qwen3-32b"]["reasons"][0]


def test_a_gpu_lifts_the_cpu_speed_ceiling(catalogue):
    # Same RAM as above, but a card that can hold the 32B.
    hw = _hw(ram=32 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-32b"]["fits"] is True
    assert results["qwen3-32b"]["recommended"] is True


def test_a_very_large_cpu_box_may_still_offer_the_32b(catalogue):
    # The ceiling is a fraction of RAM, so a genuinely huge box is not blocked
    # from choosing the largest model.
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=96 << 30), "cpu")}
    assert results["qwen3-32b"]["fits"] is True


def test_cpu_only_large_models_are_flagged_as_slow(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=64 << 30), "cpu")}
    assert any("generation will be slow" in note
               for note in results["qwen3-14b"]["notes"])
    # The 4B is small enough that the warning would just be noise.
    assert not any("generation will be slow" in note
                   for note in results["qwen3-4b"]["notes"])


def test_a_gpu_box_does_not_carry_the_slow_cpu_warning(catalogue):
    hw = _hw(ram=32 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert not any("generation will be slow" in note
                   for note in results["qwen3-32b"]["notes"])


def test_8b_is_the_recommendation_on_a_12g_vm(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=12 << 30), "cpu")}
    assert results["qwen3-8b"]["recommended"] is True


def test_too_small_a_vm_recommends_nothing_and_explains(catalogue):
    results = safi_local.evaluate_models(catalogue, _hw(ram=3 << 30), "cpu")
    assert not any(r["recommended"] for r in results)
    assert all(not r["fits"] for r in results)
    assert all(r["reasons"] for r in results)
    assert "RAM" in results[0]["reasons"][0]


def test_32b_does_not_fit_a_cpu_vm_of_ordinary_size(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=16 << 30), "cpu")}
    assert results["qwen3-32b"]["fits"] is False
    # With no usable GPU the useful thing to say is the RAM shortfall; "needs
    # 20.4 GiB VRAM, this GPU has 0.0 GiB" would just be noise.
    assert any("RAM" in reason for reason in results["qwen3-32b"]["reasons"])


def test_32b_fits_a_24gb_gpu_and_becomes_recommended(catalogue):
    hw = _hw(ram=32 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-32b"]["fits"] is True
    assert results["qwen3-32b"]["recommended"] is True
    # Plenty of RAM also fits it, but a GPU box must offload -- otherwise the
    # operator paid 765 MB for a CUDA backend and watched it sit idle.
    assert results["qwen3-32b"]["placement"] == "gpu"


def test_32b_falls_back_to_cpu_when_the_card_is_too_small(catalogue):
    # 64 GB of RAM holds the 32B, but a 16 GB card cannot offload it. That is
    # exactly the "effectively GPU-only" case, so it must be called out.
    hw = _hw(ram=64 << 30, vram=16 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-32b"]["fits"] is True
    assert results["qwen3-32b"]["placement"] == "cpu"
    assert any("run on the CPU" in note for note in results["qwen3-32b"]["notes"])


def test_32b_does_not_fit_with_neither_capacity(catalogue):
    hw = _hw(ram=16 << 30, vram=16 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-32b"]["fits"] is False
    assert any("VRAM" in reason for reason in results["qwen3-32b"]["reasons"])
    # A 16 GB card still leaves a sensible recommendation behind.
    assert results["qwen3-14b"]["recommended"] is True


def test_a_tiny_gpu_never_gets_full_offload_of_a_larger_model(catalogue):
    # min_vram 0 means "a GPU is optional", not "any GPU will do": a 2 GB card
    # must not be offered offload of a 2.5 GB model.
    hw = _hw(ram=16 << 30, vram=2 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-4b"]["fits"] is True
    assert results["qwen3-4b"]["placement"] == "cpu"
    assert any("run on the CPU" in note for note in results["qwen3-4b"]["notes"])


def test_insufficient_disk_rejects_even_a_ram_capable_model(catalogue):
    results = {r["id"]: r for r in safi_local.evaluate_models(
        catalogue, _hw(ram=64 << 30, disk=1 << 30), "cpu")}
    assert all(not r["fits"] for r in results.values())
    assert all(any("disk" in reason for reason in r["reasons"])
               for r in results.values())


def test_cuda_backend_inflates_the_disk_requirement(catalogue):
    cpu = {r["id"]: r for r in
           safi_local.evaluate_models(catalogue, _hw(ram=64 << 30), "cpu")}
    gpu = {r["id"]: r for r in safi_local.evaluate_models(
        catalogue, _hw(ram=64 << 30, vram=24 << 30, driver=535, usable=True,
                       vendor="nvidia"),
        "cuda-12.8")}
    assert gpu["qwen3-8b"]["disk_human"] != cpu["qwen3-8b"]["disk_human"]


def test_estimated_ram_matches_weights_plus_kv_plus_overhead(catalogue):
    model = safi_local.model_by_id(catalogue, "qwen3-32b")
    expected = (model["size"]
                + model["kv_bytes_per_token"] * catalogue["context_size"]
                + catalogue["overhead_bytes"])
    assert safi_local.estimate_ram(model, catalogue) == expected


def test_kv_math_matches_llama_cpp_reported_values(catalogue):
    # 36 layers * 8 kv heads * 128 head_dim * 2 (K,V) * 2 (f16) = 147456.
    # llama.cpp reported 144 KiB/token for both Qwen3-0.6B(28L -> 114688) and
    # Qwen3-8B(36L -> 147456) at ctx 8192, so the formula is the right one.
    four = safi_local.model_by_id(catalogue, "qwen3-4b")
    eight = safi_local.model_by_id(catalogue, "qwen3-8b")
    assert four["kv_bytes_per_token"] == 147456
    assert eight["kv_bytes_per_token"] == 147456
    assert safi_local.model_by_id(catalogue, "qwen3-32b")["kv_bytes_per_token"] == 262144


def test_unknown_hardware_recommends_nothing_rather_than_guessing(catalogue):
    results = safi_local.evaluate_models(catalogue, _hw(ram=0, disk=0), "cpu")
    assert not any(r["recommended"] for r in results)
    assert not any(r["fits"] for r in results)


# --------------------------------------------------------------------------
# display helpers
# --------------------------------------------------------------------------

def test_human_bytes_uses_decimal_gigabytes(catalogue):
    model = safi_local.model_by_id(catalogue, "qwen3-8b")
    assert safi_local.human_bytes(model["size"]) == "5.0 GB"


def test_describe_hardware_surfaces_a_working_gpu():
    text = safi_local.describe_hardware(
        _hw(ram=32 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia"))
    assert "32.0 GiB RAM" in text
    assert "AVX-512" in text
    assert "test gpu" in text
    assert "24.0 GiB VRAM" in text


def test_describe_hardware_warns_when_avx2_is_missing():
    hw = _hw(ram=8 << 30)
    hw["avx2"] = False
    hw["avx512"] = False
    assert "no AVX2" in safi_local.describe_hardware(hw)


def test_catalogue_file_is_valid_json_on_its_own():
    raw = json.loads((STAGE_DIR / "local-models.json").read_text(encoding="utf-8"))
    assert raw["schema"] == 1
