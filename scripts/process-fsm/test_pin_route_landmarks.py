"""The T5 clone-gate catalog is consumer data: the pin seeds it when absent and never touches it again."""

from __future__ import annotations

from pathlib import Path

import pytest

from design_clone_gate import CATALOG_REL
from test_codex_installer import INSTALL, ROOT, _pin, _target

pytestmark = pytest.mark.skipif(
    not INSTALL.is_file(), reason="installer integration tests require the product install.sh"
)

SEED = ROOT / CATALOG_REL


def test_pin_copies_the_seed_catalog_when_the_consumer_has_none(tmp_path: Path):
    target, _ = _target(tmp_path / "consumer")
    assert not (target / CATALOG_REL).exists()

    result = _pin(target)

    assert result.returncode == 0, result.stderr
    assert (target / CATALOG_REL).read_bytes() == SEED.read_bytes()


def test_pin_preserves_a_different_consumer_catalog_byte_for_byte(tmp_path: Path):
    target, _ = _target(tmp_path / "consumer")
    catalog = target / CATALOG_REL
    catalog.parent.mkdir(parents=True)
    own = SEED.read_bytes() + b"/combo/results:\n  selectors: ['.combo-page']\n  texts: ['Lista de opera\xc3\xa7\xc3\xb5es']\n"
    assert own != SEED.read_bytes()
    catalog.write_bytes(own)

    first = _pin(target)
    assert first.returncode == 0, first.stderr
    assert catalog.read_bytes() == own

    # A second pin over the same consumer keeps it too, and the rest of the tree is still synced.
    second = _pin(target)
    assert second.returncode == 0, second.stderr
    assert catalog.read_bytes() == own
    assert (target / "scripts/process-fsm/design_clone_gate.py").is_file()
