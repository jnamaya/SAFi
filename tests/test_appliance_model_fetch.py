"""Tests for safi-model-fetch, the appliance-side model downloader.

safi-model-fetch has no .py extension and lives outside the app package, so it is
loaded by path. The import inside it resolves safi_local from
/usr/local/lib/safi_local.py, which does not exist on a build host, so
SAFI_LOCAL_MODULE is pointed at the staged source before loading.
"""
import hashlib
import importlib.util
import json
import os
import tarfile
from pathlib import Path

import pytest

STAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "deploy/iso/config/includes.chroot/usr/local/sbin"
)
SBIN_DIR = Path(__file__).resolve().parents[1] / "deploy/iso/config/includes.chroot/usr/local/sbin"
FETCH_PATH = STAGE_DIR / "safi-model-fetch"
CATALOGUE = STAGE_DIR / "safi-appliance-stage/local-models.json"
LOCAL_MODULE = STAGE_DIR / "safi-appliance-stage/safi_local.py"

os.environ.setdefault("SAFI_LOCAL_MODULE", str(LOCAL_MODULE))


def _load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safi_local = _load("safi_local_for_fetch", LOCAL_MODULE)
fetch = _load("safi_model_fetch_under_test", FETCH_PATH)


@pytest.fixture
def catalogue():
    return safi_local.load_catalogue(CATALOGUE)


