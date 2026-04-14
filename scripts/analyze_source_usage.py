from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

STATUS_ACTIVE = "Active"
STATUS_REVIEW = "Review"
STATUS_INACTIVE = "Inactive"

BADGE_BY_STATUS = {
    STATUS_ACTIVE: "A",
    STATUS_REVIEW: "R",
    STATUS_INACTIVE: "I",
}

INACTIVE_PREFIX_RULES: dict[str, str] = {
    ".venv-api": "ignored_local",
    ".pytest_cache": "ignored_local",
    ".playwright-cli": "ignored_local",
    ".docker-data": "generated_data",
    "backup": "local_backup",
    "output": "generated_data",
    "TEST": "generated_data",
    "storage-clone": "local_backup",
    "storage": "generated_data",
}

INACTIVE_CLEANUP_REASON_CODES = {
    "generated_data",
    "ignored_local",
    "local_backup",
}

REVIEW_PREFIX_RULES: dict[str, str] = {
    "docs": "manual_ops_candidate",
    "wiki": "manual_ops_candidate",
    "scripts": "manual_ops_candidate",
    ".github": "manual_ops_candidate",
    ".agents": "manual_ops_candidate",
    ".codex": "manual_ops_candidate",
    "plugins": "manual_ops_candidate",
    "env": "manual_ops_candidate",
}

RUNTIME_SEED_PATHS = [
    "apps/api",
    "apps/web",
    "prompts",
    "infra/docker",
    "docker-compose.yml",
    ".github/workflows/deploy-pages.yml",
]

DOCKER_COMPOSE_PATTERN_MAP = {
    r"python\s+-m\s+([A-Za-z_][A-Za-z0-9_\.]*)": "compose_command",
    r"uvicorn\s+([A-Za-z_][A-Za-z0-9_\.]*):": "compose_command",
    r"celery\s+-A\s+([A-Za-z_][A-Za-z0-9_\.]*)": "compose_command",
}

PATH_VALUE_PATTERN_MAP = {
    "source:": "compose_path",
    "target:": "compose_path",
    "context:": "compose_path",
    "dockerfile:": "compose_path",
    "env_file:": "compose_path",
    "working-directory:": "workflow_referenced",
    "path:": "workflow_referenced",
}


@dataclass
class PathFact:
    path: str
    is_dir: bool
    size: int
    mtime: str
    tracked: bool
    ignored: bool


