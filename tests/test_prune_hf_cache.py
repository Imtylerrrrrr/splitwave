import importlib.util
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "prune_hf_cache", Path(__file__).resolve().parents[1] / "tools" / "prune_hf_cache.py")
prune_hf_cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune_hf_cache)


def make_cache(tmp_path, weight_bytes):
    """프리페치 직후 모양: snapshot 이 blob 을 가리키는 링크 + 공유 blob + xet 캐시."""
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


def test_bundled_weights_present_ignores_links_and_small_files(tmp_path):
    import main
    hf, snap = make_cache(tmp_path, weight_bytes=100)
    assert main.bundled_weights_present(str(hf), min_bytes=10) is False  # 아직 링크
    prune_hf_cache.MIN_WEIGHT_BYTES, saved = 10, prune_hf_cache.MIN_WEIGHT_BYTES
    try:
        prune_hf_cache.prune(str(hf))
    finally:
        prune_hf_cache.MIN_WEIGHT_BYTES = saved
    assert main.bundled_weights_present(str(hf), min_bytes=10) is True
    assert main.bundled_weights_present(str(hf), min_bytes=1000) is False
