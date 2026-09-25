"""Filesystem helpers for atomic Codex adapter updates."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    """Atomically replace a file using a random, exclusively created sibling.

    Never open a predictable temporary path: a pre-existing symlink at such a
    path would otherwise redirect the write before the rename replaces it.
    """

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        current = destination.lstat()
    except FileNotFoundError:
        mode = 0o644
    else:
        mode = stat.S_IMODE(current.st_mode) if stat.S_ISREG(current.st_mode) else 0o644

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name[:40]}.cf-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