def _safe_rel(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")
    return rel or "."


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _run_git_list(repo_root: Path, args: list[str]) -> set[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            check=False,
            text=False,
        )
    except OSError:
        return set()
    if completed.returncode != 0:
        return set()
    payload = completed.stdout.decode("utf-8", errors="replace")
    results: set[str] = set()
    for token in payload.split("\x00"):
        value = token.strip().replace("\\", "/").lstrip("./")
        if value:
            results.add(value)
    return results


def _collect_git_facts(repo_root: Path) -> tuple[set[str], set[str]]:
    tracked = _run_git_list(repo_root, ["ls-files", "-z"])
    ignored = _run_git_list(repo_root, ["ls-files", "-z", "--others", "--ignored", "--exclude-standard"])
    return tracked, ignored


def _module_name_from_path(path: Path, repo_root: Path) -> str | None:
    rel = _safe_rel(path, repo_root)
    if not rel.endswith(".py"):
        return None
    if not rel.startswith("apps/api/"):
        return None
    tail = rel[len("apps/api/") : -3]
    if not tail:
        return None
    module = tail.replace("/", ".")
    if module.endswith(".__init__"):
        module = module[: -len(".__init__")]
    return module or None


def _extract_python_modules_from_compose(compose_text: str) -> dict[str, set[str]]:
    modules: dict[str, set[str]] = defaultdict(set)
    for pattern, reason in DOCKER_COMPOSE_PATTERN_MAP.items():
        for match in re.finditer(pattern, compose_text):
            candidate = str(match.group(1) or "").strip()
            if candidate:
                modules[candidate].add(reason)
    return modules


def _strip_yaml_value(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("-"):
        cleaned = cleaned[1:].strip()
    cleaned = cleaned.strip("'\"")
    if cleaned.startswith("${"):
        return ""
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.replace("\\", "/")
    return cleaned.strip().strip("/")


def _extract_path_refs_from_yaml_text(text: str) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = defaultdict(set)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for marker, reason in PATH_VALUE_PATTERN_MAP.items():
            if marker not in line:
                continue
            idx = line.find(marker)
            candidate = _strip_yaml_value(line[idx + len(marker) :])
            if candidate:
                refs[candidate].add(reason)
    return refs


def _collect_path_facts(repo_root: Path, tracked: set[str], ignored: set[str]) -> dict[str, PathFact]:
    facts: dict[str, PathFact] = {}

    def walk(path: Path) -> None:
        rel = _safe_rel(path, repo_root)
        if rel in facts:
            return
        try:
            stat = path.stat()
        except OSError:
            return
        is_dir = path.is_dir()
        size = 0 if is_dir else int(stat.st_size)
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        facts[rel] = PathFact(
            path=rel,
            is_dir=is_dir,
            size=size,
            mtime=mtime,
            tracked=rel in tracked,
            ignored=rel in ignored,
        )
        if not is_dir:
            return
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for entry in sorted(entries, key=lambda item: item.name.lower()):
            child = path / entry.name
            if entry.is_symlink():
                try:
                    child_stat = child.stat()
                    child_is_dir = child.is_dir()
                except OSError:
                    continue
                child_rel = _safe_rel(child, repo_root)
                facts[child_rel] = PathFact(
                    path=child_rel,
                    is_dir=child_is_dir,
                    size=0 if child_is_dir else int(child_stat.st_size),
                    mtime=datetime.fromtimestamp(child_stat.st_mtime, tz=timezone.utc).isoformat(),
                    tracked=child_rel in tracked,
                    ignored=child_rel in ignored,
                )
                continue
            walk(child)

    walk(repo_root)
    return facts


def _collect_python_import_graph(repo_root: Path) -> tuple[dict[str, Path], dict[str, set[str]]]:
    module_to_path: dict[str, Path] = {}
    graph: dict[str, set[str]] = defaultdict(set)

    for py_path in repo_root.rglob("*.py"):
        rel = _safe_rel(py_path, repo_root)
        if rel.startswith((".venv-api/", "backup/", "output/", "TEST/", ".docker-data/", ".pytest_cache/")):
            continue
        module = _module_name_from_path(py_path, repo_root)
        if not module:
            continue
        module_to_path[module] = py_path

    for module, path in module_to_path.items():
        text = _read_text(path)
        if not text:
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        is_package_init = path.name == "__init__.py"
        current_package = module if is_package_init else module.rsplit(".", 1)[0] if "." in module else ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = str(alias.name or "").strip()
                    if target:
                        graph[module].add(target)
            if isinstance(node, ast.ImportFrom):
                base_module = str(node.module or "").strip()
                if node.level and current_package:
                    parts = current_package.split(".")
                    trim = max(node.level - 1, 0)
                    if trim <= len(parts):
                        base_parts = parts[: len(parts) - trim]
                    else:
                        base_parts = []
                    if base_module:
                        base = ".".join([*base_parts, base_module]) if base_parts else base_module
                    else:
                        base = ".".join(base_parts)
                else:
                    base = base_module
                if base:
                    graph[module].add(base)
                for alias in node.names:
                    alias_name = str(alias.name or "").strip()
                    if not alias_name or alias_name == "*":
                        continue
                    if base:
                        graph[module].add(f"{base}.{alias_name}")

    return module_to_path, graph


def _collect_reachable_python_paths(
    seed_modules: dict[str, set[str]],
    module_to_path: dict[str, Path],
    graph: dict[str, set[str]],
    repo_root: Path,
) -> tuple[set[str], dict[str, set[str]]]:
    reasons: dict[str, set[str]] = defaultdict(set)
    active_paths: set[str] = set()

    queue: deque[str] = deque()
    visited_modules: set[str] = set()
    for module, module_reasons in seed_modules.items():
        if module not in module_to_path:
            continue
        queue.append(module)
        rel = _safe_rel(module_to_path[module], repo_root)
        for reason in module_reasons:
            reasons[rel].add(reason)

    while queue:
        module = queue.popleft()
        if module in visited_modules:
            continue
        visited_modules.add(module)
        path = module_to_path.get(module)
        if path is None:
            continue
        rel = _safe_rel(path, repo_root)
        active_paths.add(rel)
        reasons[rel].add("import_reachable")
        deps = graph.get(module, set())
        for dep in deps:
            if dep in module_to_path and dep not in visited_modules:
                queue.append(dep)
                continue
            if "." in dep:
                parent = dep.rsplit(".", 1)[0]
                if parent in module_to_path and parent not in visited_modules:
                    queue.append(parent)

    return active_paths, reasons


def _mark_path_and_parents(path: str, reasons_by_path: dict[str, set[str]], reason: str) -> None:
    normalized = path.strip("/").replace("\\", "/")
    if not normalized:
        reasons_by_path["."].add(reason)
        return
    current = normalized
    while current:
        reasons_by_path[current].add(reason)
        if "/" not in current:
            break
        current = current.rsplit("/", 1)[0]
    reasons_by_path["."].add(reason)


def _choose_status(
    rel_path: str,
    is_dir: bool,
    reasons: set[str],
    tracked: bool,
    ignored: bool,
) -> tuple[str, set[str]]:
    reasons = set(reasons)
    if rel_path == ".":
        reasons.add("runtime_seed")
        return STATUS_ACTIVE, reasons

    if reasons:
        return STATUS_ACTIVE, reasons

    for prefix, reason in INACTIVE_PREFIX_RULES.items():
        if rel_path == prefix or rel_path.startswith(f"{prefix}/"):
            reasons.add(reason)
            return STATUS_INACTIVE, reasons

    if ignored and not tracked:
        reasons.add("ignored_local")
        return STATUS_INACTIVE, reasons

    for prefix, reason in REVIEW_PREFIX_RULES.items():
        if rel_path == prefix or rel_path.startswith(f"{prefix}/"):
            reasons.add(reason)
            return STATUS_REVIEW, reasons

    if rel_path.startswith("prompts/"):
        reasons.add("manual_ops_candidate")
        return STATUS_REVIEW, reasons

    if tracked:
        reasons.add("tracked_but_not_reachable")
        return STATUS_REVIEW, reasons

    reasons.add("not_referenced")
    return STATUS_INACTIVE, reasons


def _risk_level(rel_path: str, tracked: bool) -> str:
    if rel_path.startswith(("backup/", "output/", "TEST/", ".venv-api/", ".pytest_cache/", ".playwright-cli/", ".docker-data/", "storage/")):
        return "low"
    if tracked:
        return "high"
    return "medium"


def _is_cleanup_candidate(rel_path: str, node: dict[str, Any]) -> bool:
    if rel_path == ".":
        return False
    if str(node.get("status")) != STATUS_INACTIVE:
        return False

    # Never suggest VCS internals for cleanup actions from this report.
    if rel_path == ".git" or rel_path.startswith(".git/"):
        return False

    reasons = set(node.get("reasons", []))
    if reasons & INACTIVE_CLEANUP_REASON_CODES:
        return True

    # Fallback: include only explicit inactive buckets.
    for prefix in INACTIVE_PREFIX_RULES:
        if rel_path == prefix or rel_path.startswith(f"{prefix}/"):
            return True
    return False


def analyze_repository(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    tracked, ignored = _collect_git_facts(repo_root)
    facts = _collect_path_facts(repo_root, tracked, ignored)

    reasons_by_path: dict[str, set[str]] = defaultdict(set)

    for seed in RUNTIME_SEED_PATHS:
        seed_path = seed.replace("\\", "/").strip("/")
        candidate = repo_root / seed_path
        if candidate.exists():
            _mark_path_and_parents(seed_path, reasons_by_path, "runtime_seed")

    compose_path = repo_root / "docker-compose.yml"
    compose_text = _read_text(compose_path)
    workflow_path = repo_root / ".github/workflows/deploy-pages.yml"
    workflow_text = _read_text(workflow_path)

    path_refs = {}
    path_refs.update(_extract_path_refs_from_yaml_text(compose_text))
    for key, vals in _extract_path_refs_from_yaml_text(workflow_text).items():
        path_refs.setdefault(key, set()).update(vals)

    for raw_ref, ref_reasons in path_refs.items():
        ref = raw_ref.strip().strip("/")
        if not ref:
            continue
        ref_candidate = repo_root / ref
        if not ref_candidate.exists():
            continue
        for reason in ref_reasons:
            _mark_path_and_parents(ref, reasons_by_path, reason)

    seed_modules = _extract_python_modules_from_compose(compose_text)
    for module in ("app.main", "app.prestart", "app.seed", "app.core.celery_app"):
        seed_modules[module].add("runtime_seed")

    module_to_path, import_graph = _collect_python_import_graph(repo_root)
    active_python_paths, python_reasons = _collect_reachable_python_paths(seed_modules, module_to_path, import_graph, repo_root)
    for rel in active_python_paths:
        _mark_path_and_parents(rel, reasons_by_path, "import_reachable")
    for rel, rel_reasons in python_reasons.items():
        for reason in rel_reasons:
            _mark_path_and_parents(rel, reasons_by_path, reason)

    nodes: dict[str, dict[str, Any]] = {}
    for rel, fact in facts.items():
        status, reasons = _choose_status(
            rel_path=rel,
            is_dir=fact.is_dir,
            reasons=reasons_by_path.get(rel, set()),
            tracked=fact.tracked,
            ignored=fact.ignored,
        )
        nodes[rel] = {
            "path": rel,
            "name": "." if rel == "." else rel.rsplit("/", 1)[-1],
            "type": "dir" if fact.is_dir else "file",
            "status": status,
            "reasons": sorted(reasons),
            "tracked": fact.tracked,
            "ignored": fact.ignored,
            "size_bytes": fact.size,
            "mtime_utc": fact.mtime,
            "children": [],
        }

    for rel, node in list(nodes.items()):
        if rel == ".":
            continue
        parent = rel.rsplit("/", 1)[0] if "/" in rel else "."
        parent_node = nodes.get(parent)
        if not parent_node:
            continue
        parent_node["children"].append(rel)

    # Directory status refinement from descendants
    def refresh_dir_status(path_key: str) -> str:
        node = nodes[path_key]
        if node["type"] != "dir":
            return str(node["status"])
        child_statuses: set[str] = set()
        for child_key in node["children"]:
            child_statuses.add(refresh_dir_status(child_key))
        own_status = str(node["status"])
        if own_status == STATUS_ACTIVE:
            return own_status
        if STATUS_ACTIVE in child_statuses:
            node["status"] = STATUS_ACTIVE
            if "contains_active_descendant" not in node["reasons"]:
                node["reasons"].append("contains_active_descendant")
            node["reasons"] = sorted(set(node["reasons"]))
            return STATUS_ACTIVE
        if own_status == STATUS_REVIEW:
            return own_status
        if STATUS_REVIEW in child_statuses:
            node["status"] = STATUS_REVIEW
            if "contains_review_descendant" not in node["reasons"]:
                node["reasons"].append("contains_review_descendant")
            node["reasons"] = sorted(set(node["reasons"]))
            return STATUS_REVIEW
        return STATUS_INACTIVE

    if "." in nodes:
        refresh_dir_status(".")

    for node in nodes.values():
        node["children"].sort(
            key=lambda item: (
                0 if nodes[item]["type"] == "dir" else 1,
                nodes[item]["name"].lower(),
            )
        )

    files_by_status = {STATUS_ACTIVE: 0, STATUS_REVIEW: 0, STATUS_INACTIVE: 0}
    dirs_by_status = {STATUS_ACTIVE: 0, STATUS_REVIEW: 0, STATUS_INACTIVE: 0}
    top_level: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, STATUS_ACTIVE: 0, STATUS_REVIEW: 0, STATUS_INACTIVE: 0})

    for rel, node in nodes.items():
        status = str(node["status"])
        if node["type"] == "dir":
            dirs_by_status[status] += 1
        else:
            files_by_status[status] += 1
        top = "." if rel == "." else rel.split("/", 1)[0]
        top_level[top]["total"] += 1
        top_level[top][status] += 1

    cleanup_candidates: list[dict[str, Any]] = []
    for rel, node in nodes.items():
        if not _is_cleanup_candidate(rel, node):
            continue
        candidate = {
            "path": rel,
            "type": node["type"],
            "reasons": node["reasons"],
            "tracked": node["tracked"],
            "ignored": node["ignored"],
            "size_bytes": node["size_bytes"],
            "risk": _risk_level(rel, bool(node["tracked"])),
            "recommended_action": "archive_then_remove_after_validation",
        }
        cleanup_candidates.append(candidate)

    cleanup_candidates.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item["risk"]], item["path"]))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "classification_basis": "runtime_ci",
        "status_model": [STATUS_ACTIVE, STATUS_REVIEW, STATUS_INACTIVE],
        "summary": {
            "total_nodes": len(nodes),
            "total_files": sum(files_by_status.values()),
            "total_dirs": sum(dirs_by_status.values()),
            "files_by_status": files_by_status,
            "dirs_by_status": dirs_by_status,
            "top_level": dict(sorted(top_level.items(), key=lambda item: item[0].lower())),
        },
        "nodes": nodes.get(".", {}),
        "flat_nodes": [nodes[key] for key in sorted(nodes.keys())],
        "cleanup_candidates": cleanup_candidates,
    }
    return report


