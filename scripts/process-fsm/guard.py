"""Compile process-fsm.yaml + resolver into a Write Guard (Cursor + Grok + OpenCode + dsh).

Glob-first: evaluate(write_produto) only for product_globs. No GitHub in unit tests.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from board_status import (  # noqa: E402
    is_sidecar_path,
    is_status_edit_command,
    sidecar_in_command,
)
from fsm import CARD_GIT_RE, EvalContext, EvalResult, evaluate, load_fsm  # noqa: E402
from overlay import (  # noqa: E402
    OverlayError,
    board_owner_number,
    glob_lists,
    integration_branches,
    load_overlay,
    repo_owner_name,
    try_load_overlay,
)
from graphql_quota import (  # noqa: E402
    GraphQLQuotaError,
    enforce_graphql_quota,
    parse_include_output,
    raise_if_cached_exhausted,
    write_cache,
)
from resolve import UNBOUND, resolve  # noqa: E402

REPO_ROOT = ROOT.parents[1]
WRITE_TOOLS = frozenset(
    {
        "Write",
        "StrReplace",
        "Delete",
        "EditNotebook",
        "write",
        "search_replace",
        "Edit",
        "MultiEdit",
        "edit",
        "apply_patch",
    }
)
OPENCODE_WRITE_TOOLS = frozenset({"write", "edit", "apply_patch"})
DSH_EDITOR_TOOL = "str_replace_editor"
DSH_EDITOR_MUTATE = frozenset({"create", "str_replace", "insert"})
SHELL_TOOLS = frozenset(
    {"Shell", "Bash", "run_terminal_command", "run_terminal_cmd", "bash"}
)
PATH_KEYS = ("path", "file_path", "file", "target_file", "target_notebook", "filePath")
PATCH_MARKERS = (
    "*** Add File:",
    "*** Update File:",
    "*** Delete File:",
    "*** Move to:",
    "*** Move File:",
)
MUTATION_RE = re.compile(r"(?:>>|>|\btee\s+|sed\s+-i|perl\s+-i|\bcp\s+|\bmv\s+|\binstall\s+)")
NON_REDIRECT_MUTATION_RE = re.compile(r"(?:sed\s+-i|perl\s+-i|\bcp\s+|\bmv\s+|\binstall\s+)")
# File redirects / tee destinations. Targets starting with & are fd redirects (2>&1).
FILE_REDIRECT_RE = re.compile(r"(?:\d*)?(>>|>)\s*([^\s|;<>&]+)")
TEE_TARGET_RE = re.compile(r"\btee(?:\s+-a)?\s+([^\s|;<>&]+)")
_FALLBACK_PRODUCT_PREFIXES = ("backend/", "frontend/src/")
_FALLBACK_DESIGN_PREFIXES = ("openspec/changes/", "frontend/public/prototypes/")

StatusProvider = Callable[[str | None], str | None]
EvaluateFn = Callable[[dict[str, Any], EvalContext], EvalResult]
ResolveFn = Callable[..., dict[str, str | None]]


def _prefixes(globs: list[Any]) -> tuple[str, ...]:
    out: list[str] = []
    for item in globs:
        text = str(item).replace("\\", "/").rstrip("*")
        text = text.rstrip("/")
        if text:
            out.append(text + "/")
    return tuple(out)


def _glob_prefix_lists(overlay: Mapping[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    product, design = glob_lists(overlay)
    product_prefixes = _prefixes(list(product)) if product else _prefixes(list(_FALLBACK_PRODUCT_PREFIXES))
    design_prefixes = _prefixes(list(design)) if design else _prefixes(list(_FALLBACK_DESIGN_PREFIXES))
    return product_prefixes, design_prefixes


def glob_kind(rel: str, overlay: Mapping[str, Any] | None) -> str:
    posix = rel.replace("\\", "/")
    if posix.startswith("./"):
        posix = posix[2:]
    product_prefixes, design_prefixes = _glob_prefix_lists(overlay)
    for prefix in product_prefixes:
        if posix == prefix[:-1] or posix.startswith(prefix):
            return "product"
    for prefix in design_prefixes:
        if posix == prefix[:-1] or posix.startswith(prefix):
            return "design"
    return "other"


def repo_relative(cwd: Path, path: str, overlay: Mapping[str, Any] | None = None) -> str:
    candidate = Path(path)
    resolved = candidate if candidate.is_absolute() else (cwd / candidate)
    try:
        return resolved.resolve().relative_to(cwd.resolve()).as_posix()
    except ValueError:
        text = resolved.as_posix()
        product_prefixes, design_prefixes = _glob_prefix_lists(overlay)
        markers = tuple("/" + p for p in (product_prefixes + design_prefixes) if p)
        for marker in markers:
            idx = text.find(marker)
            if idx != -1:
                return text[idx + 1 :]
        return Path(path).as_posix().removeprefix("./")


def _first_str(mapping: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tool_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _as_dict(payload.get("tool_input"))
    if data:
        return data
    data = _as_dict(payload.get("toolInput"))
    if data:
        return data
    return _as_dict(payload.get("args"))


def normalize(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical envelope: Cursor, Grok, OpenCode, and dsh `{ tool, args }` all work."""
    src = payload if isinstance(payload, Mapping) else {}
    tool = _first_str(src, "tool_name", "toolName", "tool") or ""
    cwd = (
        _first_str(src, "cwd")
        or _first_str(src, "workspaceRoot")
        or _first_str(src, "directory")
        or _first_str(src, "worktree")
        or os.getcwd()
    )
    data = _tool_input(src)
    command = src.get("command") if isinstance(src.get("command"), str) else ""
    if not str(command).strip():
        # str_replace_editor.args.command is view|create|str_replace|insert, not a shell.
        if tool == DSH_EDITOR_TOOL:
            command = ""
        else:
            nested = data.get("command")
            command = nested.strip() if isinstance(nested, str) and nested.strip() else ""
    out: dict[str, Any] = {
        "tool_name": tool,
        "tool_input": data,
        "command": command,
        "cwd": cwd,
    }
    status = src.get("status")
    if isinstance(status, str) and status.strip():
        out["status"] = status.strip()
    return out


