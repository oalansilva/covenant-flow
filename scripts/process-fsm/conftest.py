"""Harness tests select their client explicitly, never inherit the invoking host."""
import pytest


@pytest.fixture(autouse=True)
def isolated_client_context(monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("COVENANT_CLIENT", raising=False)
    # Tests may run inside Claude Code itself; its identity and overrides must not leak in.
    for name in (
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_EFFORT",
        "CLAUDE_CODE_SUBAGENT_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
        "CLAUDE_CODE_EFFORT_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
