from __future__ import annotations

import os
from pathlib import Path

DATASET_ID = "nvidia/Nemotron-Personas-Korea"
DATASET_REVISION = "main"
BASE_DIR = Path(r"E:\BloggerGent\datasets\hf\nvidia\Nemotron-Personas-Korea\2026-04-20-v1.0")
RAW_DIR = BASE_DIR / "raw"
DERIVED_DIR = BASE_DIR / "derived"
PACKS_DIR = BASE_DIR / "packs"
HF_HOME = Path(r"E:\BloggerGent\hf-cache")


def main() -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub. Install with: python -m pip install huggingface_hub"
        ) from exc

    os.environ.setdefault("HF_HOME", str(HF_HOME))
    os.environ.setdefault("HF_HUB_CACHE", str(HF_HOME / "hub"))
    for path in (HF_HOME, RAW_DIR, DERIVED_DIR, PACKS_DIR):
        path.mkdir(parents=True, exist_ok=True)

    result_path = snapshot_download(
        repo_id=DATASET_ID,
        repo_type="dataset",
        revision=DATASET_REVISION,
        local_dir=str(RAW_DIR),
        allow_patterns=["README.md", "data/*.parquet"],
        resume_download=True,
        max_workers=8,
    )
    print({"status": "ok", "dataset": DATASET_ID, "raw_dir": str(RAW_DIR), "snapshot_path": str(result_path)})


if __name__ == "__main__":
    main()
