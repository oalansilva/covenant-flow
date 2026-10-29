"""Account installer behind `install.sh --account [--check|--remove]`.

Installs the versioned shim (`cf_shim.py`, `cf_shim_opencode.js`) under
`~/.config/covenant-flow/shim/<version>/` with a `current` link, and merges one Covenant Flow
registration into the global hook/plugin configuration of each in-scope host found on the machine:
Claude Code (`~/.claude/settings.json`), Cursor (`~/.cursor/hooks.json`), Codex (`~/.codex/hooks.json`)
and OpenCode (a managed plugin in `~/.config/opencode/plugin/`). Grok Build and dsh are never touched.

Every foreign key and handler is preserved. Malformed configuration or a conflict that cannot be merged
without loss refuses the whole run before any write, naming the path, so no host is ever left half
written. The run is idempotent, never reads or writes the model selection and never records trust: the
operator reviews with `cf_shim.py trust --record`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

import cf_shim
from codex_fs import atomic_write_bytes as _atomic_write_bytes
from codex_hooks import HookConfigError, merge_hooks

def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    """Atomic write that follows a symlinked host config: the target is rewritten, the link is kept."""

    target = Path(path)
    if target.is_symlink():
        target = target.resolve()
    _atomic_write_bytes(target, content)


# `mcp__ccd_*` are the desktop app's session tools (denied with a bound card, design 5). The anchored form keeps
# tools that merely contain "Write" or "Agent" (TodoWrite, ...) away from the adapter.
PRETOOL_MATCHER = "^(Bash|Edit|Write|MultiEdit|NotebookEdit|Agent|mcp__ccd_.*)$"
HOST_BINARIES = {"claude": "claude", "cursor": "cursor-agent", "codex": "codex", "opencode": "opencode"}
HOST_HOMES = {"claude": ".claude", "cursor": ".cursor", "codex": ".codex", "opencode": ".config/opencode"}
CLAUDE_STATUS = {
    "session-start": "Loading Covenant Flow status",
    "prompt-submit": "Checking for an Alan gate command",
    "pre-tool-use": "Checking Covenant Flow write/model policy",
    "post-tool-use": "Checking edited UI files",
    "subagent-stop": "Recording child evidence",
    "stop": "Running the advisory UI deep pass",
}


class InstallError(ValueError):
    pass


def command(client: str, event: str) -> str:
    return f'python3 "$HOME/.config/{cf_shim.SHIM_MARKER}" {client} {event}'


def _handler(client: str, event: str, timeout: int, message: str, **extra: Any) -> dict[str, Any]:
    return {"type": "command", "command": command(client, event), "timeout": timeout, "statusMessage": message, **extra}


def claude_document() -> dict[str, Any]:
    def h(event: str, timeout: int = 30, message: str | None = None, **extra: Any) -> dict[str, Any]:
        return _handler("claude", event, timeout, message or CLAUDE_STATUS[event], **extra)

    return {"hooks": {
        "SessionStart": [{"matcher": "startup|resume|clear|compact", "hooks": [h("session-start")]}],
        "PreToolUse": [{"matcher": PRETOOL_MATCHER, "hooks": [h("pre-tool-use", onFailure="block")]}],
        "PostToolUse": [
            {"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash", "hooks": [h("post-tool-use")]},
            {"matcher": "Agent", "hooks": [h("post-tool-use", message="Checking the child's resolved model")]},
            # EnterWorktree does not reload settings and fires no SessionStart: the card page is reinjected here.
            {"matcher": "EnterWorktree", "hooks": [h("post-tool-use", message="Loading the card page of the entered worktree")]},
        ],
        "SubagentStop": [{"hooks": [h("subagent-stop", 15)]}],
        "Stop": [{"hooks": [h("stop")]}],
        # Gate commands (card #1135): never `onFailure: block`, the prompt always goes through; the timeout is above the
        # shim's own ceiling for this event, which is above the adapter's wait for the board executor (D8).
        "UserPromptSubmit": [{"hooks": [h("prompt-submit", PROMPT_TIMEOUT)]}],
    }}


# --------------------------------------------------------------------------- Claude Code gate commands (card #1135)

# Without a registered command Claude Code refuses `/priorizar 1` as "Unknown command" before any hook runs (task 0).
# The command body is neutral: the hook captured the text first; the agent acts only on the executor's context.
PROMPT_TIMEOUT = 120
COMMAND_MARKER = "<!-- covenant-flow-command: managed by `install.sh --account`; do not edit -->"
GATE_COMMANDS = {
    "priorizar": ("Portão do Alan: priorizar o card (T1, e o executor inicia o Design)", "<card>"),
    "aprovar-design": ("Portão do Alan: aprovar o design (T7)", "<card>"),
    "devolver-design": ("Portão do Alan: devolver o design com motivo (T6)", '<card> "motivo"'),
    "homologar": ("Portão do Alan: homologar (T15)", "<card>"),
    "nao-homologar": ("Portão do Alan: não homologar com motivo (T18)", '<card> "motivo"'),
    "cancelar": ("Portão do Alan: pedir o cancelamento com motivo (T2, pede confirmação)", '<card> "motivo"'),
    "confirmar-cancelar": ("Portão do Alan: confirmar o cancelamento pedido (T2)", "<card>"),
}


def commands_dir() -> Path:
    return Path.home() / ".claude" / "commands"


def command_text(name: str) -> str:
    description, hint = GATE_COMMANDS[name]
    return (
        "---\n"
        f"description: {description}\n"
        f"argument-hint: {hint}\n"
        "---\n"
        f"{COMMAND_MARKER}\n"
        f"Comando de portão do Alan: `/{name} $ARGUMENTS`.\n\n"
        "Este texto foi capturado pelo hook de prompt do Covenant Flow antes de chegar a você e não é um pedido ao agente. "
        "Não aja sozinho a partir dele: não mova o card, não chame o executor nem `portao_client` e não rode `process_event` "
        "por causa deste comando.\n\n"
        "O resultado do executor, quando houver, está no contexto adicional desta mensagem (\"Comando de portão tratado pelo "
        "executor: …\"); siga a FSM a partir do Status atual. Sem esse contexto o comando não foi capturado: trate como "
        "wording, diga ao Alan que o comando não foi capturado e aponte o board.\n"
    )


def _managed_command_file(path: Path) -> bool:
    try:
        return COMMAND_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def plan_commands() -> list[tuple[Path, bytes]]:
    """Target bytes of the seven gate commands; a foreign file with one of these names refuses the whole run."""

    planned = []
    for name in GATE_COMMANDS:
        path = commands_dir() / f"{name}.md"
        if (path.exists() or path.is_symlink()) and not _managed_command_file(path):
            raise InstallError(f"Claude Code command conflict: {path} exists and is not managed by Covenant Flow; move it, nothing was changed")
        planned.append((path, command_text(name).encode("utf-8")))
    return planned


def command_state() -> tuple[int, int]:
    """(current managed commands, expected)."""

    current = sum(1 for name in GATE_COMMANDS if (commands_dir() / f"{name}.md").is_file()
                  and (commands_dir() / f"{name}.md").read_bytes() == command_text(name).encode("utf-8"))
    return current, len(GATE_COMMANDS)


def remove_commands() -> list[Path]:
    removed = []
    for name in GATE_COMMANDS:
        path = commands_dir() / f"{name}.md"
        if path.is_file() and _managed_command_file(path):
            remove_with_target(path)
            removed.append(path)
    return removed


def codex_document() -> dict[str, Any]:
    def h(event: str, message: str) -> dict[str, Any]:
        return _handler("codex", event, 30, message)

    return {
        "description": "Covenant Flow account registration (shim). Hooks need the host's own trust review (/hooks).",
        "hooks": {
            "SessionStart": [{"hooks": [h("session-start", "Loading Covenant Flow status")]}],
            "PreToolUse": [{"matcher": "Bash|exec_command|apply_patch|Edit|Write|Agent", "hooks": [h("pre-tool-use", "Checking Covenant Flow write/model policy")]}],
            "PostToolUse": [{"matcher": "Bash|exec_command|apply_patch|Edit|Write", "hooks": [h("post-tool-use", "Checking edited UI files")]}],
            "Stop": [{"hooks": [h("stop", "Running the advisory UI deep pass")]}],
        },
    }


def cursor_document() -> dict[str, Any]:
    def c(event: str, **extra: Any) -> dict[str, Any]:
        return {"command": command("cursor", event), **extra}

    return {"version": 1, "hooks": {
        "sessionStart": [c("session-start")],
        "preToolUse": [
            c("guard", matcher="Write|StrReplace|Delete|EditNotebook", failClosed=True),
            c("model-selection", matcher="Task|Agent", failClosed=True),
        ],
        "beforeShellExecution": [c("guard")],
        "afterFileEdit": [c("impeccable-after-file-edit")],
        "stop": [c("impeccable-stop")],
        "subagentStop": [c("subagent-stop", matcher="generalPurpose|diff-reviewer|code-reviewer", loop_limit=32)],
    }}


def opencode_plugin() -> str:
    target = (cf_shim.installed_shim_dir() / "cf_shim_opencode.js").as_uri()
    return f'{cf_shim.OPENCODE_PLUGIN_HEADER}\nexport {{ default }} from "{target}";\n'


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"cannot read {path}: {exc}; fix or move it, nothing was changed") from exc
    if not isinstance(value, dict):
        raise InstallError(f"{path} must be a JSON object; nothing was changed")
    return value


def _render(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _check_codex_toml(home: Path) -> None:
    path = home / ".codex" / "config.toml"
    if not path.exists():
        return
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InstallError(f"cannot parse {path}: {exc}; nothing was changed") from exc
    hooks = document.get("hooks")
    # `[hooks.state]` is only the host's trust bookkeeping; inline hook tables would merge with hooks.json and conflict.
    if isinstance(hooks, dict) and set(hooks) - {"state"}:
        raise InstallError(f"Codex hook conflict: {path} defines inline [hooks] entries; compose them explicitly before --account (nothing was changed)")


def _prune(document: dict[str, Any]) -> dict[str, Any]:
    """Drop only the empty groups/events a removal left behind."""

    hooks = document.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            groups = hooks[event]
            if isinstance(groups, list):
                hooks[event] = [g for g in groups if not (isinstance(g, dict) and g.get("hooks") == [] and set(g) <= {"matcher", "hooks"})]
                if not hooks[event]:
                    del hooks[event]
    return document


def _strip_nested(document: dict[str, Any], path: Path) -> dict[str, Any]:
    merged = merge_hooks({"hooks": {}}, document, target_path=path, marker=cf_shim.SHIM_MARKER, source_label="account registration")
    return _prune(merged)


def _merge_cursor(document: dict[str, Any] | None, desired: dict[str, Any] | None, path: Path) -> dict[str, Any]:
    target = json.loads(json.dumps(document)) if document is not None else {"version": 1}
    hooks = target.get("hooks", {})
    if not isinstance(hooks, dict):
        raise InstallError(f"`hooks` must be an object in {path}; nothing was changed")
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise InstallError(f"invalid hook entries for `{event}` in {path}; nothing was changed")
        hooks[event] = [e for e in entries if not cf_shim._managed_command(e.get("command"))]
        if not hooks[event]:
            del hooks[event]
    for event, entries in (desired or {}).get("hooks", {}).items():
        hooks.setdefault(event, []).extend(json.loads(json.dumps(entries)))
    if hooks or desired is not None:
        target["hooks"] = hooks
    else:
        target.pop("hooks", None)  # a removal never leaves (or creates) an empty `hooks` object (R19)
    return target


def plan_host(client: str) -> tuple[Path, bytes]:
    """Target bytes for one host config after the merge."""

    path = cf_shim.host_config_path(client)
    if client == "opencode":
        if path.exists() and not path.read_text(encoding="utf-8", errors="replace").startswith(cf_shim.OPENCODE_PLUGIN_HEADER):
            raise InstallError(f"OpenCode plugin conflict: {path} exists and is not managed by Covenant Flow; move it, nothing was changed")
        return path, opencode_plugin().encode("utf-8")
    if client == "cursor":
        return path, _render(_merge_cursor(_read_object(path), cursor_document(), path))
    if client == "codex":
        _check_codex_toml(Path.home())
    existing = _read_object(path)
    try:
        merged = merge_hooks(claude_document() if client == "claude" else codex_document(), existing, target_path=path,
                             marker=cf_shim.SHIM_MARKER, source_label=f"{client} account registration")
    except HookConfigError as exc:
        raise InstallError(f"{exc}; nothing was changed") from exc
    return path, _render(merged)


def plan_removal(client: str) -> tuple[Path, bytes | None, bool]:
    """(path, new bytes or None to delete the file, changed)."""

    path = cf_shim.host_config_path(client)
    if not path.exists():
        return path, None, False
    if client == "opencode":
        managed = path.read_text(encoding="utf-8", errors="replace").startswith(cf_shim.OPENCODE_PLUGIN_HEADER)
        return path, None, managed
    existing = _read_object(path)
    if existing is None or cf_shim.host_entries(client) is None:
        return path, None, False  # no Covenant Flow entry: the file is not ours to rewrite, byte for byte (R18, R19)
    if client == "cursor":
        stripped = _merge_cursor(existing, None, path)
    else:
        try:
            stripped = _strip_nested(existing, path)
        except HookConfigError as exc:
            raise InstallError(f"{exc}; nothing was changed") from exc
        if stripped.get("hooks") == {}:
            del stripped["hooks"]  # the entries were all ours: do not leave `"hooks": {}` behind (R18)
    changed = stripped != existing
    ours = codex_document()["description"]
    leftovers = {k: v for k, v in stripped.items() if not (client == "codex" and k == "description" and v == ours)}
    only_ours = not leftovers or leftovers == {"hooks": {}} or leftovers in ({"version": 1}, {"version": 1, "hooks": {}})
    return path, (None if only_ours else _render(stripped)), changed


def installed_hosts(forced: list[str] | None) -> list[str]:
    if forced is not None:
        return [c for c in cf_shim.CLIENTS if c in forced]
    found = []
    for client in cf_shim.CLIENTS:
        if shutil.which(HOST_BINARIES[client]) or (Path.home() / HOST_HOMES[client]).exists():
            found.append(client)
    return found


def install_shim(source: Path) -> str:
    code = source / "cf_shim.py"
    plugin = source / "cf_shim_opencode.js"
    for path in (code, plugin):
        if not path.is_file():
            raise InstallError(f"shim source missing: {path}")
    version = next((line.split('"')[1] for line in code.read_text(encoding="utf-8").splitlines() if line.startswith("SHIM_VERSION = ")), None)
    if not version:
        raise InstallError(f"cannot read SHIM_VERSION from {code}")
    target = cf_shim.shim_root() / version
    for path in (code, plugin):
        atomic_write_bytes(target / path.name, path.read_bytes())
        os.chmod(target / path.name, 0o644)
    link = cf_shim.shim_root() / "current"
    temporary = cf_shim.shim_root() / ".current.tmp"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(version)
    os.replace(temporary, link)
    return version


def run_install(source: Path, forced: list[str] | None) -> list[str]:
    hosts = [h for h in installed_hosts(forced) if cf_shim.HOST_REGISTRATION[h] == "account"]
    lines: list[str] = []
    for client in cf_shim.CLIENTS:
        if cf_shim.HOST_REGISTRATION[client] != "account":
            lines.append(f"{client}: registration=unproven (no global mechanism proven; nothing installed)")
    # Everything is planned (and every conflict raised) before the first write.
    planned = [(client, *plan_host(client)) for client in hosts]
    if "claude" in hosts:
        planned += [("claude", path, content) for path, content in plan_commands()]
    previous = {path: (path.read_bytes() if path.exists() else None) for _c, path, _b in planned}
    version = install_shim(source)
    written: list[Path] = []
    try:
        for client, path, content in planned:
            if previous[path] != content:
                atomic_write_bytes(path, content)
                written.append(path)
            if path.suffix == ".md":
                continue
            lines.append(f"{client}: registered in {path}")
    except OSError as exc:
        for path in written:
            if previous[path] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, previous[path])
        raise InstallError(f"write failed ({exc}); host configurations were restored") from exc
    if "claude" in hosts:
        lines.append(f"claude: {len(GATE_COMMANDS)} gate commands in {commands_dir()} (/{', /'.join(GATE_COMMANDS)})")
    for client in cf_shim.CLIENTS:
        if client not in hosts and cf_shim.HOST_REGISTRATION[client] == "account":
            lines.append(f"{client}: not_installed (no binary or home found)")
    lines.insert(0, f"shim {version} installed in {cf_shim.shim_root()}")
    lines.append("trust is not recorded: the operator reviews with `python3 ~/.config/covenant-flow/shim/current/cf_shim.py trust --record`; Codex also needs its own /hooks review")
    return lines


def run_remove(forced: list[str] | None) -> list[str]:
    hosts = [c for c in cf_shim.CLIENTS if forced is None or c in forced]
    plans = [(client, *plan_removal(client)) for client in hosts]
    lines = []
    for client, path, content, changed in plans:
        if not changed:
            lines.append(f"{client}: nothing to remove")
            continue
        if content is None:
            remove_with_target(path)
        else:
            atomic_write_bytes(path, content)
        lines.append(f"{client}: Covenant Flow entries removed from {path}")
    if "claude" in hosts:
        removed = remove_commands()
        if removed:
            lines.append(f"claude: {len(removed)} gate commands removed from {commands_dir()}")
    root = cf_shim.shim_root()
    remaining = managed_hosts()
    if (root.exists() or root.is_symlink()) and remaining:
        lines.append(f"shim kept in {root}: entries remain for {', '.join(remaining)}")
    elif root.exists() or root.is_symlink():
        remove_shim(root)
        lines.append(f"shim removed from {root}")
    return lines


def remove_with_target(path: Path) -> None:
    """Delete a file the installer alone created, following a symlink: the link goes and so does its target (R20)."""

    if path.is_symlink():
        path.resolve().unlink(missing_ok=True)
    path.unlink(missing_ok=True)


def remove_shim(root: Path) -> None:
    """Remove every versioned directory of the shim and the `current` link, leaving no orphan target (R20)."""

    if root.is_symlink():
        shutil.rmtree(root.resolve(), ignore_errors=True)
        root.unlink(missing_ok=True)
        return
    for child in sorted(root.iterdir(), key=lambda item: not item.is_symlink()):
        if child.is_symlink():
            target = child.resolve()
            child.unlink()
            if target.is_dir() and root in target.parents:
                shutil.rmtree(target, ignore_errors=True)
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
    root.rmdir()


def managed_hosts() -> list[str]:
    """Hosts whose config still carries a Covenant Flow entry (they need the shim to exist)."""

    found = []
    for client in cf_shim.CLIENTS:
        try:
            if plan_removal(client)[2]:
                found.append(client)
        except InstallError:
            found.append(client)  # unreadable config: assume an entry is there, never strand it
    return found


def run_check(target: Path | None, forced: list[str] | None) -> tuple[list[str], bool]:
    """One line per host; False when an installed in-scope host lacks the shim or its registration."""

    detected = installed_hosts(forced)
    top = cf_shim.git_toplevel(target) if target is not None else None
    consumer = top if top is not None and (top / cf_shim.OVERLAY).is_file() else None
    pin = "none"
    if consumer is not None:
        pin = "account" if (consumer / cf_shim.MANIFEST).is_file() else "project (pin predates account registration)"
    lines, ok = [f"shim={cf_shim._installed_version()} protocol={cf_shim.SHIM_PROTOCOL} consumer_pin={pin}"], True
    for client in cf_shim.CLIENTS:
        mode = cf_shim.HOST_REGISTRATION[client]
        if mode != "account":
            lines.append(f"{client}: registration={mode} (no global mechanism proven; the host stays visibly unprotected)")
            continue
        if client not in detected:
            lines.append(f"{client}: registration=not_installed")
            continue
        state = cf_shim.status(client, consumer)
        entry = "present" if state["registered"] else "MISSING"
        shim = state["shim_version"] if state["shim_installed"] else "MISSING"
        reviewed = "reviewed" if state["registration"]["reviewed"] else "unreviewed"
        line = f"{client}: registration=account entry={entry} shim={shim} registration_review={reviewed}"
        if client == "claude":
            current, expected = command_state()
            line += f" gate_commands={current}/{expected}"
            if state["registered"] and current != expected:
                ok = False
        adapter = state["adapter"]
        if adapter and adapter["manifest"]:
            line += f" adapter_review={'reviewed' if adapter['reviewed'] else 'unreviewed'}"
            if adapter["missing"] or adapter["divergent"]:
                line += f" adapter_files(missing={len(adapter['missing'])}, divergent={len(adapter['divergent'])})"
        elif consumer is not None:
            line += " adapter=project-registration (old pin)"
        if not state["registered"] or not state["shim_installed"]:
            ok = False
        lines.append(line)
    return lines, ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "check", "remove"))
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent, help="directory with cf_shim.py and cf_shim_opencode.js")
    parser.add_argument("--hosts", help="comma separated hosts to treat as installed (default: detect)")
    parser.add_argument("--target", type=Path, help="consumer worktree to report the adapter review for (check)")
    args = parser.parse_args(argv)
    forced = [h for h in args.hosts.split(",") if h] if args.hosts else None
    if forced is not None and any(h not in cf_shim.CLIENTS for h in forced):
        print(f"--hosts must be among {', '.join(cf_shim.CLIENTS)}", file=sys.stderr)
        return 2
    try:
        if args.action == "install":
            lines = run_install(args.source, forced)
        elif args.action == "remove":
            lines = run_remove(forced)
        else:
            lines, ok = run_check(args.target, forced)
            print("\n".join(lines))
            return 0 if ok else 1
    except (InstallError, HookConfigError) as exc:
        print(f"install --account: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
