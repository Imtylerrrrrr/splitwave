import importlib.util
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "prune_hf_cache", Path(__file__).resolve().parents[1] / "tools" / "prune_hf_cache.py")
prune_hf_cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune_hf_cache)


def _symlinks_supported(tmp_path):
    try:
        os.symlink(tmp_path, tmp_path / "_probe")
        return True
    except (OSError, NotImplementedError):
        return False


def make_cache(tmp_path, weight_bytes):
    """프리페치 직후 모양: snapshot 이 blob 을 가리키는 링크 + 공유 blob + xet 캐시."""
    if not _symlinks_supported(tmp_path):
        pytest.skip("symlinks not permitted on this machine")
    hf = tmp_path / "hf_home"
    model = hf / "hub" / "models--adefossez--HTDemucs-6s"
    blob = model / "blobs" / "d2a1"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"w" * weight_bytes)
    shared = hf / "hub" / "blobs" / "4a" / "4a08"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"s" * weight_bytes)
    (hf / "xet" / "logs").mkdir(parents=True)
    snap = model / "snapshots" / "rev"
    snap.mkdir(parents=True)
    os.symlink(blob, snap / "5c90dfd2.safetensors")
    (snap / "htdemucs_6s.yaml").write_text("x")
    (model / "refs").mkdir()
    (model / "refs" / "main").write_text("rev")
    return hf, snap


def test_prune_fails_loudly_when_delete_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(prune_hf_cache, "MIN_WEIGHT_BYTES", 10)
    hf, _snap = make_cache(tmp_path, weight_bytes=100)

    def boom(path):
        raise PermissionError(path)
    monkeypatch.setattr(prune_hf_cache.shutil, "rmtree", boom)
    with pytest.raises(PermissionError):
        prune_hf_cache.prune(str(hf))


def test_prune_materializes_links_and_drops_blob_stores(tmp_path, monkeypatch):
    monkeypatch.setattr(prune_hf_cache, "MIN_WEIGHT_BYTES", 10)
    hf, snap = make_cache(tmp_path, weight_bytes=100)

    prune_hf_cache.prune(str(hf))

    weight = snap / "5c90dfd2.safetensors"
    assert weight.is_file() and not weight.is_symlink()
    assert weight.stat().st_size == 100
    assert (snap / "htdemucs_6s.yaml").is_file()
    assert not (hf / "hub" / "models--adefossez--HTDemucs-6s" / "blobs").exists()
    assert not (hf / "hub" / "blobs").exists()
    assert not (hf / "xet").exists()


def test_prune_refuses_when_no_real_weight_remains(tmp_path, monkeypatch):
    monkeypatch.setattr(prune_hf_cache, "MIN_WEIGHT_BYTES", 10)
    hf, snap = make_cache(tmp_path, weight_bytes=5)  # 임계값보다 작음 = 가중치로 안 침

    with pytest.raises(SystemExit):
        prune_hf_cache.prune(str(hf))
