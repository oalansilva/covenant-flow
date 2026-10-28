"""Codex hook context and supported mutation targets, independent of tool workdir.

This is a cooperative Guard adapter, not a shell sandbox. Complex/dynamic shell
mutations are refused when recognized; arbitrary program side effects are not
claimed as intercepted. Hosted tools require their own interception evidence.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from guard import extract_paths, normalize, _redirect_file_targets
from resolve import resolve


class BindingError(ValueError):
    pass


def normalize_input(tool, data):
    out = dict(data)
    if tool == "Bash":
        values = [out[k] for k in ("command", "cmd") if k in out]
        if not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise BindingError("invalid_tool_input: command/cmd must be a non-empty string")
        if len(set(values)) != 1:
            raise BindingError("ambiguous_command: command and cmd differ")
        out["command"] = values[0]
    return out


def mutation_paths(request):
    """All paths on covered patch/edit and simple, static shell mutation routes."""
    canonical = normalize(request)
    paths = extract_paths(canonical)
    command = canonical.get("command", "")
    if not command:
        return paths
    redirects = _redirect_file_targets(command)
    paths = list(dict.fromkeys([*paths, *redirects]))
    # Parsing shell as a general language would silently miss targets. Restrict
    # this route to static operands; keep the original command for shared Guard.
    mutating = bool(paths) or bool(re.search(r"\b(?:cp|mv|install|tee|touch|mkdir|rm|truncate)\b|\bsed\s+-i|\bperl\s+-i", command))
    if not mutating:
        return paths
    if re.search(r"\bcd\s|\bgit\s+-C\s|\$|`|<<|[{}*?\[\]]", command):
        raise BindingError("unsupported_targets: dynamic mutation or changed shell directory cannot be verified")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    tokens = list(lexer)
    segments, segment = [], []
    for token in tokens + [";"]:
        if token and all(c in ";&|" for c in token):
            if segment:
                segments.append(segment)
            segment = []
        else:
            segment.append(token)
    for words in segments:
        if not words:
            continue
        executable = Path(words[0]).name
        if executable in {"env", "sudo", "command", "exec", "eval", "sh", "bash", "zsh", "if", "then", "for", "while", "do"}:
            raise BindingError("unsupported_targets: wrapped or compound shell mutation cannot be verified")
        # Ignore redirect operands here: collected independently above.
        operands = []
        skip = False
        for word in words[1:]:
            if skip:
                skip = False
                continue
            if ">" in word or "<" in word:
                skip = True
                continue
            if word.startswith("-") and "=" in word and "/" in word:
                operands.append(word.split("=", 1)[1])
            elif word.startswith("-") and "/" in word:
                raise BindingError("unsupported_targets: joined mutation option contains an unresolved path")
            elif not word.startswith("-"):
                operands.append(word)
        if executable in {"cp", "mv", "install", "tee", "touch", "mkdir", "rm", "truncate"}:
            if not operands:
                raise BindingError("unsupported_targets: mutation has no static operands")
            # Check sources too: mv and copies must not cross card boundaries.
            paths.extend(operands)
        elif executable in {"sed", "perl"} and any(w.startswith("-i") for w in words[1:]):
            if len(operands) < 2:
                raise BindingError("unsupported_targets: in-place edit has no static target")
            paths.extend(operands[1:])
    return list(dict.fromkeys(paths))


def validate_context(event, root, data, paths):
    """Use host event/runtime identity; never derive it from tool input paths."""
    root = Path(root).resolve()
    supplied_cwd = event.get("cwd") or event.get("workspaceRoot")
    if not isinstance(supplied_cwd, str) or not supplied_cwd.strip():
        raise BindingError("binding_unavailable: native hook cwd missing")
    session = os.environ.get("CODEX_THREAD_ID")
    event_session = event.get("session_id") or event.get("thread_id")
    if event_session and session and event_session != session:
        raise BindingError("binding_mismatch: hook session differs from active native session")
    if session:
        from codex_evidence import Rollout
        _, _, _, turns = Rollout().session(session)
        if Path(turns[-1]["cwd"]).resolve() != Path(supplied_cwd).resolve():
            raise BindingError("binding_mismatch: hook cwd differs from active native turn_context")
    bound = resolve(root, root)
    tool_dir = data.get("workdir", supplied_cwd)
    if not isinstance(tool_dir, str) or not tool_dir.strip():
        raise BindingError("binding_unavailable: workdir must be a path")
    tool_dir = Path(tool_dir).expanduser()
    if not tool_dir.is_absolute():
        tool_dir = Path(supplied_cwd) / tool_dir
    tool_dir = tool_dir.resolve()
    if tool_dir != root and root not in tool_dir.parents:
        raise BindingError("worktree_mismatch: tool workdir escapes authorized hook worktree")
    for raw in paths:
        if raw in {"/dev/null", "/dev/stdout", "/dev/stderr"}:
            continue
        candidate = Path(raw).expanduser()
        target = (candidate if candidate.is_absolute() else tool_dir / candidate).resolve()
        if root not in target.parents:
            raise BindingError(f"target_outside_binding: {raw}")
        anchor = target
        while not anchor.exists() and anchor != root:
            anchor = anchor.parent
        target_binding = resolve(root, anchor)
        if target_binding != bound:
            raise BindingError(f"target_binding_mismatch: {raw}")
        change = re.search(r"(?:^|/)openspec/changes/card-(\d+)-", str(target))
        if change and str(bound["bound_card"]) != change[1]:
            raise BindingError(f"target_card_mismatch: {raw}")
    return tool_dir, bound
