"""Synthetic consumers and an isolated operator account for the account-shim tests.

Never used by production code. A consumer here is a throwaway Git repository with a pinned overlay,
stub adapters at the paths the adapter manifest names and the manifest the pin would write.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import account_install
import adapter_manifest
import cf_shim

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ALL_HOSTS = list(cf_shim.CLIENTS)

CLAUDE_STUB = '''
import json, os, sys
event = sys.argv[1]
raw = sys.stdin.read()
with open(os.environ.get("CF_TEST_LOG", os.devnull), "a") as log:
    log.write(json.dumps({"client": "claude", "event": event, "cwd": os.getcwd(), "shim": os.environ.get("CF_SHIM_ACTIVE"),
                          "adapter_digest": os.environ.get("CF_SHIM_ADAPTER_DIGEST"), "payload": raw}) + "\\n")
if event == "session-start":
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "PAGE bound_card=1101 q=Em desenvolvimento"}}))
elif event == "pre-tool-use" and "deny-me" in raw:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "stub deny"}}))
'''
CODEX_STUB = CLAUDE_STUB.replace('"client": "claude"', '"client": "codex"')
CURSOR_STUB = r'''#!/usr/bin/env bash
RAW="$(cat)"
printf '%s\n' "$(basename "$0") $* cwd=$(pwd) shim=${CF_SHIM_ACTIVE:-}" >> "${CF_TEST_LOG:-/dev/null}"
case "$RAW" in
  *deny-me*) printf '%s\n' '{"permission":"deny","reason":"stub deny"}' ;;
  *) printf '%s\n' '{"permission":"allow"}' ;;
esac
'''
OPENCODE_STUB = """
import { appendFileSync } from "node:fs";
export default async function stub(ctx = {}) {
  appendFileSync(process.env.CF_TEST_LOG || "/dev/null", "opencode-init " + (ctx.directory || "") + "\\n");
  return {
    "tool.execute.before": async (input, output) => {
      appendFileSync(process.env.CF_TEST_LOG || "/dev/null", "opencode-before " + input.tool + "\\n");
      if (JSON.stringify(output.args || {}).includes("deny-me")) throw new Error("stub deny");
    },
  };
}
"""


def run(cmd: list[str], cwd: Path | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=kw.pop("check", True), capture_output=True, text=True, **kw)


def init_git(root: Path, branch: str = "main") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-b", branch, str(root)])
    run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "i"])
    return root


def write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode is not None:
        path.chmod(mode)


def make_consumer(root: Path, *, pin: str | None = "v1.2.0", manifest: bool = True, branch: str = "card-1101-fixture") -> Path:
    """A pinned consumer with stub adapters. `manifest=False` is a pin that predates account registration."""

    init_git(root, branch)
    overlay = "board: {}\nrepo: example/consumer\n" + (f"pin: {pin}\n" if pin else "")
    write(root / ".covenant-flow" / "overlay.yaml", overlay)
    sdir = root / "scripts" / "process-fsm"
    write(sdir / "claude_adapter.py", CLAUDE_STUB)
    write(sdir / "codex_adapter.py", CODEX_STUB)
    write(sdir / "other_module.py", "VALUE = 1\n")
    write(sdir / "test_ignored.py", "def test_x():\n    pass\n")
    write(sdir / "fixtures" / "ignored.json", "{}\n")
    for name in ("process-fsm-session-start.sh", "process-fsm-guard.sh", "process-fsm-model-selection.sh", "process-fsm-subagent-stop.sh", "impeccable.sh"):
        write(root / ".cursor" / "hooks" / name, CURSOR_STUB, 0o755)
    for name in ("process-fsm-guard.js", "impeccable-hook.js"):
        write(root / ".opencode" / "adapter" / name, OPENCODE_STUB)
    imp = root / ".agents" / "skills" / "impeccable" / "scripts"
    write(imp / "hook.mjs", "export {};\n")
    write(imp / "hook-lib.mjs", "export const lib = 1;\n")
    write(imp / "detector" / "rules.mjs", "export const rules = [];\n")
    if manifest and pin:
        adapter_manifest.write(root, pin)
    return root


def isolate_account(monkeypatch, tmp_path: Path) -> Path:
    """An empty operator account: HOME in tmp, no inherited host identity."""

    home = tmp_path / "account-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for name in ("CURSOR_VERSION", "CURSOR_PROJECT_DIR", "CF_SHIM_ACTIVE", "CF_SHIM_ADAPTER_DIGEST", "CF_SHIM_REGISTRATION_DIGEST"):
        monkeypatch.delenv(name, raising=False)
    return home


def install_account(hosts: Iterable[str] = ALL_HOSTS) -> None:
    account_install.run_install(HERE, list(hosts))


def trust_all(root: Path | None, hosts: Iterable[str] = ALL_HOSTS) -> None:
    for client in hosts:
        cf_shim.record(client, root)


def shim_command(client: str, event: str, payload: dict | str, *, env: dict | None = None, log: Path | None = None) -> subprocess.CompletedProcess:
    """Run the *installed* shim exactly as the host registration does."""

    shim = cf_shim.installed_shim_dir() / "cf_shim.py"
    full = dict(os.environ)
    full.update(env or {})
    if log is not None:
        full["CF_TEST_LOG"] = str(log)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(shim), client, event], input=raw, text=True, capture_output=True, env=full, check=False)


def last_json(result: subprocess.CompletedProcess) -> dict | None:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None


def registered_account(monkeypatch, tmp_path: Path, hosts: Iterable[str] = ALL_HOSTS) -> Path:
    """An empty tmp account with the Covenant Flow registration `install.sh --account` writes for `hosts`.

    HOME points into `tmp_path`, so nothing here can touch the real operator account.
    """

    home = isolate_account(monkeypatch, tmp_path)
    install_account(hosts)
    return home


def registered_document(client: str) -> dict:
    """The host configuration `account_install` generated in the (isolated) account."""

    return json.loads(cf_shim.host_config_path(client).read_text(encoding="utf-8"))


def shim_call(command: str) -> tuple[str, str]:
    """(client, event) a registered hook command passes to the account shim."""

    words = shlex.split(command)
    assert words[0] == "python3" and words[1].endswith("/covenant-flow/shim/current/cf_shim.py"), command
    assert len(words) == 4, command
    return words[2], words[3]


def opencode_module(name: str, root: Path = REPO) -> Path:
    """An OpenCode adapter module as the shim loads it: `.opencode/adapter/` after a pin (the pin moves it out
    of the host's auto-load path), `.opencode/plugin/` in the nucleus source tree."""

    for folder in ("adapter", "plugin"):
        path = root / ".opencode" / folder / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"OpenCode adapter module {name} not found under {root / '.opencode'}")
