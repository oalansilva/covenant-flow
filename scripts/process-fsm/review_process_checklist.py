"""Mechanical process checklist before commit. No GitHub. No pytest as Done."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from design_clone_gate import parse_live_route, parse_surface, parse_ui_impact  # noqa: E402
from fsm import CARD_GIT_RE  # noqa: E402

REPO_ROOT = ROOT.parents[1]
ERROR = "ERROR: process-checklist failed:"
FSM_REL = ".cursor/process-fsm.yaml"
PATCH_REL = Path(".cursor") / "tmp" / "review-diff.patch"
PENDING_RE = re.compile(r"^- \[ \] ", re.MULTILINE)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_OVERRIDE_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _GIT_OVERRIDE_VARS:
        env.pop(key, None)
    return env


def _fail(item: str) -> int:
    print(f"{ERROR} {item}")
    return 1


def _git_abbrev_ref(directory: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    branch = (result.stdout or "").strip()
    if not branch or branch == "HEAD":
        return ""
    return branch


def _bound_change_dir(repo: Path) -> Path | None:
    changes = repo / "openspec" / "changes"
    if not changes.is_dir():
        return None
    q_git = _git_abbrev_ref(repo)
    exact = changes / q_git if q_git else None
    if exact is not None and exact.is_dir():
        return exact
    match = CARD_GIT_RE.match(q_git) if q_git else None
    if match:
        prefix = f"card-{match.group(1)}-"
        hits = sorted(
            path
            for path in changes.iterdir()
            if path.is_dir() and path.name.startswith(prefix)
        )
        if len(hits) == 1:
            return hits[0]
        named = changes / (q_git or "")
        if named.is_dir():
            return named
    return None


def _check_wave_same_turn(value: str | None) -> str | None:
    if value != "yes":
        return "wave-same-turn"
    return None


def _check_tasks(change_dir: Path) -> str | None:
    path = change_dir / "tasks.md"
    if not path.is_file():
        return "tasks.md pending"
    text = path.read_text(encoding="utf-8")
    if PENDING_RE.search(text):
        return "tasks.md pending"
    return None


def _check_design_tokens(change_dir: Path) -> str | None:
    path = change_dir / "design.md"
    if not path.is_file():
        return "design.md tokens"
    text = path.read_text(encoding="utf-8")
    ui = parse_ui_impact(text)
    live, _rest = parse_live_route(text)
    surface = parse_surface(text)
    if ui is None or live is None or surface is None:
        return "design.md tokens"
    return None


def _check_patch(repo: Path) -> tuple[str | None, str]:
    path = repo / PATCH_REL
    if not path.is_file():
        return "review-diff.patch", ""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return "review-diff.patch", ""
    return None, text


def _norm_path(raw: str) -> str:
    path = raw.strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if len(path) >= 2 and path[0] in {'"', "'"} and path[-1] == path[0]:
        path = path[1:-1]
    return path


def _parse_count(raw: str | None) -> int:
    if raw is None:
        return 1
    return int(raw)


def _fsm_paths(old_path: str, new_path: str) -> bool:
    return FSM_REL in {_norm_path(old_path), _norm_path(new_path)}


def _extract_fsm_file(patch: str) -> dict[str, Any] | None:
    """Return metadata for the process-fsm.yaml file in a unified diff, if present."""
    lines = patch.splitlines()
    i = 0
    found: dict[str, Any] | None = None
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            parts = line.split()
            old_p = parts[2] if len(parts) > 2 else ""
            new_p = parts[3] if len(parts) > 3 else old_p
            is_fsm = _fsm_paths(old_p, new_p)
            record: dict[str, Any] = {
                "new_file": False,
                "deleted": False,
                "hunks": [],
            }
            i += 1
            while i < len(lines) and not lines[i].startswith("diff --git "):
                cur = lines[i]
                if cur.startswith("new file mode"):
                    record["new_file"] = True
                elif cur.startswith("deleted file mode"):
                    record["deleted"] = True
                elif cur.startswith("--- "):
                    record["old_path"] = cur[4:].strip()
                elif cur.startswith("+++ "):
                    record["new_path"] = cur[4:].strip()
                    if _fsm_paths(record.get("old_path", ""), record["new_path"]):
                        is_fsm = True
                elif cur.startswith("@@ "):
                    header = HUNK_RE.match(cur)
                    if header:
                        old_start = int(header.group(1))
                        old_count = _parse_count(header.group(2))
                        new_start = int(header.group(3))
                        new_count = _parse_count(header.group(4))
                        old_side: list[str] = []
                        new_side: list[str] = []
                        i += 1
                        while i < len(lines):
                            body = lines[i]
                            if body.startswith("diff --git ") or body.startswith("@@ "):
                                i -= 1
                                break
                            if body.startswith("\\"):
                                i += 1
                                continue
                            if body.startswith("+"):
                                new_side.append(body[1:])
                            elif body.startswith("-"):
                                old_side.append(body[1:])
                            elif body.startswith(" "):
                                old_side.append(body[1:])
                                new_side.append(body[1:])
                            else:
                                i -= 1
                                break
                            i += 1
                        record["hunks"].append(
                            {
                                "old_start": old_start,
                                "old_count": old_count,
                                "new_start": new_start,
                                "new_count": new_count,
                                "old_lines": old_side,
                                "new_lines": new_side,
                            }
                        )
                i += 1
            if is_fsm:
                found = record
            continue
        i += 1
    return found


def _flatten_map(raw: Any) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        items = value if isinstance(value, list) else [value]
        for item in items:
            out.add((str(key), str(item)))
    return out


def _machine_additions(old: dict[str, Any], new: dict[str, Any]) -> bool:
    old_states = {str(item) for item in (old.get("states") or [])}
    new_states = {str(item) for item in (new.get("states") or [])}
    if new_states - old_states:
        return True
    if _flatten_map(new.get("enabled_events")) - _flatten_map(old.get("enabled_events")):
        return True
    if _flatten_map(new.get("enabled_tools")) - _flatten_map(old.get("enabled_tools")):
        return True
    old_illegal = {str(item) for item in (old.get("illegal_events") or [])}
    new_illegal = {str(item) for item in (new.get("illegal_events") or [])}
    if new_illegal - old_illegal:
        return True
    return False


def _load_yaml(text: str) -> dict[str, Any]:
    loaded = yaml.safe_load(text) or {}
    return loaded if isinstance(loaded, dict) else {}


def _reverse_apply(new_text: str, hunks: list[dict[str, Any]]) -> str | None:
    lines = new_text.splitlines()
    for hunk in reversed(hunks):
        start = int(hunk["new_start"]) - 1
        count = int(hunk["new_count"])
        expected = list(hunk["new_lines"])
        if start < 0:
            return None
        actual = lines[start : start + count]
        if actual != expected:
            return None
        lines[start : start + count] = list(hunk["old_lines"])
    return "\n".join(lines) + ("\n" if new_text.endswith("\n") else "")


def _new_file_text(hunks: list[dict[str, Any]]) -> str:
    collected: list[str] = []
    for hunk in hunks:
        collected.extend(hunk["new_lines"])
    return "\n".join(collected) + ("\n" if collected else "")


def _check_fsm_edge(repo: Path, patch: str) -> str | None:
    record = _extract_fsm_file(patch)
    if record is None:
        return None
    if record.get("deleted"):
        return None
    disk = repo / FSM_REL
    if record.get("new_file"):
        added = _load_yaml(_new_file_text(record["hunks"]))
        if _machine_additions({}, added):
            return "new FSM edge"
        return None
    if not disk.is_file():
        return "new FSM edge"
    new_text = disk.read_text(encoding="utf-8")
    old_text = _reverse_apply(new_text, record["hunks"])
    if old_text is None:
        return "new FSM edge"
    if _machine_additions(_load_yaml(old_text), _load_yaml(new_text)):
        return "new FSM edge"
    return None


def check(repo: Path, wave_same_turn: str | None) -> str | None:
    item = _check_wave_same_turn(wave_same_turn)
    if item:
        return item
    change_dir = _bound_change_dir(repo)
    if change_dir is None:
        return "bound change"
    item = _check_tasks(change_dir)
    if item:
        return item
    item = _check_design_tokens(change_dir)
    if item:
        return item
    item, patch = _check_patch(repo)
    if item:
        return item
    return _check_fsm_edge(repo, patch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review_process_checklist")
    parser.add_argument("--wave-same-turn", choices=("yes", "no"), default=None)
    parser.add_argument("--root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)
    item = check(Path(args.root), args.wave_same_turn)
    if item:
        return _fail(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