def emit(permission: str, message: str = "") -> dict[str, str]:
    """Dual Cursor (`permission`) + Grok (`decision`) JSON."""
    allowed = permission == "allow"
    token = "allow" if allowed else "deny"
    out = {
        "permission": token,
        "decision": token,
        "reason": "" if allowed else message,
        "agent_message": "" if allowed else message,
        "user_message": "" if allowed else message,
    }
    return out


def _path_from_write(payload: Mapping[str, Any]) -> str | None:
    data = _tool_input(payload)
    keys = PATH_KEYS
    tool = str(payload.get("tool_name") or "")
    if tool == "EditNotebook":
        keys = ("target_notebook",) + PATH_KEYS
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _strip_quotes(token: str) -> str:
    text = token.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _is_allowlisted_sink(target: str, cwd: Path | None = None) -> bool:
    """Card #625: /dev/null and /tmp sinks outside the worktree are not product writes.

    Paths under the envelope cwd still count as product even when pytest uses /tmp
    for the fixture repo (absolute tee into the worktree must remain deny).
    """
    text = _strip_quotes(target)
    if text == "/dev/null":
        return True
    if text == "/tmp" or text.startswith("/tmp/"):
        if cwd is None:
            return True
        try:
            Path(text).resolve().relative_to(cwd.resolve())
        except ValueError:
            return True
        return False
    return False


def _redirect_file_targets(command: str) -> list[str]:
    targets: list[str] = []
    for match in FILE_REDIRECT_RE.finditer(command):
        found = _strip_quotes(match.group(2))
        if found.startswith("&"):
            # fd redirect such as 2>&1 — not a filesystem sink
            continue
        targets.append(found)
    for match in TEE_TARGET_RE.finditer(command):
        targets.append(_strip_quotes(match.group(1)))
    return targets


def _path_from_command(
    command: str, cwd: Path | None = None, overlay: Mapping[str, Any] | None = None
) -> str | None:
    if not MUTATION_RE.search(command):
        return None

    targets = _redirect_file_targets(command)
    has_non_redirect = bool(NON_REDIRECT_MUTATION_RE.search(command))

    # Only fd redirects (e.g. 2>&1) and/or allowlisted sinks → do not promote a
    # product path cited elsewhere in the command (card #625 false positive).
    if targets and all(_is_allowlisted_sink(t, cwd) for t in targets) and not has_non_redirect:
        return None
    if not targets and not has_non_redirect:
        return None

    product_prefixes, design_prefixes = _glob_prefix_lists(overlay)
    all_prefixes = product_prefixes + design_prefixes

    def _matches(target: str) -> bool:
        posix = target.replace("\\", "/").lstrip("./")
        return any(posix.startswith(prefix) or f"/{prefix}" in f"/{posix}" for prefix in all_prefixes)

    for target in targets:
        if _is_allowlisted_sink(target, cwd):
            continue
        if _matches(target):
            return target
        for prefix in all_prefixes:
            token = prefix.rstrip("/")
            if f"/{token}/" in target or target.startswith(token + "/"):
                return target

    joined = "|".join(re.escape(p.rstrip("/")) for p in all_prefixes if p)
    if not joined:
        return None
    pattern = re.compile(
        rf"((?:/(?:[\w.-]+))*/(?:{joined})/[^\s'\"|;<>&]+|(?:{joined})/[^\s'\"|;<>&]+)"
    )
    match = pattern.search(command)
    if match is None:
        return None
    found = match.group(1)
    if found.startswith("./"):
        found = found[2:]
    return found


