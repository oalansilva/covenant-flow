from __future__ import annotations

import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fsm import load_fsm  # noqa: E402
from paging import page  # noqa: E402

TODO_STUB = "Próximo evento = iniciar_design. Não apply. Não /opsx:new ainda."
GRILL_CARD = REPO / ".cursor" / "skills" / "grill-card" / "SKILL.md"
GRILLING = REPO / ".cursor" / "skills" / "grilling" / "SKILL.md"
ALAN_WORKFLOW = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
GROK_GRILL_CARD = REPO / ".grok" / "skills" / "grill-card" / "SKILL.md"
GROK_GRILLING = REPO / ".grok" / "skills" / "grilling" / "SKILL.md"
HERMES = Path("/srv/knowledge/hermes-second-brain/skills")
CODEX = Path.home() / ".codex" / "skills"
HOST_TOOLS = ("AskUserQuestion", "ask_user_question")
DOD_NEEDLES = (
    "CONTEXT.md",
    "docs/adr",
    "process_event priorizar",
    "/opsx:",
    "disable-model-invocation: false",
    "grill-card: fronteira vazia; história no body; à espera de T1 (Alan).",
)


def _regular_skill(path: Path) -> None:
    assert path.is_file(), path
    assert not path.is_symlink(), path
    assert not stat.S_ISLNK(path.stat().st_mode), path


def _resolve(bound: str, git: str) -> object:
    def inner(cwd, path, issue_id=None, status=None):
        return {"q": None, "bound_card": bound, "q_git": git}

    return inner


def _provider(status: str | None):
    def inner(bound: str | None) -> str | None:
        assert bound == "613"
        return status

    return inner


def test_grill_skills_are_regular_files() -> None:
    _regular_skill(GRILL_CARD)
    _regular_skill(GRILLING)
    skills = REPO / ".cursor" / "skills"
    assert not (skills / "grill-with-docs").exists()


def test_grill_card_text_has_prohibitions() -> None:
    text = GRILL_CARD.read_text(encoding="utf-8")
    for needle in DOD_NEEDLES:
        assert needle in text, needle
    assert "bound_card" in text
    assert "Em Refinamento" in text
    assert "Não exige branch `card-<id>-*`" in text
    assert "sessão bound a `card-<id>-*`" not in text


def test_grill_skills_not_dual_written() -> None:
    for name in ("grill-card", "grilling"):
        assert not (HERMES / name).exists()
        assert not (CODEX / name).exists()


def test_em_refinamento_stub_names_grill() -> None:
    fsm = load_fsm()
    stub = str(fsm["context_file"]["Em Refinamento"])
    assert "grill-card" in stub
    assert "T1" in stub
    assert "CONTEXT.md" in stub
    todo = str(fsm["context_file"]["Todo"])
    assert TODO_STUB in todo
    design = str(fsm["context_file"]["Design"])
    assert "sintetizar" in design
    assert "reentrevistar" in design
    tools = fsm["enabled_tools"]["Em Refinamento"]
    assert list(tools) == ["issue_edit", "comment"]
    assert "write_openspec" not in tools
    transitions = {row["id"]: row for row in fsm["transitions"]}
    assert transitions["T0"]["to"] == "Em Refinamento"
    assert transitions["T1"]["actor"] == "Alan"
    assert transitions["T1"]["from"] == "Em Refinamento"
    assert transitions["T1"]["to"] == "Todo"


def _near(text: str, left: str, right: str, window: int = 80) -> bool:
    start = 0
    while True:
        pos = text.find(left, start)
        if pos < 0:
            return False
        lo = max(0, pos - window)
        hi = min(len(text), pos + len(left) + window)
        if right in text[lo:hi]:
            return True
        start = pos + 1


def _heading_section(text: str, heading: str) -> str:
    start = text.find(heading)
    assert start >= 0, heading
    rest = text[start + len(heading) :]
    nxt = rest.find("\n## ")
    return heading + (rest if nxt < 0 else rest[:nxt])


def test_grill_card_host_options_needles() -> None:
    text = GRILL_CARD.read_text(encoding="utf-8")
    for needle in HOST_TOOLS:
        assert needle in text, needle
    assert "N≥2" in text or "N>=2" in text
    assert _near(text, "Other", "não conta")


def test_grilling_vendor_stays_matt() -> None:
    text = GRILLING.read_text(encoding="utf-8")
    assert "❓" in text
    assert "➡️" in text
    for needle in HOST_TOOLS:
        assert needle not in text, needle


