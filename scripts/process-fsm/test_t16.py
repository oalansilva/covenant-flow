from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from t16 import (  # noqa: E402
    T16Error,
    classify_package,
    lote_git,
    measure_m_lote,
    parse_package_cards,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _ok(code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["scripts/release-guard", "post"], code, "", "")


def test_parse_package_cards_env_and_solo():
    assert parse_package_cards("617,618,617", None) == [617, 618]
    assert parse_package_cards("", "652") == [652]
    assert parse_package_cards(None, "#652") == [652]
    assert parse_package_cards("", None) == []
    assert parse_package_cards("nope", None) is None
    assert parse_package_cards("0", None) is None


def test_lote_git():
    assert lote_git("develop") is True
    assert lote_git("release-2026-08-21") is True
    assert lote_git("main") is False
    assert lote_git("card-652-x") is False


def test_wrong_fechar_release_git():
    from t16 import wrong_fechar_release_git

    assert wrong_fechar_release_git("main") is True
    assert wrong_fechar_release_git("docs-release") is True
    assert wrong_fechar_release_git("sync-2026-07-01") is True
    assert wrong_fechar_release_git("develop") is False
    assert wrong_fechar_release_git("release-2026-08-21") is False


def test_measure_m_lote_records_passed_package_not_raw_env(monkeypatch):
    monkeypatch.setenv("RELEASE_CARDS", " 0617, 618 ")
    passed = measure_m_lote(
        cwd=ROOT.parents[1],
        package="617,618",
        runner=lambda *a, **k: _ok(0),
    )
    assert passed.ok is True
    assert passed.context is not None
    assert passed.context.package == "617,618"
    fallback = measure_m_lote(runner=lambda *a, **k: _ok(0))
    assert fallback.context is not None
    assert fallback.context.package == " 0617, 618 "


def test_measure_m_lote_exit_codes():
    passed = measure_m_lote(runner=lambda *a, **k: _ok(0))
    assert bool(passed) is True
    assert passed.ok is True
    failed = measure_m_lote(
        runner=lambda *a, **k: subprocess.CompletedProcess(
            ["scripts/release-guard", "post"], 1, "BLOCKER: archive still active\n", ""
        )
    )
    assert bool(failed) is False
    assert failed.blockers == ("archive still active",)
    assert failed.fail_class == "post_failed"

    def boom(*a, **k):  # noqa: ANN001
        raise OSError("missing")

    crashed = measure_m_lote(runner=boom)
    assert bool(crashed) is False
    assert crashed.fail_class == "measure_failed"


def test_classify_package_skip_pronto_and_reject_done():
    homologado, pronto = classify_package(
        [617, 618],
        lambda bound: {"617": "Homologado", "618": "Pronto"}[str(bound)],
    )
    assert homologado == [617]
    assert pronto == [618]
    with pytest.raises(T16Error):
        classify_package([617], lambda bound: "Done")
    with pytest.raises(T16Error):
        classify_package([617], lambda bound: None)