def _command(payload: Mapping[str, Any]) -> str:
    canonical = normalize(payload)
    raw = canonical.get("command")
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def _sidecar_deny() -> dict[str, str]:
    message = (
        "process-fsm-guard deny reason=sidecar. .design-digest is written only by process_event T5."
    )
    return emit("deny", message)


def _status_edit_deny() -> dict[str, str]:
    message = (
        "process-fsm-guard deny reason=status_item_edit. Use scripts/process-fsm/process_event.py; "
        "do not gh project item-edit Status."
    )
    return emit("deny", message)


def git_anchor(cwd: Path, path: str) -> str:
    """Existing directory for git -C so Write into a new folder still binds q_git."""
    candidate = Path(path)
    resolved = candidate if candidate.is_absolute() else (cwd / candidate)
    current = resolved.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return str(current if current.exists() else cwd)


def _paths_from_patch_text(text: str) -> list[str]:
    out: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        for marker in PATCH_MARKERS:
            if line.startswith(marker):
                found = line[len(marker) :].strip()
                if found:
                    out.append(found)
                break
    return out


def _editor_subcommand(mapping: Mapping[str, Any]) -> str:
    raw = mapping.get("command")
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def is_dsh_editor_mutate(payload: Mapping[str, Any]) -> bool:
    canonical = normalize(payload)
    if str(canonical.get("tool_name") or "") != DSH_EDITOR_TOOL:
        return False
    data = canonical.get("tool_input")
    mapping = data if isinstance(data, dict) else {}
    return _editor_subcommand(mapping) in DSH_EDITOR_MUTATE


def extract_paths(
    payload: Mapping[str, Any], overlay: Mapping[str, Any] | None = None
) -> list[str]:
    """Every write path in envelope order (filePath then patchText markers)."""
    canonical = normalize(payload)
    tool = str(canonical.get("tool_name") or "")
    data = canonical.get("tool_input")
    mapping = data if isinstance(data, dict) else {}
    cwd_raw = canonical.get("cwd")
    cwd = Path(str(cwd_raw)) if isinstance(cwd_raw, str) and cwd_raw.strip() else None
    found: list[str] = []
    if tool == DSH_EDITOR_TOOL:
        # Mutate via args.path. view is not a write. Do not dump the tool into WRITE_TOOLS.
        if _editor_subcommand(mapping) in DSH_EDITOR_MUTATE:
            write_path = mapping.get("path")
            if isinstance(write_path, str) and write_path.strip():
                return [write_path.strip()]
            return []
        return []
    if tool in WRITE_TOOLS:
        write_path = _path_from_write(canonical)
        if write_path:
            found.append(write_path)
        patch = mapping.get("patchText")
        if not isinstance(patch, str):
            patch = mapping.get("patch_text")
        if isinstance(patch, str) and patch:
            for item in _paths_from_patch_text(patch):
                if item not in found:
                    found.append(item)
        if found:
            return found
    command = canonical.get("command")
    if isinstance(command, str) and command.strip():
        one = _path_from_command(command, cwd, overlay)
        if one:
            return [one]
    if tool in SHELL_TOOLS:
        one = _path_from_command(str(command or ""), cwd, overlay)
        if one:
            return [one]
    return []


def extract_path(payload: Mapping[str, Any], overlay: Mapping[str, Any] | None = None) -> str | None:
    paths = extract_paths(payload, overlay)
    return paths[0] if paths else None