def render_tree_text(root_node: dict[str, Any]) -> str:
    lines: list[str] = []

    def walk(node: dict[str, Any], prefix: str, is_last: bool) -> None:
        badge = BADGE_BY_STATUS.get(str(node.get("status")), "?")
        label = str(node.get("path") or node.get("name") or "")
        reason = ",".join(node.get("reasons", []))
        connector = "`-- " if is_last else "|-- "
        line_prefix = "" if not prefix else prefix
        lines.append(f"{line_prefix}{connector}[{badge}] {label} ({reason})")
        children = node.get("children", [])
        for index, child in enumerate(children):
            child_last = index == len(children) - 1
            child_prefix = f"{prefix}{'    ' if is_last else '|   '}"
            walk(child, child_prefix, child_last)

    if not root_node:
        return ""

    normalized_root = dict(root_node)
    normalized_root["path"] = "."
    normalized_root["children"] = root_node.get("children", [])
    walk(normalized_root, "", True)
    return "\n".join(lines) + "\n"


def _render_tree_html(node: dict[str, Any]) -> str:
    badge = BADGE_BY_STATUS.get(str(node.get("status")), "?")
    status = str(node.get("status"))
    label = escape(str(node.get("path") or node.get("name") or ""))
    reasons = ", ".join(node.get("reasons", []))
    reason_html = escape(reasons)
    node_type = str(node.get("type"))
    children = node.get("children", [])

    if node_type != "dir":
        return (
            f'<div class="node file" data-status="{escape(status)}" data-path="{label}">'
            f"<span class=\"badge\">[{badge}]</span> {label} "
            f"<span class=\"reasons\">{reason_html}</span>"
            "</div>"
        )

    details_open = " open" if label.count("/") < 2 else ""
    children_html = "".join(_render_tree_html(child) for child in children)
    return (
        f'<details class="node dir" data-status="{escape(status)}" data-path="{label}"{details_open}>'
        f"<summary><span class=\"badge\">[{badge}]</span> {label} <span class=\"reasons\">{reason_html}</span></summary>"
        f"<div class=\"children\">{children_html}</div>"
        "</details>"
    )


