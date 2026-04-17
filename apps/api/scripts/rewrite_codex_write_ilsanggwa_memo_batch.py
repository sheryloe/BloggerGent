from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy template rewriter for 일상과-메모. "
            "This command is blocked in production because it bypasses category prompts."
        ),
    )
    parser.add_argument(
        "--allow-legacy-template",
        action="store_true",
        help="Bypass guard (for local experimentation only).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_legacy_template:
        print(
            (
                "blocked:legacy_template_rewriter_disabled\n"
                "Use category-prompt-based flow only.\n"
                "Recommended path:\n"
                "1) export_codex_write_cloudflare.py --category \"일상과-메모\"\n"
                "2) prompt-based topic/content fill\n"
                "3) publish_codex_write_cloudflare.py --dry-run\n"
                "4) publish_codex_write_cloudflare.py"
            ),
        )
        return 2
    print("warning: legacy template bypass enabled. No operation executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