def _stage_jev_bundle(catalogue, root: Path) -> Path:
    """Put a complete, correctly-sized bundle on disk without downloading it.

    Sparse files: the real bundle is 1.7 GB and every test here is about control
    flow, not about 1.7 GB of zeroes. installed_jev_dir() checks size, which is
    the same check it makes against a real install.
    """
    catalogue = dict(catalogue, model_root=str(root))
    target = safi_local.jev_local_dir(catalogue)
    for entry in safi_local.jev_local(catalogue)["files"]:
        path = target / entry["name"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as handle:
            handle.truncate(int(entry["size"]))
    return target


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def test_cpu_plan_is_the_model_alone(catalogue):
    model = safi_local.model_by_id(catalogue, "qwen3-8b")
    plan = fetch.build_plan(catalogue, model, catalogue["backends"]["cpu"])
    assert [s["kind"] for s in plan] == ["model"]
    assert plan[0]["sha256"] == model["sha256"]


def test_cuda_plan_fetches_backend_assets_before_the_weights(catalogue):
    model = safi_local.model_by_id(catalogue, "qwen3-32b")
    plan = fetch.build_plan(catalogue, model, catalogue["backends"]["cuda-12.8"])
    kinds = [s["kind"] for s in plan]
    assert kinds == ["backend", "backend", "model"]
    assert plan[-1]["size"] == model["size"]


def test_every_step_carries_a_digest(catalogue):
    for backend_id in catalogue["backends"]:
        model = safi_local.model_by_id(catalogue, "qwen3-4b")
        for step in fetch.build_plan(catalogue, model, catalogue["backends"][backend_id]):
            assert len(step["sha256"]) == 64, step["name"]
            assert step["size"] > 0, step["name"]
            assert step["url"].startswith("https://"), step["name"]


def test_plan_total_matches_the_sum_of_steps(catalogue):
    model = safi_local.model_by_id(catalogue, "qwen3-8b")
    plan = fetch.build_plan(catalogue, model, catalogue["backends"]["cuda-12.8"])
    assert fetch.plan_total_bytes(plan) == sum(s["size"] for s in plan)


def test_gpu_boxes_are_asked_to_download_the_full_cuda_pair(catalogue):
    # 171 MB would be the wrong number to show an operator: the cudart archive
    # is what makes the backend loadable.
    model = safi_local.model_by_id(catalogue, "qwen3-32b")
    plan = fetch.build_plan(catalogue, model, catalogue["backends"]["cuda-12.8"])
    assert fetch.plan_total_bytes(plan) > model["size"] + 700_000_000


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def test_verify_accepts_a_matching_digest(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"safi" * 1000)
    fetch.verify(blob, hashlib.sha256(blob.read_bytes()).hexdigest())


def test_verify_rejects_and_deletes_a_corrupt_file(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"corrupt")
    with pytest.raises(fetch.FetchError) as exc:
        fetch.verify(blob, "0" * 64)
    assert "checksum mismatch" in str(exc.value)
    # Kept, the next attempt would resume onto the corrupt prefix and fail
    # forever.
    assert not blob.exists()


def test_sha256_file_matches_hashlib(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(os.urandom(3_000_000))
    assert fetch.sha256_file(blob) == hashlib.sha256(blob.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# unit + env rendering
# --------------------------------------------------------------------------

def test_cpu_unit_pins_the_cpu_binary_and_zero_gpu_layers(catalogue):
    env = fetch.render_env_file(catalogue, catalogue["backends"]["cpu"])
    assert "SAFI_LOCAL_MODEL_GPU_LAYERS=0" in env
    assert "SAFI_LOCAL_MODEL_CONTEXT=8192" in env

    unit = fetch.render_unit("/opt/safi/bin/llama-server", "/opt/safi/bin",
                             "/var/lib/safi/models/qwen3-8b/x.gguf", "safi-qwen3-8b")
    assert "ExecStart=/opt/safi/bin/llama-server" in unit
    assert "LD_LIBRARY_PATH=/opt/safi/bin" in unit
    assert "--alias safi-qwen3-8b" in unit
    assert "--host 127.0.0.1" in unit


def test_threads_is_a_physical_core_count_never_the_all_logical_default(catalogue):
    # 0 would mean "every logical CPU". On an SMT host llama.cpp hands the work
    # to sibling cores that share one physical core's FP units, which measured
    # at roughly half the decode throughput of the physical core count on the
    # 12-core/16-thread development host.
    env = fetch.render_env_file(catalogue, catalogue["backends"]["cpu"])
    threads = int(
        next(l for l in env.splitlines() if l.startswith("SAFI_LOCAL_MODEL_THREADS=")).split("=")[1]
    )
    assert threads >= 1
    assert f"SAFI_LOCAL_MODEL_THREADS={threads}" in env
    assert "SAFI_LOCAL_MODEL_THREADS=0\n" not in env


def test_physical_core_count_never_exceeds_the_logical_count_and_never_zero():
    count = fetch.physical_core_count()
    assert 1 <= count <= (os.cpu_count() or 1)


def test_physical_core_count_falls_back_when_sysfs_has_no_topology(monkeypatch):
    # Containers and some virtualised guests expose no thread_siblings_list.
    # Degrading to the logical count is the old behaviour, so a missing
    # topology tree must not raise or invent a core.
    import pathlib

    monkeypatch.setattr(pathlib.Path, "glob", lambda self, pat: iter(()))
    monkeypatch.setattr(fetch.os, "cpu_count", lambda: 8)
    assert fetch.physical_core_count() == 8

    monkeypatch.setattr(fetch.os, "cpu_count", lambda: None)
    assert fetch.physical_core_count() == 1


def test_cuda_unit_points_at_the_cuda_tree_and_offloads_everything(catalogue):
    env = fetch.render_env_file(catalogue, catalogue["backends"]["cuda-12.8"])
    assert "SAFI_LOCAL_MODEL_GPU_LAYERS=99" in env

    unit = fetch.render_unit("/opt/safi/cuda/llama-server", "/opt/safi/cuda",
                             "/var/lib/safi/models/qwen3-32b/y.gguf", "safi-qwen3-32b")
    assert "ExecStart=/opt/safi/cuda/llama-server" in unit
    assert "LD_LIBRARY_PATH=/opt/safi/cuda" in unit
    assert "--n-gpu-layers ${SAFI_LOCAL_MODEL_GPU_LAYERS}" in unit


def test_unit_keeps_the_loopback_only_posture(catalogue):
    unit = fetch.render_unit("/opt/safi/bin/llama-server", "/opt/safi/bin", "/m.gguf", "a")
    assert "--host 127.0.0.1" in unit
    assert "--port 8081" in unit
    assert "0.0.0.0" not in unit


def test_unit_alias_is_the_detect_provider_prefix(catalogue):
    # Phase 1 made detect_provider route the whole safi- prefix to local. A unit
    # published under any other alias would silently be sent to groq.
    for model_id in ("qwen3-4b", "qwen3-8b", "qwen3-14b", "qwen3-32b"):
        model = safi_local.model_by_id(catalogue, model_id)
        assert model["alias"].startswith("safi-")
        unit = fetch.render_unit("/b", "/l", "/m.gguf", model["alias"])
        assert f"--alias {model['alias']}" in unit


def test_unit_keeps_a_readiness_probe(catalogue):
    # A 20 GB model takes minutes to load; without the probe systemd reports
    # success for a server that is not answering yet.
    unit = fetch.render_unit("/b", "/l", "/m.gguf", "safi-qwen3-8b")
    assert "ExecStartPost=" in unit
    assert "/v1/models" in unit
    assert "TimeoutStartSec=900" in unit


def test_unit_expands_context_from_the_env_file(catalogue):
    unit = fetch.render_unit("/b", "/l", "/m.gguf", "safi-qwen3-8b")
    assert "EnvironmentFile=" in unit
    assert "--ctx-size ${SAFI_LOCAL_MODEL_CONTEXT}" in unit
    assert "--reasoning off" in unit


# --------------------------------------------------------------------------
# backend install
# --------------------------------------------------------------------------

def _make_archive(path: Path, layout: dict) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, content in layout.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, __import__("io").BytesIO(content))
    return path


def test_install_backend_flattens_server_and_libraries(tmp_path):
    archive = _make_archive(tmp_path / "llama.tar.gz", {
        "build/bin/llama-server": b"#!/bin/false\n",
        "build/bin/libllama.so": b"libllama",
        "build/bin/libggml-cpu-haswell.so": b"ggml",
    })
    dest = tmp_path / "out"
    fetch.install_backend(archive, dest)
    assert (dest / "llama-server").exists()
    assert (dest / "libllama.so").exists()
    assert (dest / "libggml-cpu-haswell.so").exists()
    assert not (dest / "build").exists()


def test_install_backend_collects_libraries_from_a_sibling_tree(tmp_path):
    # The cudart archive is a separate tarball and may not put libcudart
    # next to the server, so every .so under the archive has to be collected.
    archive = _make_archive(tmp_path / "cudart.tar.gz", {
        "build/bin/llama-server": b"server",
        "build/lib/libcudart.so.12": b"cudart",
        "build/lib/libcublas.so.13": b"cublas",
    })
    dest = tmp_path / "out"
    fetch.install_backend(archive, dest)
    assert (dest / "libcudart.so.12").exists()
    assert (dest / "libcublas.so.13").exists()


def test_install_backend_fails_loudly_on_an_unexpected_layout(tmp_path):
    archive = _make_archive(tmp_path / "wrong.tar.gz", {"README": b"no server here"})
    with pytest.raises(fetch.FetchError) as exc:
        fetch.install_backend(archive, tmp_path / "out")
    assert "llama-server" in str(exc.value)


def test_install_backend_refuses_a_traversal_path(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("../../etc/pwned")
        info.size = 3
        tar.addfile(info, __import__("io").BytesIO(b"bad"))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.install_backend(archive, tmp_path / "out")
    assert "unsafe path" in str(exc.value)


# --------------------------------------------------------------------------
# request handling
# --------------------------------------------------------------------------

def test_resolve_rejects_an_unknown_model(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text(json.dumps({"model": "gpt-4b", "backend": "cpu"}))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.resolve(fetch.argparse.Namespace(model=None, backend=None), catalogue)
    assert "unknown model id" in str(exc.value)


def test_resolve_rejects_an_unknown_backend(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text(json.dumps({"model": "qwen3-8b", "backend": "rocm"}))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.resolve(fetch.argparse.Namespace(model=None, backend=None), catalogue)
    assert "unknown backend id" in str(exc.value)


def test_resolve_prefers_explicit_arguments_over_the_choice_file(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text(json.dumps({"model": "qwen3-4b", "backend": "cpu"}))
    model, backend = fetch.resolve(
        fetch.argparse.Namespace(model="qwen3-32b", backend="cuda-13.4"), catalogue)
    assert model["id"] == "qwen3-32b"
    assert backend["id"] == "cuda-13.4"


def test_resolve_reports_a_missing_choice_file(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "absent.json")
    with pytest.raises(fetch.FetchError) as exc:
        fetch.resolve(fetch.argparse.Namespace(model=None, backend=None), catalogue)
    assert "no model selection" in str(exc.value)


def test_download_choice_does_not_require_activation(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text(json.dumps({
        "model": "qwen3-8b", "backend": "cpu", "activate": False,
    }))
    model, backend = fetch.resolve(
        fetch.argparse.Namespace(model=None, backend=None), catalogue)
    assert model["id"] == "qwen3-8b"
    assert backend["id"] == "cpu"
    assert fetch.should_activate() is False


def test_a_fetch_without_an_activate_key_still_activates(catalogue, tmp_path, monkeypatch):
    # The setup wizard writes {"model", "backend"} with no activate key. That
    # is the first-boot path, and it must end with the model server running: a
    # default of False here left a downloaded model with no unit on disk.
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text(json.dumps({
        "model": "qwen3-8b", "backend": "cpu",
    }))
    assert fetch.should_activate() is True


def test_an_explicit_activate_true_activates(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text(json.dumps({
        "model": "qwen3-8b", "backend": "cpu", "activate": True,
    }))
    assert fetch.should_activate() is True


def test_resolve_rejects_corrupt_choice_json(catalogue, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "CHOICE_PATH", tmp_path / "choice.json")
    (tmp_path / "choice.json").write_text("{not json")
    with pytest.raises(fetch.FetchError) as exc:
        fetch.resolve(fetch.argparse.Namespace(model=None, backend=None), catalogue)
    assert "not valid JSON" in str(exc.value)


# --------------------------------------------------------------------------
# re-activation must not re-download
# --------------------------------------------------------------------------

def test_an_installed_model_is_recognised(catalogue, tmp_path):
    model = safi_local.model_by_id(catalogue, "phi4-mini")
    target = tmp_path / model["id"] / model["file"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\0" * 4)
    # A short file is not an installed model.
    catalogue = dict(catalogue, model_root=str(tmp_path))
    assert fetch.installed_model_path(model, catalogue) is None

    with open(target, "wb") as handle:  # sparse stand-in for 2.5 GB
        handle.truncate(int(model["size"]))
    assert fetch.installed_model_path(model, catalogue) == target


def test_a_short_or_missing_file_is_not_treated_as_installed(catalogue, tmp_path):
    model = safi_local.model_by_id(catalogue, "qwen3-4b")
    catalogue = dict(catalogue, model_root=str(tmp_path))
    assert fetch.installed_model_path(model, catalogue) is None


def test_activating_an_already_downloaded_model_downloads_nothing(tmp_path, monkeypatch):
    """The bug: install_model() moves the cache file away, so every switch back
    to a model re-fetched the full weights. The installed path must short-circuit
    the download step, and activation must still happen."""
    catalogue = safi_local.load_catalogue(CATALOGUE)
    model = safi_local.model_by_id(catalogue, "phi4-mini")
    root = tmp_path / "models"
    target = root / model["id"] / model["file"]
    target.parent.mkdir(parents=True)
    # A sparse file stands in for 2.5 GB of weights.
    with open(target, "wb") as handle:
        handle.truncate(int(model["size"]))
    catalogue = dict(catalogue, model_root=str(root))

    cache = tmp_path / "cache"
    cache.mkdir()
    status = tmp_path / "model-fetch.json"
    choice = tmp_path / "choice.json"
    choice.write_text(json.dumps({"model": "phi4-mini", "backend": "cpu",
                                  "activate": True}))
    unit = tmp_path / "safi-llama-server.service"
    env_file = tmp_path / "llama-server.env"

    monkeypatch.setattr(fetch.safi_local, "load_catalogue", lambda *a, **kw: catalogue)
    monkeypatch.setattr(fetch, "CACHE_DIR", cache)
    monkeypatch.setattr(fetch, "STATUS_PATH", status)
    monkeypatch.setattr(fetch, "CHOICE_PATH", choice)
    monkeypatch.setattr(fetch, "UNIT_PATH", unit)
    monkeypatch.setattr(fetch, "ENV_FILE", env_file)
    monkeypatch.setattr(fetch, "write_status",
                        lambda **kw: status.write_text(json.dumps(kw, default=str)))
    monkeypatch.setattr(fetch, "activate_unit", lambda: None)
    monkeypatch.setattr(fetch, "verify", lambda *a, **kw: None)
    cpu_home = tmp_path / "opt/bin"
    cpu_home.mkdir(parents=True)
    (cpu_home / "llama-server").write_text("#!/bin/sh\n")
    monkeypatch.setattr(fetch, "CPU_HOME", cpu_home)

    def _no_downloads(step, *a, **kw):
        raise AssertionError(f"re-activation must not download {step.get('name', step.get('kind'))}")

    monkeypatch.setattr(fetch, "download", _no_downloads)
    monkeypatch.setattr(fetch.shutil, "which", _no_downloads)
    # The local Jev bundle is a mandatory step of its own, so "already
    # downloaded" only means "downloaded nothing" when it too is on disk.
    _stage_jev_bundle(catalogue, root)

    rc = fetch.main(["--model", "phi4-mini", "--backend", "cpu"])
    assert rc == 0
    # Nothing was fetched, and the unit still points at the model.
    assert list(cache.iterdir()) == []
    body = unit.read_text()
    assert f"--alias {model['alias']}" in body
    assert model["file"] in body
    # The weights were left exactly where they were.
    assert target.exists()
    assert json.loads(status.read_text())["activated"] is True


def test_an_uninstalled_model_still_downloads(tmp_path, monkeypatch):
    catalogue = safi_local.load_catalogue(CATALOGUE)
    model = safi_local.model_by_id(catalogue, "phi4-mini")
    root = tmp_path / "models"
    root.mkdir()
    catalogue = dict(catalogue, model_root=str(root))

    cache = tmp_path / "cache"
    cache.mkdir()
    status = tmp_path / "model-fetch.json"
    choice = tmp_path / "choice.json"
    choice.write_text(json.dumps({"model": "phi4-mini", "backend": "cpu",
                                  "activate": False}))

    monkeypatch.setattr(fetch.safi_local, "load_catalogue", lambda *a, **kw: catalogue)
    monkeypatch.setattr(fetch, "CACHE_DIR", cache)
    monkeypatch.setattr(fetch, "STATUS_PATH", status)
    monkeypatch.setattr(fetch, "CHOICE_PATH", choice)
    monkeypatch.setattr(fetch, "UNIT_PATH", tmp_path / "safi-llama-server.service")
    monkeypatch.setattr(fetch, "ENV_FILE", tmp_path / "llama-server.env")
    monkeypatch.setattr(fetch, "write_status",
                        lambda **kw: status.write_text(json.dumps(kw, default=str)))
    monkeypatch.setattr(fetch, "verify", lambda *a, **kw: None)

    def _fake_download(step, progress):
        progress(step, step["size"])
        blob = cache / f"{step['sha256']}.part"
        blob.write_bytes(b"\0" * int(step["size"]))
        return blob

    monkeypatch.setattr(fetch, "download", _fake_download)

    rc = fetch.main(["--model", "phi4-mini", "--backend", "cpu"])
    assert rc == 0
    # The weights were fetched and installed, and nothing was activated.
    assert (root / model["id"] / model["file"]).exists()
    assert not (tmp_path / "safi-llama-server.service").exists()


# --------------------------------------------------------------------------
# status file
# --------------------------------------------------------------------------

def test_status_round_trips_and_survives_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "STATUS_PATH", tmp_path / "status.json")
    fetch.write_status(state="running", percent=42)
    assert fetch.read_status()["percent"] == 42
    # A poll must never see a half-written document, and a truncated file from
    # a power cut must not take the progress page down.
    (tmp_path / "status.json").write_text("{ truncated")
    assert fetch.read_status() == {}


def test_status_update_merges_rather_than_replaces(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "STATUS_PATH", tmp_path / "status.json")
    fetch.write_status(state="running", model="qwen3-32b", percent=10)
    fetch.write_status(percent=55)
    status = fetch.read_status()
    assert status["model"] == "qwen3-32b"
    assert status["percent"] == 55


# --------------------------------------------------------------------------
# install_model: where the weights actually land
# --------------------------------------------------------------------------
#
# This is the function that decides the on-disk layout, and it is the one the
# app's model picker reads back. Its path convention therefore has to come from
# the catalogue, not from a constant in either file.

def test_install_lands_the_weights_where_the_catalogue_says(catalogue, tmp_path):
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    model = next(m for m in catalogue["models"] if m["id"] == "qwen3-8b")
    cached = tmp_path / "cached.gguf"
    cached.write_bytes(b"weights")

    target = fetch.install_model(cached, model, payload)

    assert target == tmp_path / "models" / "qwen3-8b" / model["file"]
    assert target.read_bytes() == b"weights"
    assert not cached.exists(), "the partial must be moved, not copied"


def test_install_prefers_the_catalogue_filename_over_the_url(catalogue, tmp_path):
    # The catalogue states 'file'. Deriving it from the url would make the
    # picker and the downloader disagree the moment a model is republished
    # under a different asset name.
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    model = dict(next(m for m in catalogue["models"] if m["id"] == "qwen3-8b"))
    model["url"] = "https://huggingface.co/x/renamed-8B.gguf"
    model["file"] = "Qwen3-8B-Q4_K_M.gguf"
    cached = tmp_path / "cached.gguf"
    cached.write_bytes(b"weights")

    target = fetch.install_model(cached, model, payload)

    assert target.name == "Qwen3-8B-Q4_K_M.gguf"


def test_install_falls_back_to_the_url_when_the_catalogue_omits_file(catalogue, tmp_path):
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    model = dict(next(m for m in catalogue["models"] if m["id"] == "qwen3-8b"))
    model.pop("file")
    cached = tmp_path / "cached.gguf"
    cached.write_bytes(b"weights")

    target = fetch.install_model(cached, model, payload)

    assert target.name == Path(model["url"].split("?", 1)[0]).name


def test_install_is_safe_to_repeat(catalogue, tmp_path):
    # The wizard's retry button can re-run a fetch that already placed weights.
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    model = dict(next(m for m in catalogue["models"] if m["id"] == "qwen3-8b"), size=9)
    for _ in range(2):
        cached = tmp_path / "cached.gguf"
        cached.write_bytes(b"weights!!")
        target = fetch.install_model(cached, model, payload)
    assert target.read_bytes() == b"weights!!"
    assert target.stat().st_size == 9


def test_installed_weights_are_world_readable(catalogue, tmp_path):
    # The app runs as the safi user and reads this file to decide what to
    # offer, so it cannot be root-only.
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    model = next(m for m in catalogue["models"] if m["id"] == "qwen3-8b")
    cached = tmp_path / "cached.gguf"
    cached.write_bytes(b"weights")
    target = fetch.install_model(cached, model, payload)
    assert oct(target.stat().st_mode)[-3:] == "644"


def test_the_catalogue_layout_matches_what_the_app_reads(catalogue, tmp_path, monkeypatch):
    # The picker's presence check is <model_root>/<id>/<file> with an exact
    # size. If install_model wrote anywhere else, the picker would show nothing
    # after a successful download.
    from safi_app.core.services import provider_governance as pg
    from safi_app import config as cm

    # The fetcher has activated the model, so the app treats it as served.
    monkeypatch.setattr(cm, "active_local_model", lambda: "safi-qwen3-8b")
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    root = tmp_path / "models"
    root.mkdir()
    path = tmp_path / "local-models.json"
    path.write_text(json.dumps(payload))

    # A real 5 GB file is not needed to prove the paths agree; shrink the model
    # in the catalogue itself so the size check is meaningful.
    model = next(m for m in catalogue["models"] if m["id"] == "qwen3-8b")
    small = dict(model, size=len(b"weights"))
    payload["models"] = [small if m["id"] == "qwen3-8b" else m
                         for m in payload["models"]]
    path.write_text(json.dumps(payload))
    cached = tmp_path / "cached.gguf"
    cached.write_bytes(b"weights")
    fetch.install_model(cached, small, payload)

    offered = pg.installed_local_models(str(path))
    assert [m["id"] for m in offered] == [model["alias"]]


# --------------------------------------------------------------------------
# the local Jev bundle
# --------------------------------------------------------------------------
#
# Laya is what lets an appliance audit itself with no TypeSafe key and no
# internet. It is a five-file ONNX bundle rather than a GGUF, so it cannot go
# through the chat-model path: the fetcher would try to start a llama-server
# that cannot load it. These tests pin the bundle-specific contract: it is a
# mandatory step, it installs as one atomic unit, and it is digest-pinned.

def test_the_local_jev_bundle_is_not_offered_as_a_chat_model(catalogue):
    """It must not appear in the Intellect picker.

    A 1.7 GB encoder in that list would be selectable, and selecting it would
    produce a llama-server that cannot load the file -- a broken model choice
    that looks valid in the UI.
    """
    assert safi_local.jev_local(catalogue) is not None
    assert all(m["id"] != "laya" for m in catalogue["models"])
    assert "laya" not in [m.get("file") for m in catalogue["models"]]


def test_every_jev_file_is_digest_pinned_at_a_pinned_revision(catalogue):
    """Supply chain: a mutable ref would make the ISO unverifiable between builds.

    The revision is the exact commit Laya's release documents, so a rebuild
    cannot pick up different weights under the same version string.
    """
    block = safi_local.jev_local(catalogue)
    assert len(block["revision"]) == 40
    for entry in block["files"]:
        assert len(entry["sha256"]) == 64, entry["name"]
        assert entry["size"] > 0, entry["name"]
        assert entry["url"].startswith("https://"), entry["name"]
        assert block["revision"] in entry["url"], entry["name"]


def test_jev_files_are_ordered_smallest_first(catalogue):
    """A failure part-way through should leave the cheap files already verified."""
    sizes = [f["size"] for f in safi_local.jev_local_files(catalogue)]
    assert sizes == sorted(sizes)


def test_jev_install_path_is_a_sibling_of_the_chat_models(catalogue, tmp_path):
    """One model_root, two readers -- so the location is derived, not duplicated."""
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    jev_dir = safi_local.jev_local_dir(payload)
    assert jev_dir == tmp_path / "models" / "laya"
    assert jev_dir.parent == tmp_path / "models"


def test_jev_total_is_about_1_7_gb(catalogue):
    """Sanity on the pin: a mis-transcribed size would make the fetch unresumable."""
    total = safi_local.jev_local_bytes(catalogue)
    assert 1_600_000_000 < total < 1_800_000_000


def test_installed_jev_dir_is_none_when_the_bundle_is_absent(catalogue, tmp_path):
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    assert fetch.installed_jev_dir(payload) is None


def test_installed_jev_dir_is_none_when_any_file_is_short(catalogue, tmp_path):
    """A truncated weights file is the failure that matters most here.

    laya.onnx is a small graph that opens fine without its .data sibling, so
    "the ONNX file is present" is not a usable completeness test. Every pinned
    file has to be at full size.
    """
    root = _stage_jev_bundle(catalogue, tmp_path / "models")
    weights = root / "laya.onnx.data"
    with open(weights, "r+b") as handle:
        handle.truncate(1024)
    assert fetch.installed_jev_dir(dict(catalogue, model_root=str(tmp_path / "models"))) is None


def test_a_complete_bundle_is_recognised_as_installed(catalogue, tmp_path):
    _stage_jev_bundle(catalogue, tmp_path / "models")
    found = fetch.installed_jev_dir(dict(catalogue, model_root=str(tmp_path / "models")))
    assert found == tmp_path / "models" / "laya"


def test_install_jev_lands_every_file_where_the_catalogue_says(catalogue, tmp_path):
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    steps = []
    for entry in safi_local.jev_local_files(payload):
        cached = tmp_path / f"cached-{entry['name'].replace('/', '-')}"
        # Sparse to the pinned size so the post-install completeness check is
        # meaningful without writing 1.7 GB per test.
        with open(cached, "wb") as handle:
            handle.truncate(int(entry["size"]))
        steps.append((cached, entry))

    target = fetch.install_jev_local(steps, payload)

    assert target == tmp_path / "models" / "laya"
    for entry in safi_local.jev_local_files(payload):
        assert (target / entry["name"]).is_file()
    # The cache is emptied by moving, not by copying, so a 1.7 GB install does
    # not transiently need twice the disk.
    assert not list(tmp_path.glob("cached-*"))


def test_install_jev_is_all_or_nothing(catalogue, tmp_path):
    """The bundle is only coherent as a set, so the live path is renamed in one step.

    is_available() is a file-existence test: a half-populated directory at the
    live path would pass it and then fail on the missing weights file at the
    first governance turn, long after the operator's setup screen said "done".
    """
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    steps = []
    for entry in safi_local.jev_local_files(payload):
        cached = tmp_path / f"cached-{entry['name'].replace('/', '-')}"
        # Sparse to the pinned size so the post-install completeness check is
        # meaningful without writing 1.7 GB per test.
        with open(cached, "wb") as handle:
            handle.truncate(int(entry["size"]))
        steps.append((cached, entry))

    fetch.install_jev_local(steps, payload)
    assert fetch.installed_jev_dir(payload) is not None
    # No staging or backup directory is left behind to be mistaken for a bundle.
    root = tmp_path / "models"
    assert not (root / "laya.partial").exists()
    assert not (root / "laya.previous").exists()
    assert sorted(p.name for p in root.iterdir()) == ["laya"]


def test_a_failed_reinstall_restores_the_previous_bundle(catalogue, tmp_path, monkeypatch):
    """A rename that fails must not leave the live path empty.

    This is the failure that would be worst to debug: the operator sees setup
    report an error, but typed Conscience silently falls back to the hosted
    provider, which the ISO ships no key for. The next turn fails with a
    connection error that has nothing to do with the failed upgrade.
    """
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    for generation in (b"good", b"doomed"):
        steps = []
        for entry in safi_local.jev_local_files(payload):
            cached = tmp_path / f"cached-{generation}-{entry['name'].replace('/', '-')}"
            with open(cached, "wb") as handle:
                handle.write(generation)
                handle.truncate(int(entry["size"]))
            steps.append((cached, entry))
        if generation == b"good":
            fetch.install_jev_local(steps, payload)

    root = tmp_path / "models"
    assert fetch.installed_jev_dir(payload) is not None

    real_replace = os.replace

    def flaky(src, dst):
        # Fail only the staging -> live rename, after the old bundle was moved
        # aside. That is the window where the live path is momentarily empty.
        if Path(src).name == "laya.partial" and Path(dst).name == "laya":
            raise OSError(28, "No space left on device")
        return real_replace(src, dst)

    monkeypatch.setattr(fetch.os, "replace", flaky)
    steps = []
    for entry in safi_local.jev_local_files(payload):
        cached = tmp_path / f"cached-doomed-{entry['name'].replace('/', '-')}"
        with open(cached, "wb") as handle:
            handle.write(b"doomed")
            handle.truncate(int(entry["size"]))
        steps.append((cached, entry))

    with pytest.raises(fetch.FetchError):
        fetch.install_jev_local(steps, payload)
    monkeypatch.undo()

    # The previously verified bundle is serving again, not a hole.
    assert fetch.installed_jev_dir(payload) is not None
    # Sparse files, so compare the leading bytes rather than the whole 3.8 MB.
    assert (root / "laya" / "laya.onnx").read_bytes()[:4] == b"good"
    assert not (root / "laya.partial").exists()
    assert not (root / "laya.previous").exists()


def test_reinstalling_replaces_the_previous_bundle(catalogue, tmp_path):
    """A changed bundle must not leave two candidate directories on disk."""
    payload = dict(catalogue, model_root=str(tmp_path / "models"))
    for generation in (b"first", b"second"):
        steps = []
        for entry in safi_local.jev_local_files(payload):
            cached = tmp_path / f"cached-{generation}-{entry['name'].replace('/', '-')}"
            with open(cached, "wb") as handle:
                handle.write(generation)
                handle.truncate(int(entry["size"]))
            steps.append((cached, entry))
        fetch.install_jev_local(steps, payload)

    root = tmp_path / "models"
    assert sorted(p.name for p in root.iterdir()) == ["laya"]
    # Sparse files, so compare the leading bytes rather than the whole 3.8 MB.
    assert (root / "laya" / "laya.onnx").read_bytes()[:6] == b"second"


def test_a_first_boot_fetch_installs_the_jev_bundle(catalogue, tmp_path, monkeypatch):
    """End to end: the bundle is fetched, verified and installed with the model.

    This is the behaviour the appliance depends on -- an ISO that cannot audit
    itself offline is not a working appliance -- so it is tested through main()
    rather than by calling install_jev_local directly.
    """
    catalogue = dict(catalogue, model_root=str(tmp_path / "models"))
    model = next(m for m in catalogue["models"] if m["id"] == "phi4-mini")
    catalogue["models"] = [dict(model, size=8) if m["id"] == "phi4-mini" else m
                           for m in catalogue["models"]]
    root = tmp_path / "models"
    root.mkdir()

    cache = tmp_path / "cache"
    cache.mkdir()
    status = tmp_path / "model-fetch.json"
    choice = tmp_path / "choice.json"
    choice.write_text(json.dumps({"model": "phi4-mini", "backend": "cpu",
                                  "activate": False}))
    monkeypatch.setattr(fetch.safi_local, "load_catalogue", lambda *a, **kw: catalogue)
    monkeypatch.setattr(fetch, "CACHE_DIR", cache)
    monkeypatch.setattr(fetch, "STATUS_PATH", status)
    monkeypatch.setattr(fetch, "CHOICE_PATH", choice)
    monkeypatch.setattr(fetch, "UNIT_PATH", tmp_path / "safi-llama-server.service")
    monkeypatch.setattr(fetch, "ENV_FILE", tmp_path / "llama-server.env")
    monkeypatch.setattr(fetch, "write_status",
                        lambda **kw: status.write_text(json.dumps(kw, default=str)))
    monkeypatch.setattr(fetch, "verify", lambda *a, **kw: None)

    requested = []

    def _fake_download(step, progress):
        requested.append(step["kind"])
        progress(step, step["size"])
        blob = cache / f"{step['sha256']}.part"
        blob.write_bytes(b"\0" * int(step["size"]))
        return blob

    monkeypatch.setattr(fetch, "download", _fake_download)

    assert fetch.main(["--model", "phi4-mini", "--backend", "cpu"]) == 0
    assert "jev_local" in requested
    assert fetch.installed_jev_dir(catalogue) is not None
    assert (root / model["id"] / model["file"]).exists()
    assert json.loads(status.read_text())["jev_local_path"]


def test_the_jev_bundle_is_only_fetched_once_across_fetches(catalogue, tmp_path, monkeypatch):
    """Re-running setup must not re-download 1.7 GB of already-verified weights."""
    catalogue = dict(catalogue, model_root=str(tmp_path / "models"))
    model = next(m for m in catalogue["models"] if m["id"] == "phi4-mini")
    # Shrink the weights in the catalogue so the size check passes on a sparse
    # file; the point of this test is the Jev bundle, not the GGUF.
    small = dict(model, size=8)
    catalogue["models"] = [small if m["id"] == "phi4-mini" else m
                           for m in catalogue["models"]]
    root = tmp_path / "models"
    root.mkdir()
    (root / small["id"]).mkdir(parents=True)
    with open(root / small["id"] / small["file"], "wb") as handle:
        handle.truncate(int(small["size"]))
    _stage_jev_bundle(catalogue, root)

    cache = tmp_path / "cache"
    cache.mkdir()
    choice = tmp_path / "choice.json"
    choice.write_text(json.dumps({"model": "phi4-mini", "backend": "cpu",
                                  "activate": False}))
    monkeypatch.setattr(fetch.safi_local, "load_catalogue", lambda *a, **kw: catalogue)
    monkeypatch.setattr(fetch, "CACHE_DIR", cache)
    monkeypatch.setattr(fetch, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(fetch, "CHOICE_PATH", choice)
    monkeypatch.setattr(fetch, "UNIT_PATH", tmp_path / "safi-llama-server.service")
    monkeypatch.setattr(fetch, "ENV_FILE", tmp_path / "llama-server.env")
    monkeypatch.setattr(fetch, "write_status", lambda **kw: None)
    monkeypatch.setattr(fetch, "verify", lambda *a, **kw: None)

    def _no_downloads(step, *a, **kw):
        raise AssertionError(f"must not re-download {step.get('name')}")

    monkeypatch.setattr(fetch, "download", _no_downloads)
    assert fetch.main(["--model", "phi4-mini", "--backend", "cpu"]) == 0
    assert fetch.installed_jev_dir(catalogue) is not None
