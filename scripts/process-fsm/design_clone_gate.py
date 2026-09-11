"""Static clone gate for T5 G_design. No Playwright. No network."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import yaml

CATALOG_REL = "scripts/process-fsm/route-landmarks.yaml"
BLOCKED = "BLOCKED"
PASS = "PASS"

UI_IMPACT_RE = re.compile(
    r"^\s*(?:\*{0,2})UI impact:(?:\*{0,2})\s+(none|affected)\b",
    re.MULTILINE,
)
LIVE_ROUTE_RE = re.compile(
    r"^\s*(?:\*{0,2})live_route:(?:\*{0,2})\s+(\/\S+|landing|N/A)((?:\s+\S.*)?)?\s*$",
    re.MULTILINE,
)
SURFACE_RE = re.compile(
    r"^\s*(?:\*{0,2})surface:(?:\*{0,2})\s+(existing|new)\s*$",
    re.MULTILINE,
)
COPIED_START = "COPIED:start"
COPIED_END = "COPIED:end"
CLASS_ATTR_RE = re.compile(r"""class=["']([^"']*)["']""")


def parse_ui_impact(text: str) -> str | None:
    match = UI_IMPACT_RE.search(text)
    return match.group(1) if match else None


def parse_live_route(text: str) -> tuple[str | None, str]:
    match = LIVE_ROUTE_RE.search(text)
    if not match:
        return None, ""
    value = match.group(1)
    same_line = (match.group(2) or "").strip()
    if same_line:
        return value, same_line
    after = text[match.end() :]
    for line in after.splitlines():
        stripped = line.strip()
        if stripped:
            return value, stripped
    return value, ""


def parse_surface(text: str) -> str | None:
    match = SURFACE_RE.search(text)
    return match.group(1) if match else None


def copied_utf8_sum(html: str) -> int:
    events: list[tuple[str, int, int]] = []
    pos = 0
    while True:
        start_at = html.find(COPIED_START, pos)
        end_at = html.find(COPIED_END, pos)
        if start_at < 0 and end_at < 0:
            break
        if start_at >= 0 and (end_at < 0 or start_at < end_at):
            events.append(("start", start_at, start_at + len(COPIED_START)))
            pos = start_at + len(COPIED_START)
        else:
            events.append(("end", end_at, end_at + len(COPIED_END)))
            pos = end_at + len(COPIED_END)
    stack: list[int] = []
    total = 0
    pairs = 0
    for kind, at, after in events:
        if kind == "start":
            stack.append(after)
        elif stack:
            begin = stack.pop()
            total += len(html[begin:at].encode("utf-8"))
            pairs += 1
    return total if pairs else 0


def canonical_proto_html(proto_dir: Path | None) -> str:
    if proto_dir is None or not proto_dir.is_dir():
        return ""
    index = proto_dir / "index.html"
    if index.is_file():
        return index.read_text(encoding="utf-8")
    htmls = sorted(path for path in proto_dir.glob("*.html") if path.is_file())
    if len(htmls) == 1:
        return htmls[0].read_text(encoding="utf-8")
    return ""


def proto_has_html(proto_dir: Path | None) -> bool:
    return bool(proto_dir is not None and proto_dir.is_dir() and any(proto_dir.glob("*.html")))


def selector_matches(selector: str, html: str) -> bool:
    if selector in html:
        return True
    if "." not in selector:
        return False
    cls = selector.split(".", 1)[1]
    if not cls:
        return False
    for raw in CLASS_ATTR_RE.findall(html):
        if cls in raw.split():
            return True
    return False


def landmarks_match(entry: Mapping[str, Any], html: str) -> bool:
    selectors = list(entry.get("selectors") or [])
    texts = list(entry.get("texts") or [])
    if not all(selector_matches(str(sel), html) for sel in selectors):
        return False
    return all(str(text) in html for text in texts)


def routes_from_catalog(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    routes: dict[str, Any] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        key_s = str(key)
        entry = dict(value)
        if "kind" not in entry and key_s.startswith("/"):
            entry["kind"] = "authenticated"
        if key_s.startswith("/") or entry.get("kind") == "public":
            routes[key_s] = entry
    return routes


def parse_catalog(text: str) -> dict[str, Any]:
    loaded = yaml.safe_load(text) or {}
    return loaded if isinstance(loaded, dict) else {}


def load_catalog_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return parse_catalog(path.read_text(encoding="utf-8"))


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "route-landmarks.yaml"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def load_head_catalog(repo: Path) -> dict[str, Any]:
    """HEAD catalog only. A worktree-only key MUST NOT satisfy the gate."""
    exists = _git(repo, "cat-file", "-e", f"HEAD:{CATALOG_REL}")
    if exists.returncode == 0:
        shown = _git(repo, "show", f"HEAD:{CATALOG_REL}")
        if shown.returncode == 0:
            return parse_catalog(shown.stdout)
        return {}
    worktree = repo / CATALOG_REL
    if not worktree.is_file():
        return {}
    tracked = _git(repo, "ls-files", "--error-unmatch", CATALOG_REL)
    if tracked.returncode != 0:
        return {}
    quiet = _git(repo, "diff", "--quiet", "HEAD", "--", CATALOG_REL)
    if quiet.returncode != 0:
        return {}
    return load_catalog_file(worktree)


def _catalog_live_route(live_route: str | None) -> bool:
    return bool(live_route and (live_route.startswith("/") or live_route == "landing"))


def requires_existing_clone(live_route: str | None, surface: str | None) -> bool:
    if _catalog_live_route(live_route):
        return True
    return surface == "existing"


def is_new_exempt(live_route: str | None, surface: str | None, justification: str) -> bool:
    if _catalog_live_route(live_route):
        return False
    if surface == "new":
        return True
    return live_route == "N/A" and bool(justification.strip())


def classify(html: str, live_route: str, catalog: dict[str, Any] | None = None) -> str:
    data = catalog if catalog is not None else load_catalog_file(default_catalog_path())
    entry = routes_from_catalog(data).get(live_route)
    if entry is None:
        return BLOCKED
    if not landmarks_match(entry, html):
        return BLOCKED
    if copied_utf8_sum(html) <= 0:
        return BLOCKED
    return PASS


def evaluate_clone_gate(
    design_text: str,
    proto_dir: Path | None,
    repo: Path,
    catalog: dict[str, Any] | None = None,
) -> bool:
    ui = parse_ui_impact(design_text)
    live_route, justification = parse_live_route(design_text)
    surface = parse_surface(design_text)
    has_proto = proto_has_html(proto_dir)
    existing = requires_existing_clone(live_route, surface)

    if ui == "none" and not existing:
        return True
    if existing:
        data = catalog if catalog is not None else load_head_catalog(repo)
        routes = routes_from_catalog(data)
        route = live_route if live_route and live_route in routes else None
        if route is None:
            return False
        entry = routes.get(route)
        if entry is None:
            return False
        html = canonical_proto_html(proto_dir)
        if not landmarks_match(entry, html):
            return False
        return copied_utf8_sum(html) > 0
    if ui is None and not has_proto:
        return True
    if ui is None and has_proto:
        return False
    if ui == "affected" and not has_proto:
        return True
    if live_route is None and surface is None:
        return False
    if is_new_exempt(live_route, surface, justification):
        return True
    return False


def clone_gate_ok(change_dir: Path, proto_dir: Path | None, repo: Path) -> bool:
    design = change_dir / "design.md"
    if not design.is_file():
        return False
    return evaluate_clone_gate(design.read_text(encoding="utf-8"), proto_dir, repo)