def test_alan_workflow_grill_card_relays_all_options() -> None:
    text = ALAN_WORKFLOW.read_text(encoding="utf-8")
    section = _heading_section(text, "## Grill-card")
    assert "todas as options" in section
    assert "não colapsa" in section


def test_grok_grill_stubs_do_not_name_host_tools() -> None:
    for path in (GROK_GRILL_CARD, GROK_GRILLING):
        text = path.read_text(encoding="utf-8")
        for needle in HOST_TOOLS:
            assert needle not in text, (path, needle)


def test_em_refinamento_page_stays_short() -> None:
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("Em Refinamento"),
    )
    ctx = result["additional_context"]
    assert "grill-card" in ctx
    assert "Chat" in ctx
    assert len(ctx.splitlines()) <= 20


_EMPH_WORD = re.compile(r"(?<![a-z0-9])_([a-z0-9]+)_(?![a-z0-9])")


def _plain(text: str) -> str:
    s = str(text).lower()
    s = s.replace("`", "")
    s = s.replace("**", "")
    s = s.replace("*", "")
    s = _EMPH_WORD.sub(r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def test_n2_client_labelled_grill_copy() -> None:
    assert "não chama a ferramenta do host" in _plain("**não** chama a ferramenta do host")
    assert _plain("ask_user_question") == "ask_user_question"
    assert "o pai spawna" in _plain("O **pai** spawna")
    assert "root chama ask_user_question" not in _plain(
        "O runtime root nunca chama ask_user_question."
    )
    assert "root chama ask_user_question" not in _plain(
        "O runtime root não chama. chama ask_user_question."
    )
    assert "root chama ask_user_question" in _plain(
        "O runtime root chama `ask_user_question`."
    )

    text = GRILL_CARD.read_text(encoding="utf-8")
    cursor = _heading_section(text, "## Cliente: Cursor e Grok")
    dsh = _heading_section(text, "## Cliente: dsh")
    full, cursor_p, dsh_p = map(_plain, (text, cursor, dsh))
    for frase in (
        "não chama a ferramenta do host",
        "o pai spawna",
        "dump d5",
        "quem chama",
    ):
        assert full.count(frase) == cursor_p.count(frase), frase
        assert cursor_p.count(frase) >= 1, frase
    assert "root chama ask_user_question" in dsh_p
    assert "não chama ask_user_question" not in dsh_p
    assert "não chama a ferramenta do host" not in dsh_p
    assert "recomendação vive só" in dsh_p
    assert "não copie" in dsh_p
    assert "➡️" in dsh
    assert "com o host no ar" in cursor_p
    for needle in HOST_TOOLS:
        assert needle in cursor, needle
    if "## Precondição" in text:
        pre = _plain(_heading_section(text, "## Precondição"))
        for needle in (
            "filho",
            "spawna",
            "relaying",
            "dump d5",
            "ask_user_question",
            "askuserquestion",
            "não chama",
        ):
            assert needle not in pre, needle
    cursor_start = text.find("## Cliente: Cursor e Grok")
    cursor_end = cursor_start + len(cursor)
    dsh_start = text.find("## Cliente: dsh")
    dsh_end = dsh_start + len(dsh)
    for match in re.finditer(r"^## [^#].*$", text, re.M):
        heading = match.group(0)
        if "perguntas da rodada" not in _plain(heading):
            continue
        off = match.start()
        assert cursor_start <= off < cursor_end or dsh_start <= off < dsh_end, heading

    cf = _heading_section(ALAN_WORKFLOW.read_text(encoding="utf-8"), "## Grill-card")
    assert "Cliente dsh:" in cf
    assert "O **pai** spawna" in cf
    assert "todas as options" in cf
    assert "não colapsa" in cf

    guard_src = (ROOT / "guard.py").read_text(encoding="utf-8")
    for needle in ("grill-card", "dsh_grill_spawn", "isGrillShapedSpawn"):
        assert needle not in guard_src, needle

    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    nonempty = [ln for ln in agents.splitlines() if ln.strip()]
    assert len(nonempty) <= 40
    assert "ask_user_question" not in agents

    stub = (REPO / ".dsh" / "skills" / "grill-card" / "SKILL.md").read_text(encoding="utf-8")
    body = stub.split("---", 2)[2]
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
    assert "MUST Read" in stub

    if (REPO / "install.sh").is_file():
        adapter = (ROOT / "test_dsh_adapter.py").read_text(encoding="utf-8")
        assert 'overlay["pin"] == "v1.1.4"' in adapter
