from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "analyze_source_usage.py"
    spec = importlib.util.spec_from_file_location("analyze_source_usage", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed_to_load_analyze_source_usage_module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["analyze_source_usage"] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _hydrate(node: dict, by_path: dict[str, dict]) -> dict:
    hydrated = dict(node)
    hydrated["children"] = [_hydrate(by_path[item], by_path) for item in node.get("children", []) if item in by_path]
    return hydrated


def _build_fixture_repo(root: Path) -> None:
    _write(
        root / "docker-compose.yml",
        """
services:
  api:
    command: >
      sh -c "python -m app.main"
""".strip(),
    )
    _write(
        root / ".github/workflows/deploy-pages.yml",
        """
name: deploy
jobs:
  build:
    steps:
      - run: npm run build
    defaults:
      run:
        working-directory: apps/web
""".strip(),
    )
    _write(root / "apps/api/app/__init__.py", "")
    _write(root / "apps/api/app/main.py", "import app.utils\n")
    _write(root / "apps/api/app/utils.py", "VALUE = 1\n")
    _write(root / "apps/web/package.json", '{"name":"sample-web"}\n')
    _write(root / "prompts/channels/sample.txt", "prompt\n")
    _write(root / "backup/old.txt", "old\n")
    _write(root / ".git/config", "[core]\n\trepositoryformatversion = 0\n")
    _write(root / ".env", "API_KEY=dev\n")
    _write(root / "docs/guide.md", "# guide\n")
    _write(root / "scripts/manual_task.py", "print('manual')\n")
    _write(root / "storage/reports/sample.json", "{}\n")


def test_analyze_repository_classifies_active_review_inactive(tmp_path: Path) -> None:
    module = _load_module()
    _build_fixture_repo(tmp_path)

    report = module.analyze_repository(tmp_path)
    flat = {item["path"]: item for item in report["flat_nodes"]}

    assert flat["apps/api/app/main.py"]["status"] == module.STATUS_ACTIVE
    assert flat["apps/api/app/utils.py"]["status"] == module.STATUS_ACTIVE
    assert flat["backup/old.txt"]["status"] == module.STATUS_INACTIVE
    assert flat["docs/guide.md"]["status"] == module.STATUS_REVIEW
    assert flat["scripts/manual_task.py"]["status"] == module.STATUS_REVIEW
    assert flat["storage/reports/sample.json"]["status"] == module.STATUS_INACTIVE


def test_analyze_repository_writes_json_tree_html_outputs(tmp_path: Path) -> None:
    module = _load_module()
    _build_fixture_repo(tmp_path)
    output_dir = tmp_path / "docs/reports"

    exit_code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    json_path = output_dir / "source-usage-report.json"
    tree_path = output_dir / "source-usage-tree.txt"
    html_path = output_dir / "source-usage-report.html"
    assert json_path.exists()
    assert tree_path.exists()
    assert html_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "summary" in payload
    assert payload["summary"]["total_nodes"] > 0

    tree_text = tree_path.read_text(encoding="utf-8")
    assert "[A] ." in tree_text

    html = html_path.read_text(encoding="utf-8")
    assert "Source Usage Report" in html
    assert "Inactive Cleanup Candidates" in html

    cleanup_paths = {item["path"] for item in payload.get("cleanup_candidates", [])}
    assert "backup/old.txt" in cleanup_paths
    assert ".git/config" not in cleanup_paths
    assert ".env" not in cleanup_paths
