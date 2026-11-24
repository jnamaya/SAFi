import importlib.util
import json
from pathlib import Path

import pytest

STAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "deploy/iso/config/includes.chroot/usr/local/sbin/safi-appliance-stage"
)
if not STAGE_DIR.is_dir():
    pytest.skip("appliance ISO build tree (deploy/iso) is not present", allow_module_level=True)


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
    for key, backend in catalogue["backends"].items():
        assert backend["id"] == key


def test_qwen3_0_6b_is_retired_not_offered(catalogue):
    assert "qwen3-0.6b" not in [m["id"] for m in catalogue["models"]]
    assert "qwen3-0.6b" in catalogue["retired"]


def test_cpu_backend_ships_on_the_iso(catalogue):
    assert catalogue["backends"]["cpu"]["on_iso"] is True
    assert safi_local.backend_download_bytes(catalogue, "cpu") == 0


def test_cuda_backend_downloads_both_archives(catalogue):
    assets = catalogue["backends"]["cuda-12.8"]["assets"]
    assert len(assets) == 2
    assert any("cudart-" in a["url"] for a in assets)
    assert any("cudart-" not in a["url"] for a in assets)
    total = safi_local.backend_download_bytes(catalogue, "cuda-12.8")
    assert total > 700_000_000


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


def _amd_hw(vram, carve=0):
    hw = _hw(vram=vram, driver=0, usable=True, vendor="amd")
    hw["gpu"]["name"] = "AMD Radeon 8060S"
    hw["gpu"]["carve_out_bytes"] = carve
    hw["gpu"]["ttm_pool_bytes"] = vram
    return hw


def test_amd_gpu_selects_vulkan(catalogue):
    hw = _amd_hw(vram=56 << 30)
    assert safi_local.select_backend(catalogue, hw) == "vulkan"


def test_amd_vulkan_backend_is_fully_pinned(catalogue):
    backend = catalogue["backends"]["vulkan"]
    assert backend["id"] == "vulkan"
    assert backend["on_iso"] is False
    assert backend["vendors"] == ["amd"]
    assert backend["home"] == "/opt/safi/vulkan"
    assets = backend["assets"]
    assert len(assets) == 1
    assert "vulkan" in assets[0]["url"]
    assert len(assets[0]["sha256"]) == 64
    assert assets[0]["size"] == 31346600
    assert safi_local.backend_download_bytes(catalogue, "vulkan") == assets[0]["size"]


def test_cuda_backends_are_scoped_to_nvidia_and_carry_a_home(catalogue):
    for key, backend in catalogue["backends"].items():
        if key.startswith("cuda"):
            assert backend["vendors"] == ["nvidia"], key
            assert backend["home"].startswith("/opt/safi/"), key
    assert catalogue["backends"]["cpu"]["home"] == "/opt/safi/bin"


def test_amd_gpu_is_not_offered_cuda(catalogue):
    hw = _amd_hw(vram=56 << 30)
    hw["gpu"]["driver_major"] = 595
    assert safi_local.select_backend(catalogue, hw) == "vulkan"


def test_huge_uma_carve_out_is_surfaced(catalogue):
    hw = _amd_hw(vram=32 << 30, carve=28 << 30)
    reason = safi_local.backend_reason(catalogue, hw, "vulkan")
    assert "UMA Frame Buffer" in reason
    assert "28 GiB" in reason


def test_qwen3_8_27b_is_the_amd_flagship(catalogue):
    entry = safi_local.model_by_id(catalogue, "qwen3.8-27b")
    assert entry["optimized_for"] == ["amd"]
    assert entry["llama_args"][:2] == ["--spec-type", "draft-mtp"]
    assert "-fa" in entry["llama_args"] and "-ctv" in entry["llama_args"]
    hw = _amd_hw(vram=56 << 30)
    hw2 = dict(hw)
    hw2["ram_bytes"] = 60 << 30
    hw2["disk_free_bytes"] = 100 << 30
    backend = safi_local.select_backend(catalogue, hw2)
    results = {r["id"]: r for r in safi_local.evaluate_models(catalogue, hw2, backend)}
    assert results["qwen3.8-27b"]["fits"] is True
    assert results["qwen3.8-27b"]["recommended"] is True


def test_flagship_does_not_override_small_vm_tuning(catalogue):
    hw = _hw(ram=8 << 30, disk=100 << 30)
    results = {r["id"]: r for r in safi_local.evaluate_models(catalogue, hw, "cpu")}
    assert results["qwen3.8-27b"]["fits"] is False
    recommended = [r["id"] for r in results.values() if r["recommended"]]
    assert recommended == ["qwen3-4b"]


def test_4b_is_the_recommendation_on_a_small_vm(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=8 << 30), "cpu")}
    assert results["qwen3-4b"]["recommended"] is True
    assert results["qwen3-4b"]["fits"] is True


def test_a_cpu_box_is_not_offered_a_model_it_cannot_stream(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=32 << 30), "cpu")}
    assert results["qwen3-32b"]["fits"] is False
    assert results["qwen3-14b"]["recommended"] is True
    assert "would not stream at a usable rate" in results["qwen3-32b"]["reasons"][0]


def test_a_gpu_lifts_the_cpu_speed_ceiling(catalogue):
    hw = _hw(ram=32 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-32b"]["fits"] is True
    assert results["qwen3-32b"]["recommended"] is True


def test_a_very_large_cpu_box_may_still_offer_the_32b(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=96 << 30), "cpu")}
    assert results["qwen3-32b"]["fits"] is True


def test_cpu_only_large_models_are_flagged_as_slow(catalogue):
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, _hw(ram=64 << 30), "cpu")}
    assert any("generation will be slow" in note
               for note in results["qwen3-14b"]["notes"])
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
    assert any("RAM" in reason for reason in results["qwen3-32b"]["reasons"])


def test_32b_fits_a_24gb_gpu_and_becomes_recommended(catalogue):
    hw = _hw(ram=32 << 30, vram=24 << 30, driver=535, usable=True, vendor="nvidia")
    results = {r["id"]: r for r in
               safi_local.evaluate_models(catalogue, hw, "cuda-12.8")}
    assert results["qwen3-32b"]["fits"] is True
    assert results["qwen3-32b"]["recommended"] is True
    assert results["qwen3-32b"]["placement"] == "gpu"


def test_32b_falls_back_to_cpu_when_the_card_is_too_small(catalogue):
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
    assert results["qwen3-14b"]["recommended"] is True


def test_a_tiny_gpu_never_gets_full_offload_of_a_larger_model(catalogue):
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
    four = safi_local.model_by_id(catalogue, "qwen3-4b")
    eight = safi_local.model_by_id(catalogue, "qwen3-8b")
    assert four["kv_bytes_per_token"] == 147456
    assert eight["kv_bytes_per_token"] == 147456
    assert safi_local.model_by_id(catalogue, "qwen3-32b")["kv_bytes_per_token"] == 262144


def test_unknown_hardware_recommends_nothing_rather_than_guessing(catalogue):
    results = safi_local.evaluate_models(catalogue, _hw(ram=0, disk=0), "cpu")
    assert not any(r["recommended"] for r in results)
    assert not any(r["fits"] for r in results)


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
