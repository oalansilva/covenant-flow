"""Project Status field ids from overlay + Shell classification. Not secrets."""

from __future__ import annotations

import re
from typing import Any, Mapping

from overlay import status_field_id, status_option_ids

PROCESS_EVENT_RE = re.compile(r"process-fsm/process_event\.py|\bprocess_event\.py\b")


def is_sidecar_path(path: str | None) -> bool:
    if not path:
        return False
    posix = path.replace("\\", "/").split("?")[0].rstrip("/")
    return posix.endswith(".design-digest")


def sidecar_mutation_in_command(command: str | None) -> bool:
    """True only when the shell command mutates a `.design-digest` path (card #631).

    Mere citation (`git add`/`commit`/`status`/`reset`, `ls`, `cat`) MUST be False.
    """
    if not command or ".design-digest" not in command:
        return False
    if re.search(r"(?:\d*)?(?:>>|>)\s*[^\s|;<>&]*\.design-digest\b", command):
        return True
    if re.search(r"\btee(?:\s+-a)?\s+[^\s|;<>&]*\.design-digest\b", command):
        return True
    if re.search(r"\b(?:rm|unlink|shred)\b[^\n]*\.design-digest\b", command):
        return True
    if re.search(r"\b(?:cp|mv|install)\b[^\n]*\.design-digest\b", command):
        return True
    if re.search(r"(?:sed\s+-i|perl\s+-i)[^\n]*\.design-digest\b", command):
        return True
    if re.search(r"\bpython3?\s+-c\b", command):
        if re.search(
            r"open\s*\([^)]*\.design-digest[^)]*['\"][wax+]+",
            command,
        ):
            return True
        if re.search(
            r"Path\s*\([^)]*\.design-digest[^)]*\)\s*\.\s*write_(?:text|bytes)\s*\(",
            command,
        ):
            return True
        if re.search(r"\.design-digest[^;]*\.write\s*\(", command):
            return True
    return False


def sidecar_in_command(command: str | None) -> bool:
    """Compat alias: sidecar deny only on mutation (#631)."""
    return sidecar_mutation_in_command(command)


def is_status_edit_command(
    command: str | None,
    overlay: Mapping[str, Any] | None = None,
) -> bool:
    if not command:
        return False
    field = status_field_id(overlay)
    option_ids = status_option_ids(overlay)
    graphql = "updateProjectV2ItemFieldValue" in command
    item_edit = "item-edit" in command
    if not graphql and not item_edit:
        return False
    if overlay is None:
        return True
    if graphql and field and field in command:
        return True
    if item_edit and field and field in command:
        return True
    if item_edit and any(option_id in command for option_id in option_ids):
        return True
    return False


# Card #1135: only `process_event` asks the board executor; Alan's gate commands are captured only by the prompt hook.
# Cooperative like the `item-edit` rule above: it holds a cooperating agent, never a deliberate forger (design D5).
PROCESS_EVENT_ONLY_RE = re.compile(
    r"^\s*(?:[A-Z_][A-Z0-9_]*=\S*\s+)*(?:\S*/)?python3?\s+(?:\S*/)?scripts/process-fsm/process_event\.py"
    r"\s+[a-z_]+(?:\s+--[a-z][a-z-]*(?:[ =][^\s;&|<>`$()]+)?)*\s*$"
)
_PORTAO_CALL_RE = re.compile(
    # running the client module or the executor script; reading/staging them (`cat`, `sed -n`, `git add`) is not a call
    r"(?:\bpython3?\b|\bpy\b)[^;&|\n]*(?:\bportao_client(?:\.py)?\b|\bportao/executor\.py\b)"
    r"|\b(?:import\s+portao_client|from\s+portao_client\s+import|from\s+portao\b[\w.]*\s+import|import\s+portao\b)"
    r"|\bportao_client\s*\.\s*(?:capturar|pedir|enviar|montar_pedido)\b"
)
_DISPATCH_RE = re.compile(r"(?:repos/|api\.github\.com/repos/)[^\s'\"/]+/[^\s'\"/]+/dispatches\b")
_HTTP_CLIENT_RE = re.compile(r"\bgh\s+api\b|\bcurl\b|\bwget\b|\bhttpie?\b|\brequests\.|\burllib\b|\bhttpx\b|\bfetch\(")


def is_executor_dispatch_command(command: str | None, overlay: Mapping[str, Any] | None = None) -> bool:
    """True when a shell command calls the executor client (`capturar`/`pedir`) or a `dispatches` endpoint directly.

    `repository_dispatch` is how the board executor is triggered: the agent reaches it only through
    `scripts/process-fsm/process_event.py <event> [--flags]`, and Alan's commands only through the prompt hook. Reading
    the files (`cat`, `grep`, `sed -n`) is not a call. Any repository's `dispatches` is denied, so a renamed executor
    repository is covered too; `overlay` is accepted for symmetry with `is_status_edit_command`.
    """

    del overlay
    if not command:
        return False
    if PROCESS_EVENT_ONLY_RE.match(command):
        return False
    if _PORTAO_CALL_RE.search(command):
        return True
    return bool(_DISPATCH_RE.search(command) and _HTTP_CLIENT_RE.search(command))
