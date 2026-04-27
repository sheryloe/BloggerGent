from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATASET_ID = "nvidia/Nemotron-Personas-Korea"
SOURCE_URL = "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea"
BASE_DIR = Path(r"E:\BloggerGent\datasets\hf\nvidia\Nemotron-Personas-Korea\2026-04-20-v1.0")
RAW_DATA_DIR = BASE_DIR / "raw" / "data"
DERIVED_DIR = BASE_DIR / "derived"
MANIFEST_PATH = DERIVED_DIR / "manifest.json"
EXPECTED_ROWS = 1_000_000
EXPECTED_PARQUET_COUNT = 9


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    try:
        import pyarrow.dataset as ds
    except ImportError as exc:
        raise SystemExit("Missing dependency: pyarrow. Install with: python -m pip install pyarrow") from exc

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW_DATA_DIR.glob("*.parquet"))
    if len(files) != EXPECTED_PARQUET_COUNT:
        raise SystemExit(f"Expected {EXPECTED_PARQUET_COUNT} parquet files, found {len(files)} in {RAW_DATA_DIR}")

    dataset = ds.dataset(str(RAW_DATA_DIR), format="parquet")
    row_count = dataset.count_rows()
    if row_count != EXPECTED_ROWS:
        raise SystemExit(f"Expected {EXPECTED_ROWS} rows, found {row_count}")

    manifest: dict[str, Any] = {
        "dataset": DATASET_ID,
        "license": "CC BY 4.0",
        "source_url": SOURCE_URL,
        "expected_rows": EXPECTED_ROWS,
        "row_count": row_count,
        "files": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        ],
        "schema": [
            {"name": field.name, "type": str(field.type)}
            for field in dataset.schema
        ],
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"status": "ok", "manifest": str(MANIFEST_PATH), "row_count": row_count, "files": len(files)})


if __name__ == "__main__":
    main()