def render_html_report(report: dict[str, Any], tree_text: str) -> str:
    summary = report.get("summary", {})
    files_by_status = summary.get("files_by_status", {})
    dirs_by_status = summary.get("dirs_by_status", {})
    cleanup_candidates = report.get("cleanup_candidates", [])
    root_node = report.get("nodes", {})

    cleanup_rows = []
    for item in cleanup_candidates:
        cleanup_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('path', '')))}</td>"
            f"<td>{escape(str(item.get('type', '')))}</td>"
            f"<td>{escape(str(item.get('risk', '')))}</td>"
            f"<td>{escape(', '.join(item.get('reasons', [])))}</td>"
            f"<td>{escape(str(item.get('recommended_action', '')))}</td>"
            "</tr>"
        )
    cleanup_html = "".join(cleanup_rows) or "<tr><td colspan=\"5\">비활성 정리 후보가 없습니다.</td></tr>"

    tree_html = _render_tree_html(root_node) if root_node else "<div>트리 데이터가 없습니다.</div>"
    generated_at = escape(str(report.get("generated_at", "")))
    repo_root = escape(str(report.get("repo_root", "")))
    report_json = escape(json.dumps(report, ensure_ascii=False))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>소스 사용성 분석 리포트</title>
  <style>
    body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 24px; color: #1f2937; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .meta {{ color: #4b5563; margin-bottom: 16px; }}
    .guide {{ padding: 12px; border: 1px solid #cbd5e1; background: #f8fafc; margin: 12px 0 16px; border-radius: 8px; }}
    .guide p {{ margin: 8px 0; }}
    .guide ul {{ margin: 8px 0 0 18px; }}
    .warning {{ padding: 12px; border: 1px solid #f59e0b; background: #fffbeb; margin: 16px 0; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: 12px; margin: 12px 0 20px; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; background: #f9fafb; }}
    .card .label {{ font-size: 12px; color: #6b7280; }}
    .card .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .controls {{ display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }}
    .controls input, .controls select {{ padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; }}
    .tree-box {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; max-height: 620px; overflow: auto; background: #ffffff; }}
    .node {{ margin: 2px 0; }}
    .node summary {{ cursor: pointer; }}
    .children {{ margin-left: 16px; padding-left: 8px; border-left: 1px solid #e5e7eb; }}
    .badge {{ font-family: Consolas, "Courier New", monospace; font-weight: 700; color: #111827; }}
    .reasons {{ color: #6b7280; font-size: 12px; margin-left: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    pre {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; max-height: 320px; overflow: auto; background: #f8fafc; }}
  </style>
</head>
<body>
  <h1>소스 사용성 분석 리포트</h1>
  <div class="meta">생성 시각(UTC): {generated_at}<br/>분석 대상: {repo_root}</div>

  <div class="warning">
    <strong>주의:</strong> 이 리포트는 정리 의사결정용 분석 결과입니다. 추가 검증 없이 즉시 삭제하지 마세요.
  </div>

  <div class="guide">
    <h2>이 리포트는 무엇인가</h2>
    <p>전체 소스를 런타임 + CI 기준으로 분석해 현재 사용성 상태를 분류한 결과입니다.</p>
    <ul>
      <li><strong>Active</strong>: 실제 실행 경로(런타임/워크플로우/import 그래프)에서 도달 가능한 항목</li>
      <li><strong>Review</strong>: 즉시 삭제는 위험하며 운영/문서/수동 스크립트 성격으로 검토가 필요한 항목</li>
      <li><strong>Inactive</strong>: 생성물/캐시/백업 등 실행 경로에서 사용 근거가 없는 항목</li>
    </ul>
    <p>트리 필터/검색으로 경로를 빠르게 찾고, 하단 정리 후보 표에서 위험도와 권장 액션을 확인할 수 있습니다.</p>
  </div>

  <div class="cards">
    <div class="card"><div class="label">사용중 파일 (Active)</div><div class="value">{files_by_status.get(STATUS_ACTIVE, 0)}</div></div>
    <div class="card"><div class="label">검토 파일 (Review)</div><div class="value">{files_by_status.get(STATUS_REVIEW, 0)}</div></div>
    <div class="card"><div class="label">비활성 파일 (Inactive)</div><div class="value">{files_by_status.get(STATUS_INACTIVE, 0)}</div></div>
    <div class="card"><div class="label">사용중 폴더 (Active)</div><div class="value">{dirs_by_status.get(STATUS_ACTIVE, 0)}</div></div>
    <div class="card"><div class="label">검토 폴더 (Review)</div><div class="value">{dirs_by_status.get(STATUS_REVIEW, 0)}</div></div>
    <div class="card"><div class="label">비활성 폴더 (Inactive)</div><div class="value">{dirs_by_status.get(STATUS_INACTIVE, 0)}</div></div>
  </div>

  <h2>트리 (접기/펼치기)</h2>
  <div class="controls">
    <label for="statusFilter">상태</label>
    <select id="statusFilter">
      <option value="ALL">전체</option>
      <option value="{STATUS_ACTIVE}">Active (사용중)</option>
      <option value="{STATUS_REVIEW}">Review (검토)</option>
      <option value="{STATUS_INACTIVE}">Inactive (비활성)</option>
    </select>
    <label for="searchText">검색</label>
    <input id="searchText" type="text" placeholder="경로/파일명 포함 검색..." />
  </div>
  <div class="tree-box" id="treeRoot">{tree_html}</div>

  <h2>비활성 정리 후보</h2>
  <table>
    <thead>
      <tr><th>경로</th><th>유형</th><th>위험도</th><th>판정 이유 코드</th><th>권장 액션</th></tr>
    </thead>
    <tbody id="cleanupTable">
      {cleanup_html}
    </tbody>
  </table>

  <h2>트리 원문 (Raw)</h2>
  <pre>{escape(tree_text)}</pre>

  <script>
    const statusFilter = document.getElementById('statusFilter');
    const searchText = document.getElementById('searchText');
    const nodes = Array.from(document.querySelectorAll('.node'));

    function applyFilter() {{
      const status = statusFilter.value;
      const query = searchText.value.trim().toLowerCase();
      for (const node of nodes) {{
        const nodeStatus = (node.getAttribute('data-status') || '').trim();
        const nodePath = (node.getAttribute('data-path') || '').toLowerCase();
        const statusOk = status === 'ALL' || nodeStatus === status;
        const queryOk = !query || nodePath.includes(query);
        node.style.display = (statusOk && queryOk) ? '' : 'none';
      }}
    }}
    statusFilter.addEventListener('change', applyFilter);
    searchText.addEventListener('input', applyFilter);
    window.__REPORT_JSON__ = JSON.parse("{report_json}");
  </script>
</body>
</html>
"""


def _resolve_output_paths(repo_root: Path, output_dir: Path, json_path: str, tree_path: str, html_path: str) -> tuple[Path, Path, Path]:
    out_dir = output_dir if output_dir.is_absolute() else (repo_root / output_dir)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    resolved_json = Path(json_path).resolve() if json_path else out_dir / "source-usage-report.json"
    resolved_tree = Path(tree_path).resolve() if tree_path else out_dir / "source-usage-tree.txt"
    resolved_html = Path(html_path).resolve() if html_path else out_dir / "source-usage-report.html"

    resolved_json.parent.mkdir(parents=True, exist_ok=True)
    resolved_tree.parent.mkdir(parents=True, exist_ok=True)
    resolved_html.parent.mkdir(parents=True, exist_ok=True)
    return resolved_json, resolved_tree, resolved_html


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze repository source usage and produce tree/html reports.")
    parser.add_argument("--repo-root", default="", help="Repository root path (default: script parent parent).")
    parser.add_argument("--output-dir", default="docs/reports", help="Output directory for report files.")
    parser.add_argument("--json-path", default="", help="Optional explicit JSON report path.")
    parser.add_argument("--tree-path", default="", help="Optional explicit tree text path.")
    parser.add_argument("--html-path", default="", help="Optional explicit HTML report path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    script_path = Path(__file__).resolve()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else script_path.parents[1]
    output_dir = Path(args.output_dir)
    json_path, tree_path, html_path = _resolve_output_paths(
        repo_root=repo_root,
        output_dir=output_dir,
        json_path=str(args.json_path or ""),
        tree_path=str(args.tree_path or ""),
        html_path=str(args.html_path or ""),
    )

    report = analyze_repository(repo_root)
    nodes_by_path = {node["path"]: node for node in report.get("flat_nodes", [])}
    root_node = report.get("nodes", {})

    def attach_children(node: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(node)
        hydrated["children"] = [attach_children(nodes_by_path[item]) for item in node.get("children", []) if item in nodes_by_path]
        return hydrated

    hydrated_root = attach_children(root_node) if root_node else {}
    tree_text = render_tree_text(hydrated_root)
    html = render_html_report({**report, "nodes": hydrated_root}, tree_text)

    json_path.write_text(json.dumps({**report, "nodes": hydrated_root}, ensure_ascii=False, indent=2), encoding="utf-8")
    tree_path.write_text(tree_text, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    print(
        json.dumps(
            {
                "repo_root": str(repo_root),
                "json_report": str(json_path),
                "tree_report": str(tree_path),
                "html_report": str(html_path),
                "summary": report.get("summary", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
