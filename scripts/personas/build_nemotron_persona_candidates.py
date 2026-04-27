from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(r"E:\BloggerGent\datasets\hf\nvidia\Nemotron-Personas-Korea\2026-04-20-v1.0")
RAW_DATA_DIR = BASE_DIR / "raw" / "data"
DERIVED_DIR = BASE_DIR / "derived"
SEED_INDEX_PATH = DERIVED_DIR / "persona_seed_index.parquet"
SAMPLED_JSONL_PATH = DERIVED_DIR / "persona_candidates_sampled.jsonl"
CANDIDATE_MANIFEST_PATH = DERIVED_DIR / "persona_candidate_manifest.json"
MAX_PER_STRATUM = 100
MAX_TOTAL = 30000

BANNED_FIELDS = {
    "name", "sex", "gender", "marital_status", "military_status", "district", "province",
    "occupation", "education", "health", "politics", "religion", "age", "exact_age",
}
COLUMNS = [
    "uuid", "persona", "travel_persona", "culinary_persona", "arts_persona", "family_persona",
    "professional_persona", "cultural_background", "skills_and_expertise", "hobbies_and_interests",
    "career_goals_and_ambitions", "province", "district", "sex", "age", "occupation",
]


def age_band(value: Any) -> str:
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    lower = max(0, min(age // 10 * 10, 90))
    return f"{lower}-{lower + 9}"


def text(value: Any, limit: int = 1200) -> str:
    normalized = " ".join(str(value or "").replace("\n", " ").split())
    return normalized[:limit]


def sanitized_profile(row: dict[str, Any]) -> dict[str, Any]:
    source_text = " ".join(
        text(row.get(key), 500)
        for key in ("travel_persona", "culinary_persona", "arts_persona", "persona", "professional_persona")
    ).lower()
    return {
        "decision_style": "compare-time-cost-risk" if any(term in source_text for term in ("cost", "time", "budget", "schedule", "plan")) else "context-first",
        "content_preference": "practical-guide" if any(term in source_text for term in ("guide", "tips", "practical", "help")) else "context-summary",
        "pace_preference": "slow-to-moderate" if any(term in source_text for term in ("relax", "slow", "calm")) else "moderate",
        "trust_preference": "evidence-and-checklist",
        "tone_register": "practical-and-polite",
    }


def candidate_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uuid": text(row.get("uuid"), 80),
        "age_band": age_band(row.get("age")),
        "source_fields": {
            "persona": text(row.get("persona")),
            "travel_persona": text(row.get("travel_persona")),
            "culinary_persona": text(row.get("culinary_persona")),
            "arts_persona": text(row.get("arts_persona")),
            "family_persona": text(row.get("family_persona")),
            "professional_persona": text(row.get("professional_persona")),
            "cultural_background": text(row.get("cultural_background")),
            "skills_and_expertise": text(row.get("skills_and_expertise")),
            "hobbies_and_interests": text(row.get("hobbies_and_interests")),
            "career_goals_and_ambitions": text(row.get("career_goals_and_ambitions")),
        },
        "sanitized_profile": sanitized_profile(row),
    }


def main() -> None:
    try:
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit("Missing dependency: pyarrow. Install with: python -m pip install pyarrow") from exc

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    dataset = ds.dataset(str(RAW_DATA_DIR), format="parquet")
    available = set(dataset.schema.names)
    columns = [column for column in COLUMNS if column in available]
    if "uuid" not in columns:
        raise SystemExit("Dataset must contain uuid column")

    strata_counts: dict[str, int] = defaultdict(int)
    selected: list[dict[str, Any]] = []
    seen_uuid: set[str] = set()
    scanner = dataset.scanner(columns=columns, batch_size=2048)
    for batch in scanner.to_batches():
        for row in batch.to_pylist():
            uuid = text(row.get("uuid"), 80)
            if not uuid or uuid in seen_uuid:
                continue
            band = age_band(row.get("age"))
            stratum = "|".join([text(row.get("province"), 80) or "unknown", text(row.get("sex"), 40) or "unknown", band])
            if strata_counts[stratum] >= MAX_PER_STRATUM:
                continue
            candidate = candidate_from_row(row)
            seen_uuid.add(uuid)
            strata_counts[stratum] += 1
            selected.append(candidate)
            if len(selected) >= MAX_TOTAL:
                break
        if len(selected) >= MAX_TOTAL:
            break

    selected = sorted(selected, key=lambda item: item["uuid"])
    with SAMPLED_JSONL_PATH.open("w", encoding="utf-8") as handle:
        for item in selected:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    seed_rows = [
        {
            "uuid": item["uuid"],
            "age_band": item["age_band"],
            "persona": item["source_fields"].get("persona", ""),
            "travel_persona": item["source_fields"].get("travel_persona", ""),
            "culinary_persona": item["source_fields"].get("culinary_persona", ""),
            "arts_persona": item["source_fields"].get("arts_persona", ""),
            "professional_persona": item["source_fields"].get("professional_persona", ""),
            "cultural_background": item["source_fields"].get("cultural_background", ""),
            "skills_and_expertise": item["source_fields"].get("skills_and_expertise", ""),
            "hobbies_and_interests": item["source_fields"].get("hobbies_and_interests", ""),
        }
        for item in selected
    ]
    pq.write_table(pa.Table.from_pylist(seed_rows), SEED_INDEX_PATH)

    manifest = {
        "status": "ok",
        "source": str(RAW_DATA_DIR),
        "candidate_count": len(selected),
        "sampling": {"max_per_stratum": MAX_PER_STRATUM, "max_total": MAX_TOTAL, "unit": "1 uuid = 1 candidate"},
        "forbidden_fields_removed": sorted(BANNED_FIELDS),
        "outputs": [str(SEED_INDEX_PATH), str(SAMPLED_JSONL_PATH)],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    CANDIDATE_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"status": "ok", "candidate_count": len(selected), "manifest": str(CANDIDATE_MANIFEST_PATH)})


if __name__ == "__main__":
    main()
