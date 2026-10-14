"""Consumer-side check that a session really runs under the account registration.

`process_event` (and the Claude Code evidence preflight) call `require_active` before the transitions
that depend on hooks. It adds no state, event, edge or permission: it only makes a missing registration
visible. A consumer whose pin predates account registration (no adapter manifest) is not checked here:
its project registration and its own preflight stay exactly as before. Grok Build and dsh are never
checked: their registration stays in the project.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import cf_shim

ACCOUNT_CLIENTS = cf_shim.CLIENTS
SESSION_VARIABLES = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_THREAD_ID"}
RECOVERY = "run `install.sh --account` from the covenant-flow checkout, have the operator review with `cf_shim.py trust --record`, then start a new session"


class RegistrationRefusal(Exception):
    def __init__(self, code: str, detail: str, recovery: str = RECOVERY):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.recovery = recovery

    def __str__(self) -> str:
        return f"{self.detail}. Recovery: {self.recovery}."


def consumer_root(workdir: str | Path) -> Path:
    base = Path(workdir).resolve()
    return cf_shim.git_toplevel(base) or base


def registration_of(root: Path, client: str) -> str | None:
    """`account`, `project`, `unproven`, or None when the pin predates account registration."""

    try:
        manifest = cf_shim.load_manifest(root)
    except cf_shim.ManifestError as exc:
        raise RegistrationRefusal("hooks_inactive", f"the adapter manifest of this pin is unreadable ({exc})", "re-run `install.sh --pin <tag>`") from exc
    if manifest is None:
        return None
    entry = manifest["clients"].get(client)
    return str(entry.get("registration")) if isinstance(entry, dict) else "unproven"


def require_active(
    client: str,
    workdir: str | Path,
    *,
    session: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Raise `RegistrationRefusal` unless the client's account registration is installed, reviewed and (when the
    client exposes its session) was loaded by this very session. None = this consumer is not on the account pin."""

    env = os.environ if environ is None else environ
    if client not in ACCOUNT_CLIENTS:
        return None
    root = consumer_root(workdir)
    registration = registration_of(root, client)
    if registration is None or registration == "project":
        return None
    if registration != "account":
        raise RegistrationRefusal(
            "hooks_inactive",
            f"{client} is registration={registration}: its global hook mechanism is not proven, so this session has no process protection",
            "none from this card: the host stays visibly unprotected until a follow-up proves its global mechanism",
        )
    status = cf_shim.status(client, root)
    if not status["shim_installed"]:
        raise RegistrationRefusal("hooks_inactive", f"the account shim is not installed (no hooks run for {client} in this pin)")
    if not status["registered"]:
        raise RegistrationRefusal("hooks_inactive", f"{client} has no Covenant Flow account registration")
    if not status["registration"]["reviewed"]:
        raise RegistrationRefusal("hooks_unreviewed", f"the {client} account registration or the shim was not reviewed by the operator")
    adapter = status["adapter"] or {}
    if adapter.get("missing"):
        raise RegistrationRefusal("adapter_missing", f"pinned adapter file(s) absent: {', '.join(adapter['missing'][:5])}", "re-run `install.sh --pin <tag>`")
    if adapter.get("divergent"):
        raise RegistrationRefusal("adapter_divergent", f"adapter file(s) differ from the pinned manifest: {', '.join(adapter['divergent'][:5])}", "re-run `install.sh --pin <tag>` or review the change and run `cf_shim.py trust --record`")
    if not adapter.get("reviewed"):
        raise RegistrationRefusal("hooks_unreviewed", f"the pinned {client} adapter was not reviewed by the operator")
    beat = None
    variable = SESSION_VARIABLES.get(client)
    if variable is not None:
        identity = session or env.get(variable) or ""
        beat = cf_shim.read_heartbeat(client, identity)
        if beat is None:
            raise RegistrationRefusal(
                "hooks_inactive",
                f"no shim heartbeat for this {client} session: the account hooks did not run at its start (registration absent, disabled or reviewed by the host later)",
            )
        if beat.get("registration_digest") != status["registration"]["digest"]:
            raise RegistrationRefusal("hooks_changed", "the account registration changed after this session started", "start a new session")
    return {"mode": "account", "status": status, "heartbeat": beat, "root": str(root)}