def github_status_provider(bound_card: str | None) -> str | None:
    """Pontual issue→Status. RATE_LIMIT / remaining=0 raises GraphQLQuotaError (not None)."""
    if bound_card in (None, "", UNBOUND):
        return None
    try:
        number = int(str(bound_card))
    except (TypeError, ValueError):
        return None
    raise_if_cached_exhausted()
    overlay = try_load_overlay(Path.cwd())
    owner, repo_name = repo_owner_name(overlay)
    board_owner, board_number = board_owner_number(overlay)
    if not owner or not repo_name or not board_owner or board_number is None:
        return None
    env = os.environ.copy()
    try:
        query = (
            f'query($n:Int!){{repository(owner:"{owner}",name:"{repo_name}")'
            "{issue(number:$n){projectItems(first:20){nodes{"
            "project{number owner{...on User{login}}}"
            'fieldValueByName(name:"Status")'
            "{...on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}"
        )
        proc = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "--include",
                "-f",
                f"query={query}",
                "-F",
                f"n={number}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    captured = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    quota = parse_include_output(captured)
    write_cache(quota)
    enforce_graphql_quota(quota)
    data = quota.body
    if not isinstance(data, dict):
        return None
    nodes = (
        (((data.get("data") or {}).get("repository") or {}).get("issue") or {}).get("projectItems")
        or {}
    ).get("nodes") or []
    for node in nodes:
        project = (node or {}).get("project") or {}
        login = (project.get("owner") or {}).get("login")
        if project.get("number") != board_number or login not in (None, board_owner):
            continue
        field = (node or {}).get("fieldValueByName") or {}
        name = field.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _card_branch(q_git: str | None) -> bool:
    return bool(q_git) and CARD_GIT_RE.match(str(q_git)) is not None


def environment_dev_source(overlay: Mapping[str, Any] | None) -> str:
    """Read overlay environments.dev.source — not a hardcoded production path."""
    if not overlay:
        return ""
    env = overlay.get("environments")
    if not isinstance(env, Mapping):
        return ""
    dev = env.get("dev")
    if not isinstance(dev, Mapping):
        return ""
    return str(dev.get("source") or "").strip()


_CARD_CREATE_RE = re.compile(
    r"\bgit(?:\s+-C\s+(\S+))?\s+(?:checkout(?:\s+--track)?\s+-b|switch\s+-c)\s+"
    r"(card-\d+\S*)"
)


def _same_fs_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return os.path.normpath(str(left)) == os.path.normpath(str(right))


