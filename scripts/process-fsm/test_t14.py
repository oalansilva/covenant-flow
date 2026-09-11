from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from t14 import (  # noqa: E402
    T14Error,
    LiveT14Runner,
    _overlay_health_url,
    classify_qa_gate,
    measure_checks_green,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class Scripted:
    def __init__(self, responses: list[subprocess.CompletedProcess[str]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):  # noqa: ANN001
        self.calls.append(list(args))
        if not self.responses:
            raise AssertionError(f"unexpected call {args}")
        return self.responses.pop(0)


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _checks_ndjson(*rows: dict) -> str:
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def test_measure_checks_green_qa_gate_pass():
    scripted = Scripted(
        [
            _ok(json.dumps([{"number": 99, "headRefOid": "abc"}])),
            _ok(
                _checks_ndjson(
                    {"name": "qa-gate", "status": "completed", "conclusion": "success"},
                    {"name": "other", "status": "completed", "conclusion": "failure"},
                )
            ),
        ]
    )
    assert measure_checks_green("632", "card-632-t14-live-done", runner=scripted) is True
    assert scripted.calls[0][scripted.calls[0].index("--head") + 1] == "card-632-t14-live-done"
    assert "api" in scripted.calls[1]


def test_measure_checks_green_other_failure_does_not_block():
    scripted = Scripted(
        [
            _ok(json.dumps([{"number": 99, "headRefOid": "abc"}])),
            _ok(
                _checks_ndjson(
                    {"name": "qa-gate", "status": "completed", "conclusion": "success"},
                    {"name": "other", "status": "completed", "conclusion": "failure"},
                ),
                returncode=0,
            ),
        ]
    )
    assert measure_checks_green("632", "card-632-t14-live-done", runner=scripted) is True


def test_measure_checks_green_missing_or_fail():
    empty = Scripted([_ok("[]")])
    assert measure_checks_green("632", "card-632-x", runner=empty) is False
    failed = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok(_checks_ndjson({"name": "qa-gate", "status": "completed", "conclusion": "failure"})),
        ]
    )
    assert measure_checks_green("632", "card-632-x", runner=failed) is False
    missing = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok(_checks_ndjson({"name": "lint", "status": "completed", "conclusion": "success"})),
        ]
    )
    assert measure_checks_green("632", "card-632-x", runner=missing) is False


def test_measure_checks_green_error_is_false():
    boom = Scripted([_ok("{not-json")])
    assert measure_checks_green("632", "card-632-x", runner=boom) is False


def test_classify_qa_gate_no_pr():
    empty = Scripted([_ok("[]")])
    assert classify_qa_gate("801", "card-801-x", runner=empty) == {"ok": False, "reason": "no_pr"}
    assert classify_qa_gate("801", None, runner=Scripted([])) == {"ok": False, "reason": "no_pr"}
    no_head = Scripted([_ok(json.dumps([{"number": 1}]))])
    assert classify_qa_gate("801", "card-801-x", runner=no_head) == {"ok": False, "reason": "no_pr"}


def test_classify_qa_gate_pending():
    scripted = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok(_checks_ndjson({"name": "qa-gate", "status": "in_progress", "conclusion": ""})),
        ]
    )
    assert classify_qa_gate("801", "card-801-x", runner=scripted) == {
        "ok": False,
        "reason": "qa-gate pending",
    }


def test_classify_qa_gate_failed_missing_skipped_api():
    missing = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok(_checks_ndjson({"name": "lint", "status": "completed", "conclusion": "success"})),
        ]
    )
    assert classify_qa_gate("801", "card-801-x", runner=missing) == {
        "ok": False,
        "reason": "qa-gate failed",
    }
    skipped = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok(_checks_ndjson({"name": "qa-gate", "status": "completed", "conclusion": "skipped"})),
        ]
    )
    assert classify_qa_gate("801", "card-801-x", runner=skipped)["reason"] == "qa-gate failed"
    cancelled = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok(_checks_ndjson({"name": "qa-gate", "status": "completed", "conclusion": "cancelled"})),
        ]
    )
    assert classify_qa_gate("801", "card-801-x", runner=cancelled)["reason"] == "qa-gate failed"
    api_err = Scripted(
        [
            _ok(json.dumps([{"number": 1, "headRefOid": "abc"}])),
            _ok("", returncode=1),
        ]
    )
    assert classify_qa_gate("801", "card-801-x", runner=api_err) == {
        "ok": False,
        "reason": "qa-gate failed",
    }
    pr_json = Scripted([_ok("{not-json")])
    assert classify_qa_gate("801", "card-801-x", runner=pr_json)["reason"] == "qa-gate failed"


def test_classify_qa_gate_ok():
    scripted = Scripted(
        [
            _ok(json.dumps([{"number": 99, "headRefOid": "abc"}])),
            _ok(
                _checks_ndjson(
                    {"name": "qa-gate", "status": "completed", "conclusion": "success"},
                    {"name": "other", "status": "completed", "conclusion": "failure"},
                )
            ),
        ]
    )
    assert classify_qa_gate("801", "card-801-x", runner=scripted) == {"ok": True, "reason": None}


def test_t14_health_url_uses_dev_not_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "t14.try_load_overlay",
        lambda _root: {
            "environments": {"dev": {"url": "https://dev.example.test"}},
            "release": {"health_url": "https://prod.example.test/api/health"},
        },
    )
    assert _overlay_health_url() == "https://dev.example.test/api/health"


def _git(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    assert proc.returncode == 0


def test_sync_dirty_raises_before_mutate(tmp_path: Path):
    _git(["git", "init"], tmp_path)
    _git(["git", "config", "user.email", "t14@test"], tmp_path)
    _git(["git", "config", "user.name", "t14"], tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(["git", "add", "a.txt"], tmp_path)
    _git(["git", "commit", "-m", "init"], tmp_path)
    (tmp_path / "dirt.txt").write_text("nope\n", encoding="utf-8")
    calls: list[list[str]] = []

    def wrapped(args, **kwargs):  # noqa: ANN001
        calls.append(list(args))
        return subprocess.run(args, **kwargs)

    runner = LiveT14Runner(source=tmp_path, restart_path=tmp_path / "restart", runner=wrapped)
    with pytest.raises(T14Error, match="dirty") as exc:
        runner.sync_dev_source()
    text = str(exc.value)
    assert str(tmp_path) in text
    assert "dirt.txt" in text
    assert any("--porcelain" in c for c in calls)
    assert not any("reset" in c for c in calls)
    assert not any(len(c) >= 4 and c[3] == "merge" for c in calls)
    assert not any(len(c) >= 4 and c[3] == "checkout" for c in calls)


def test_restart_rejects_noncanonical_path_on_canonical_source(tmp_path: Path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    runner = LiveT14Runner(
        source=canonical,
        restart_path=tmp_path / "restart",
        canonical_restart=canonical / "restart",
    )
    with pytest.raises(T14Error, match="path"):
        runner.restart()
