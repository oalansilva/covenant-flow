from __future__ import annotations

import json
from pathlib import Path

import pytest

import claude_proxy
import claude_review
from codex_review import ReviewDiffError
from claude_fixtures import World
from model_selection_fixtures import machine_models  # noqa: F401

DIFF = "c" * 64
WAVE = "wave-1101-a"


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def born(world, role, *, agent, call, msg_id="m-wave", tools=("Read", "Grep"), diff=DIFF, **kw):
    cap, path, task, prepared = world.prepare(role, diff=diff, wave=WAVE)
    world.spawn(cap, task, role=role, subagent_type=role, agent=agent, call_id=call, msg_id=msg_id, child_tools=tools, **kw)
    return cap, path, prepared


def record(world, role, path, prepared):
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", role, "--band", "execucao", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 0


def wave(world, **second):
    first = born(world, "diff-reviewer", agent="aaaabbbbccccdddd1", call="toolu_1")
    other = born(world, "code-reviewer", agent="eeeeffff00001111a", call="toolu_2", **second)
    record(world, "diff-reviewer", first[1], first[2])
    record(world, "code-reviewer", other[1], other[2])
    return first, other


def verify(world, sha=DIFF):
    return claude_review.verify_wave(root=world.repo, wave_id=WAVE, expected_sha256=sha, bound_card="1101")


def test_wave_passes_with_two_distinct_read_only_children_in_one_message(world):
    wave(world)
    digest, ids = verify(world)
    assert digest == DIFF and ids == ("aaaabbbbccccdddd1", "eeeeffff00001111a")


def test_wave_rejects_reviewers_born_in_different_parent_messages(world):
    wave(world, msg_id="m-later")
    with pytest.raises(ReviewDiffError, match="same parent message"):
        verify(world)


def test_wave_rejects_a_reviewer_that_used_a_write_tool(world):
    first = born(world, "diff-reviewer", agent="aaaabbbbccccdddd1", call="toolu_1")
    other = born(world, "code-reviewer", agent="eeeeffff00001111a", call="toolu_2", tools=("Read", "Edit"))
    record(world, "diff-reviewer", first[1], first[2])
    # the collector itself refuses a reviewer with Edit: no proxy can exist for it
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(other[1]), "--activity", "code-reviewer", "--band", "execucao", "--birth", other[2]["birth"], "--wait-seconds", "0"]) == 2
    with pytest.raises(ReviewDiffError, match="exactly two"):
        verify(world)


def test_wave_rejects_another_diff_digest_missing_role_and_wrong_card(world):
    wave(world)
    with pytest.raises(ReviewDiffError, match="expected diff"):
        verify(world, sha="d" * 64)
    with pytest.raises(ReviewDiffError, match="not bound to card"):
        claude_review.verify_wave(root=world.repo, wave_id=WAVE, expected_sha256=DIFF, bound_card="9999")
    with pytest.raises(ReviewDiffError, match="64 hexadecimal"):
        verify(world, sha="short")


def test_wave_rejects_duplicate_role_and_tampered_proxy_records(world):
    wave(world)
    log = world.repo / ".cursor/tmp/claude-child-proxies.jsonl"
    lines = log.read_text().splitlines()
    tampered = [json.loads(line) for line in lines]
    tampered[1]["observed_model"] = "claude-opus-5-5"
    log.write_text("\n".join(json.dumps(x) for x in tampered) + "\n")
    with pytest.raises(ReviewDiffError, match="observed model pair differs"):
        verify(world)
    dup = [json.loads(line) for line in lines]
    dup[1]["activity"] = "diff-reviewer"
    log.write_text("\n".join(json.dumps(x) for x in dup) + "\n")
    with pytest.raises(ReviewDiffError, match="duplicate"):
        verify(world)


def test_wave_rejects_forged_read_only_claim_by_recomputing_from_the_transcript(world):
    first, other = wave(world)
    log = world.repo / ".cursor/tmp/claude-child-proxies.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    entries[0]["tools_used"] = ["Read", "Bash"]
    log.write_text("\n".join(json.dumps(x) for x in entries) + "\n")
    with pytest.raises(ReviewDiffError, match="Read/Grep/Glob"):
        verify(world)
    entries[0]["tools_used"] = ["Read", "Grep"]
    entries[0]["child_id"] = "forgedforgedforged"
    log.write_text("\n".join(json.dumps(x) for x in entries) + "\n")
    with pytest.raises(ReviewDiffError, match="provenance rejected"):
        verify(world)


def test_wave_with_changed_selection_between_births_is_rejected(world):
    import yaml
    from model_selection import SelectionError
    first = born(world, "diff-reviewer", agent="aaaabbbbccccdddd1", call="toolu_1")
    from model_selection_fixtures import document
    path = Path.home() / ".config/covenant-flow/model-selection.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["clients"]["claude"]["execucao"]["model"] = "claude-haiku-5-5"
    path.write_text(yaml.safe_dump(doc))
    from model_selection import compare_wave, resolve
    with pytest.raises(SelectionError, match="selection_changed"):
        compare_wave(first[0], resolve("claude", "execucao", role="code-reviewer"))
