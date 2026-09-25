"""번들용 HuggingFace 캐시 정리.

프리페치 직후의 hf_home 은 러너·huggingface_hub 버전에 따라 모양이 다르다:
같은 가중치가 blob / snapshot / xet 캐시에 여러 벌 복사돼 있기도 하고,
snapshots/ 의 파일이 blob 을 가리키는 심볼릭 링크이기도 하다.
그래서 blob 저장소를 그냥 지우면 링크만 남아 가중치가 통째로 빠질 수 있다 (v1.0.1 사고).

이 스크립트는 snapshots/ 아래 링크를 실제 파일로 바꾼 뒤 나머지 저장소를 지우고,
실제 가중치 파일이 남아 있는지 검증한다. 검증 실패 시 종료 코드 1.

사용: python tools/prune_hf_cache.py <hf_home>
"""
import glob
import os
import shutil
import sys

MIN_WEIGHT_BYTES = 10_000_000


def materialize_links(snapshots_root: str) -> int:
    """snapshots_root 아래 심볼릭 링크 파일을 실제 복사본으로 바꾼다. 바꾼 개수 반환."""
    n = 0
    for root, _dirs, files in os.walk(snapshots_root):
        for name in files:
            path = os.path.join(root, name)
            if not os.path.islink(path):
                continue
            target = os.path.realpath(path)
            if not os.path.isfile(target):
                raise SystemExit(f"prune: dangling link {path} -> {target}. "
                                 "Fix: re-run the prefetch step; the HF download did not complete.")
            os.unlink(path)
            shutil.copyfile(target, path)
            n += 1
    return n


def remove_dir(path: str) -> None:
    """없으면 넘어가고, 있는데 못 지우면 실패한다 (조용히 남으면 중복 가중치가 번들에 들어간다)."""
    if os.path.lexists(path):
        shutil.rmtree(path)


def real_weight_files(hf_home: str) -> list:
    pattern = os.path.join(glob.escape(hf_home), "hub", "models--*", "snapshots", "*", "*.safetensors")
    return [p for p in glob.glob(pattern)
            if os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p) >= MIN_WEIGHT_BYTES]


def prune(hf_home: str) -> None:
    hub = os.path.join(hf_home, "hub")
    for model_dir in glob.glob(os.path.join(glob.escape(hub), "models--*")):
        n = materialize_links(os.path.join(model_dir, "snapshots"))
        print(f"prune: {os.path.basename(model_dir)}: {n} link(s) materialized")
        remove_dir(os.path.join(model_dir, "blobs"))
    remove_dir(os.path.join(hub, "blobs"))  # 공유 blob 저장소
    remove_dir(os.path.join(hf_home, "xet"))

    weights = real_weight_files(hf_home)
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(hf_home) for f in fs if not os.path.islink(os.path.join(r, f)))
    print(f"prune: {len(weights)} weight file(s), hf_home total {total / 1e6:.1f} MB")
    if not weights:
        raise SystemExit("prune: no real weight file left under snapshots/. "
                         "Fix: check the prefetch step downloaded from HuggingFace (MODEL_NAME must be hf://...).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prune_hf_cache.py <hf_home>")
    prune(sys.argv[1])
