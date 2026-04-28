from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

# Load environment variables from runtime.settings.env if possible
ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
if ENV_PATH.exists():
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

from app.services.ops.lighthouse_service import run_pagespeed_insights_audit, LighthouseAuditError


DEFAULT_URLS = [
    "https://donggri-kankoku.blogspot.com/",
    "https://donggri-corea.blogspot.com/",
    "https://donggri-korea.blogspot.com/"
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PageSpeed Insights analysis on multiple URLs.")
    parser.add_argument("urls", nargs="*", help="URLs to analyze (defaults to preset Blogger URLs)")
    parser.add_argument("--api-key", help="PageSpeed Insights API key (optional, falls back to env)")
    parser.add_argument("--save", action="store_true", help="Save detailed JSON reports to storage")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    urls = args.urls if args.urls else DEFAULT_URLS
    api_key = args.api_key or os.getenv("PAGESPEED_API_KEY")

    if not api_key:
        print("WARNING: PAGESPEED_API_KEY not found in environment or arguments. Using limited rate mode.")

    results = {}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    
    print(f"Starting PageSpeed Insights analysis for {len(urls)} sites...")

    for url in urls:
        print(f"\n--- Analyzing: {url} ---")
        site_key = url.replace("https://", "").replace("/", "").replace(".blogspot.com", "")
        results[url] = {}

        for strategy in ["mobile", "desktop"]:
            print(f"  [{strategy.upper()}] Running audit...")
            try:
                audit = run_pagespeed_insights_audit(url, strategy=strategy, api_key=api_key)
                scores = audit["scores"]
                results[url][strategy] = scores
                
                print(f"    Performance:   {scores.get('performance', 'N/A')}")
                print(f"    Accessibility: {scores.get('accessibility', 'N/A')}")
                print(f"    Best Practices: {scores.get('best_practices', 'N/A')}")
                print(f"    SEO:           {scores.get('seo', 'N/A')}")
                
                if args.save:
                    storage_root = Path(os.getenv("BLOGGENT_RUNTIME_STORAGE_ROOT", r"D:\Donggri_Runtime\BloggerGent\storage"))
                    report_dir = storage_root / "_common" / "analysis" / "lighthouse" / "manual"
                    report_dir.mkdir(parents=True, exist_ok=True)
                    
                    filename = f"psi-{site_key}-{strategy}-{timestamp}.json"
                    report_path = report_dir / filename
                    report_path.write_text(json.dumps(audit["raw_report"], ensure_ascii=False), encoding="utf-8")
                    print(f"    Report saved to: {report_path}")

            except LighthouseAuditError as e:
                print(f"    ERROR: {e}")
                results[url][strategy] = {"error": str(e)}
            except Exception as e:
                print(f"    UNEXPECTED ERROR: {e}")
                results[url][strategy] = {"error": str(e)}

    # Print Final Summary Table
    print("\n" + "="*50)
    print("FINAL SUMMARY REPORT")
    print("="*50)
    
    header = "{:<40} | {:>4} | {:>4} | {:>4} | {:>4}".format("Site", "PERF", "ACC", "BP", "SEO")
    print(header)
    print("-" * len(header))

    for url in urls:
        for strategy in ["mobile", "desktop"]:
            res = results[url].get(strategy, {})
            if "error" in res:
                print(f"{url[:40]:<40} | ERR ({strategy})")
                continue
            
            row = "{:<40} | {:>4} | {:>4} | {:>4} | {:>4} ({})".format(
                url[:40],
                res.get("performance", "??"),
                res.get("accessibility", "??"),
                res.get("best_practices", "??"),
                res.get("seo", "??"),
                strategy[0].upper()
            )
            print(row)

    return 0


if __name__ == "__main__":
    sys.exit(main())