def _effective_git_path(command: str, cwd: Path | str) -> str | None:
    """cwd, or git -C target when the command creates a card-* branch."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "git" or token.endswith("/git"):
            c_path = None
            sub = None
            create = False
            branch = None
            j = i + 1
            while j < len(tokens):
                item = tokens[j]
                if item in {"&&", "||", ";", "|"}:
                    break
                if item == "-C" and j + 1 < len(tokens):
                    c_path = tokens[j + 1]
                    j += 2
                    continue
                if item == "--":
                    j += 1
                    continue
                if item in {"checkout", "switch"} and sub is None:
                    sub = item
                    j += 1
                    continue
                if sub == "checkout" and item in {"-b", "--track"}:
                    create = True
                    j += 1
                    continue
                if sub == "switch" and item == "-c":
                    create = True
                    j += 1
                    continue
                if create and branch is None and not item.startswith("-"):
                    branch = item
                    break
                j += 1
            if create and branch and CARD_GIT_RE.match(branch):
                raw = c_path if c_path else str(cwd)
                raw = raw.strip().strip("'\"")
                target = Path(raw) if Path(raw).is_absolute() else Path(cwd) / raw
                return str(target)
            i = j if j > i else i + 1
            continue
        i += 1
    match = _CARD_CREATE_RE.search(command)
    if match is None:
        return None
    branch = (match.group(2) or "").strip().strip("'\"")
    if CARD_GIT_RE.match(branch) is None:
        return None
    raw = (match.group(1) or str(cwd)).strip().strip("'\"")
    target = Path(raw) if Path(raw).is_absolute() else Path(cwd) / raw
    return str(target)


def is_canonical_card_branch_create(command: str, cwd: Path | str, source: str) -> bool:
    """True when checkout -b / switch -c / --track -b card-* targets overlay DEV source."""
    if not command or not source:
        return False
    target = _effective_git_path(command, cwd)
    if target is None:
        return False
    return _same_fs_path(target, source)


def _reason_message(reason: str, state: str | None, q_git: str | None, bound: str | None) -> str:
    return (
        f"process-fsm-guard deny reason={reason} q={state!s} q_git={q_git!s} "
        f"bound_card={bound!s}. Write produto blocked."
    )


def _allow() -> dict[str, str]:
    return emit("allow")


def _deny(reason: str, state: str | None, q_git: str | None, bound: str | None) -> dict[str, str]:
    return emit("deny", _reason_message(reason, state, q_git, bound))


def _deny_quota(
    reason: str,
    state: str | None,
    q_git: str | None,
    bound: str | None,
    quota_err: GraphQLQuotaError | None,
) -> dict[str, str]:
    denied = _deny(reason, state, q_git, bound)
    if quota_err is None:
        return denied
    extra = f" GraphQL quota remaining={quota_err.remaining} reset_at={quota_err.reset_at}"
    denied["agent_message"] = (denied.get("agent_message") or "") + extra
    return denied


def _empty_path_deny() -> dict[str, str]:
    message = (
        "process-fsm-guard deny reason=empty_path. "
        "write/edit/apply_patch (file_path or filePath) and "
        "str_replace_editor mutate (create/str_replace/insert path) "
        "require an extractable path."
    )
    return emit("deny", message)


def decide(
    payload: Mapping[str, Any],
    *,
    fsm: dict[str, Any] | None = None,
    resolve_fn: ResolveFn = resolve,
    status_provider: StatusProvider | None = None,
    evaluate_fn: EvaluateFn = evaluate,
    load_fsm_fn: Callable[..., dict[str, Any]] = load_fsm,
    overlay: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    canonical = normalize(payload)
    cwd_raw = canonical.get("cwd") or os.getcwd()
    cwd = Path(str(cwd_raw))
    if overlay is None:
        try:
            overlay = load_overlay(cwd, require_filled=True)
            overlay_ok = True
        except OverlayError:
            overlay = None
            overlay_ok = False
    else:
        overlay_ok = True
    paths = extract_paths(canonical, overlay)
    command = _command(canonical)
    tool = str(canonical.get("tool_name") or "")
    if any(is_sidecar_path(item) for item in paths) or sidecar_in_command(command):
        return _sidecar_deny()
    if is_status_edit_command(command, overlay):
        return _status_edit_deny()
    source = environment_dev_source(overlay)
    if source and is_canonical_card_branch_create(command, cwd, source):
        message = (
            "process-fsm-guard deny reason=canonical_card_branch. "
            "Do not git checkout -b / switch -c card-* on environments.dev.source."
        )
        return emit("deny", message)
    if not paths:
        if tool in OPENCODE_WRITE_TOOLS or is_dsh_editor_mutate(canonical):
            return _empty_path_deny()
        return _allow()

    write_like = (
        tool in WRITE_TOOLS
        or tool in SHELL_TOOLS
        or bool(command)
        or is_dsh_editor_mutate(canonical)
    )
    table = fsm if fsm is not None else load_fsm_fn()
    classified: list[tuple[str, str, str]] = []
    for item in paths:
        rel = repo_relative(cwd, item, overlay)
        classified.append((item, rel, glob_kind(rel, overlay)))
    product = [(orig, rel) for orig, rel, kind in classified if kind == "product"]
    design = [(orig, rel) for orig, rel, kind in classified if kind == "design"]
    kind = "product" if product else ("design" if design else "other")
    anchor = product[0][0] if product else (design[0][0] if design else paths[0])
    rel = product[0][1] if product else (design[0][1] if design else classified[0][1])
    if not overlay_ok:
        if kind == "product" and write_like:
            return _deny("overlay", None, None, None)
        return _allow()
    injected = payload.get("status")
    status = injected.strip() if isinstance(injected, str) and injected.strip() else None

    resolved = resolve_fn(cwd, git_anchor(cwd, anchor), status=status)
    q_git = resolved.get("q_git")
    bound = resolved.get("bound_card")
    q: str | None = status if status is not None else resolved.get("q")
    quota_err: GraphQLQuotaError | None = None
    if q is None and status_provider is not None:
        try:
            q = status_provider(None if bound in (None, UNBOUND) else str(bound))
        except GraphQLQuotaError as exc:
            quota_err = exc
            q = None

    if kind != "product":
        if q is None and kind == "design" and not _card_branch(q_git):
            return _deny_quota("fail_closed", q, q_git, bound, quota_err)
        return _allow()

    if q is None:
        return _deny_quota("fail_closed", q, q_git, bound, quota_err)

    if q_git in integration_branches(overlay):
        return _deny("I1", q, q_git, bound)

    ctx = EvalContext(
        state=q,
        event="write_produto",
        actor="Agent",
        q_git=q_git,
        bound_card=bound,
        path=rel,
    )
    result = evaluate_fn(table, ctx)
    if result.result == "allow":
        return _allow()
    reason = result.reason or "I1"
    if q == "Pronto para Dev" and reason == "I1":
        reason = "I3"
    if bound in (None, "", UNBOUND) and reason == "I1":
        reason = "unbound"
    return _deny(reason, q, q_git, bound)


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    decision = decide(payload, status_provider=github_status_provider)
    json.dump(decision, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
