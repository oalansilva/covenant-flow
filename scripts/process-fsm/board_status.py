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
