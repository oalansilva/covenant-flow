"""Consumer overlay `.covenant-flow/overlay.yaml`. No GitHub. No law table."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from fsm import load_fsm

OVERLAY_REL = Path(".covenant-flow") / "overlay.yaml"
SCHEMA_MAJOR = 1
LAW_NEEDLES = ("fail_closed_asymmetric", "illegal_edges", "exclusive_group")
LAW_TOP_KEYS = frozenset(
    {
        "states",
        "transitions",
        "illegal_events",
        "illegal_edges",
        "invariants",
        "enabled_tools",
        "enabled_events",
        "context_file",
        "product_globs",
        "design_globs",
    }
)
ENV_KEYS = ("source", "url", "db", "services")
RELEASE_KEYS = ("restart", "migrate", "build", "health_url")
CLIENT_KEYS = ("cursor", "grok", "opencode")


class OverlayError(ValueError):
    pass


class OverlayMissing(OverlayError):
    pass


class OverlayInvalid(OverlayError):
    pass


def column_names(fsm: Mapping[str, Any] | None = None) -> list[str]:
    table = fsm if fsm is not None else load_fsm()
    names = [str(item) for item in (table.get("states") or [])]
    if len(names) != 12:
        raise OverlayInvalid(f"yaml must declare 12 column names, got {len(names)}")
    return names


def find_overlay_path(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for folder in (cur, *cur.parents):
        candidate = folder / OVERLAY_REL
        if candidate.is_file():
            return candidate
    return None


def empty_template(fsm: Mapping[str, Any] | None = None) -> dict[str, Any]:
    names = column_names(fsm)
    return {
        "board": {
            "owner": "",
            "number": None,
            "status_field_id": "",
            "project_id": "",
            "status_options": {name: "" for name in names},
        },
        "repo": "",
        "product_globs": [],
        "design_globs": [],
        "integration_branch": "",
        "production_branch": "",
        "pin": "",
        "canonical_paths": {},
        "forbidden_worktrees": [],
        "overlay_doc": "",
        "clients": {name: {"auto": False} for name in CLIENT_KEYS},
        "impeccable": {"critique_dir": "", "design_md": ""},
        "runtime": {"playwright": ""},
        "environments": {
            "dev": {"source": "", "url": "", "db": "", "services": []},
        },
        "release": {key: "" for key in RELEASE_KEYS},
    }


def dump_template(fsm: Mapping[str, Any] | None = None) -> str:
    data = empty_template(fsm)
    header = (
        "# Covenant Flow overlay (machine). Human prose lives at overlay_doc.\n"
        "# --init leaves keys empty. Do not copy the yaml law table here.\n"
        f"# schema major {SCHEMA_MAJOR}; a breaking key change is v{SCHEMA_MAJOR + 1}.0.0.\n"
        "# environments.prod is optional (omit the key for DEV-only projects).\n"
    )
    body = yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return header + body


def _as_mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise OverlayInvalid(f"{label} must be a mapping")
    return raw


def _as_list(raw: Any, label: str) -> list[Any]:
    if not isinstance(raw, list):
        raise OverlayInvalid(f"{label} must be a list")
    return raw


def _nonempty_str(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise OverlayInvalid(f"{label} must be a non-empty string")
    return raw.strip()


def _filled_env(raw: Any, label: str) -> None:
    env = _as_mapping(raw, label)
    for key in ENV_KEYS:
        if key not in env:
            raise OverlayInvalid(f"{label}.{key} is required")
    _nonempty_str(env.get("source"), f"{label}.source")
    _nonempty_str(env.get("url"), f"{label}.url")
    _nonempty_str(env.get("db"), f"{label}.db")
    services = env.get("services")
    if not isinstance(services, list) or not services:
        raise OverlayInvalid(f"{label}.services must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in services):
        raise OverlayInvalid(f"{label}.services items must be non-empty strings")


def join_status_options(data: Mapping[str, Any], fsm: Mapping[str, Any] | None = None) -> dict[str, str]:
    names = column_names(fsm)
    board = _as_mapping(data.get("board"), "board")
    options = _as_mapping(board.get("status_options"), "board.status_options")
    got = list(options.keys())
    if got != names:
        raise OverlayInvalid(
            "board.status_options names must equal the 12 yaml column names in order"
        )
    joined: dict[str, str] = {}
    for name in names:
        value = options.get(name)
        if not isinstance(value, str) or not value.strip():
            raise OverlayInvalid(f"board.status_options[{name!r}] id is missing")
        joined[name] = value.strip()
    return joined


def _reject_law_table(raw_text: str, data: Mapping[str, Any]) -> None:
    for needle in LAW_NEEDLES:
        if needle in raw_text:
            raise OverlayInvalid("overlay must not copy T0–T17 / I1–I9")
    overlap = LAW_TOP_KEYS.intersection(data)
    # product_globs/design_globs live in overlay by design; they are not the yaml law table.
    overlap -= {"product_globs", "design_globs"}
    if overlap:
        raise OverlayInvalid(f"overlay must not copy law keys {sorted(overlap)}")


def validate_overlay(
    data: Mapping[str, Any],
    *,
    fsm: Mapping[str, Any] | None = None,
    require_filled: bool = True,
    raw_text: str = "",
) -> None:
    if not isinstance(data, dict):
        raise OverlayInvalid("overlay must be a mapping")
    if raw_text:
        _reject_law_table(raw_text, data)
    required = (
        "board",
        "repo",
        "product_globs",
        "design_globs",
        "integration_branch",
        "production_branch",
        "pin",
        "canonical_paths",
        "forbidden_worktrees",
        "overlay_doc",
        "clients",
        "impeccable",
        "runtime",
        "environments",
        "release",
    )
    missing = [key for key in required if key not in data]
    if missing:
        raise OverlayInvalid(f"missing keys: {missing}")
    board = _as_mapping(data.get("board"), "board")
    for key in ("owner", "number", "status_field_id", "status_options"):
        if key not in board:
            raise OverlayInvalid(f"board.{key} is required")
    _as_mapping(board.get("status_options"), "board.status_options")
    _as_list(data.get("product_globs"), "product_globs")
    _as_list(data.get("design_globs"), "design_globs")
    _as_mapping(data.get("canonical_paths"), "canonical_paths")
    _as_list(data.get("forbidden_worktrees"), "forbidden_worktrees")
    _as_mapping(data.get("clients"), "clients")
    _as_mapping(data.get("impeccable"), "impeccable")
    runtime = _as_mapping(data.get("runtime"), "runtime")
    if "playwright" not in runtime:
        raise OverlayInvalid("runtime.playwright is required")
    environments = _as_mapping(data.get("environments"), "environments")
    if "dev" not in environments:
        raise OverlayInvalid("environments.dev is required")
    _as_mapping(environments.get("dev"), "environments.dev")
    if "prod" in environments and environments.get("prod") is not None:
        _as_mapping(environments.get("prod"), "environments.prod")
    release = _as_mapping(data.get("release"), "release")
    for key in RELEASE_KEYS:
        if key not in release:
            raise OverlayInvalid(f"release.{key} is required")
    if not require_filled:
        # Join names (ids may be empty on --init).
        names = column_names(fsm)
        got = list((_as_mapping(board.get("status_options"), "board.status_options")).keys())
        if got != names:
            raise OverlayInvalid(
                "board.status_options names must equal the 12 yaml column names in order"
            )
        return
    _nonempty_str(board.get("owner"), "board.owner")
    number = board.get("number")
    if not isinstance(number, int) or number < 1:
        raise OverlayInvalid("board.number must be a positive int")
    _nonempty_str(board.get("status_field_id"), "board.status_field_id")
    join_status_options(data, fsm)
    _nonempty_str(data.get("repo"), "repo")
    product = data.get("product_globs") or []
    design = data.get("design_globs") or []
    if not product or not all(isinstance(item, str) and item.strip() for item in product):
        raise OverlayInvalid("product_globs must be a non-empty list of strings")
    if not design or not all(isinstance(item, str) and item.strip() for item in design):
        raise OverlayInvalid("design_globs must be a non-empty list of strings")
    _nonempty_str(data.get("integration_branch"), "integration_branch")
    _nonempty_str(data.get("production_branch"), "production_branch")
    pin = _nonempty_str(data.get("pin"), "pin")
    if not pin.startswith("v"):
        raise OverlayInvalid("pin must be a semver tag vMAJOR.MINOR.PATCH")
    _nonempty_str(data.get("overlay_doc"), "overlay_doc")
    clients = _as_mapping(data.get("clients"), "clients")
    for name in CLIENT_KEYS:
        if name not in clients:
            raise OverlayInvalid(f"clients.{name} is required")
    _filled_env(environments.get("dev"), "environments.dev")
    if "prod" in environments and environments.get("prod") is not None:
        _filled_env(environments.get("prod"), "environments.prod")


def empty_required_keys(data: Mapping[str, Any], fsm: Mapping[str, Any] | None = None) -> list[str]:
    """Keys that --init leaves empty (for the skill to list)."""
    empty: list[str] = []
    board = data.get("board") if isinstance(data.get("board"), dict) else {}
    for key in ("owner", "status_field_id"):
        if not str(board.get(key) or "").strip():
            empty.append(f"board.{key}")
    if not isinstance(board.get("number"), int):
        empty.append("board.number")
    options = board.get("status_options") if isinstance(board.get("status_options"), dict) else {}
    for name in column_names(fsm):
        if not str(options.get(name) or "").strip():
            empty.append(f"board.status_options.{name}")
    for key in (
        "repo",
        "integration_branch",
        "production_branch",
        "pin",
        "overlay_doc",
    ):
        if not str(data.get(key) or "").strip():
            empty.append(key)
    if not (data.get("product_globs") or []):
        empty.append("product_globs")
    if not (data.get("design_globs") or []):
        empty.append("design_globs")
    return empty


def load_overlay(
    start: Path | None = None,
    *,
    fsm: Mapping[str, Any] | None = None,
    require_filled: bool = True,
) -> dict[str, Any]:
    path = find_overlay_path(start)
    if path is None:
        raise OverlayMissing("missing .covenant-flow/overlay.yaml")
    raw_text = path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw_text)
    if not isinstance(loaded, dict):
        raise OverlayInvalid("overlay must be a mapping")
    validate_overlay(loaded, fsm=fsm, require_filled=require_filled, raw_text=raw_text)
    return loaded


def try_load_overlay(start: Path | None = None, *, require_filled: bool = True) -> dict[str, Any] | None:
    try:
        return load_overlay(start, require_filled=require_filled)
    except OverlayError:
        return None


def status_field_id(overlay: Mapping[str, Any] | None) -> str:
    if not overlay:
        return ""
    return str(((overlay.get("board") or {}).get("status_field_id")) or "").strip()


def status_options(overlay: Mapping[str, Any] | None) -> dict[str, str]:
    if not overlay:
        return {}
    raw = ((overlay.get("board") or {}).get("status_options")) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v).strip() for k, v in raw.items() if str(v).strip()}


def status_option_ids(overlay: Mapping[str, Any] | None) -> frozenset[str]:
    return frozenset(status_options(overlay).values())


def board_project_id(overlay: Mapping[str, Any] | None) -> str:
    if not overlay:
        return ""
    return str(((overlay.get("board") or {}).get("project_id")) or "").strip()


def repo_slug(overlay: Mapping[str, Any] | None) -> str:
    if not overlay:
        return ""
    return str(overlay.get("repo") or "").strip()


def repo_owner_name(overlay: Mapping[str, Any] | None) -> tuple[str, str]:
    slug = repo_slug(overlay)
    if "/" not in slug:
        return "", ""
    owner, name = slug.split("/", 1)
    return owner, name


def board_owner_number(overlay: Mapping[str, Any] | None) -> tuple[str, int | None]:
    if not overlay:
        return "", None
    board = overlay.get("board") or {}
    owner = str(board.get("owner") or "").strip()
    number = board.get("number")
    return owner, number if isinstance(number, int) else None


def glob_lists(overlay: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    if not overlay:
        return [], []
    product = [str(item) for item in (overlay.get("product_globs") or [])]
    design = [str(item) for item in (overlay.get("design_globs") or [])]
    return product, design


def integration_branches(overlay: Mapping[str, Any] | None) -> frozenset[str]:
    if not overlay:
        return frozenset()
    names = []
    for key in ("integration_branch", "production_branch"):
        value = str(overlay.get(key) or "").strip()
        if value:
            names.append(value)
    return frozenset(names)


def release_hooks_empty(overlay: Mapping[str, Any] | None) -> bool:
    if not overlay:
        return True
    release = overlay.get("release") or {}
    if not isinstance(release, dict):
        return True
    return not any(str(release.get(key) or "").strip() for key in RELEASE_KEYS)


def write_init(target: Path, fsm: Mapping[str, Any] | None = None) -> Path:
    dest = target / OVERLAY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    dest.write_text(dump_template(fsm), encoding="utf-8")
    return dest


def set_pin(target: Path, pin: str) -> None:
    path = target / OVERLAY_REL
    if not path.is_file():
        raise OverlayMissing("missing overlay")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OverlayInvalid("overlay must be a mapping")
    data["pin"] = pin
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def render_agents(overlay: Mapping[str, Any]) -> str:
    owner, number = board_owner_number(overlay)
    doc = str(overlay.get("overlay_doc") or "").strip() or "docs/overlay.md"
    board = f"https://github.com/users/{owner}/projects/{number}" if owner and number else ""
    lines = [
        "# AGENTS.md — always-on curto",
        "",
        f"Board: {board}" if board else "Board: (overlay board.owner / board.number)",
        "",
        "Resolva `(q, bound_card, q_git)`; não invente aresta.",
        "Chat é wording, não autorização. NLU ≠ δ. `implemente` ∉ δ.",
        "`Em Refinamento` é a entrada. Não pular Design / Aprovação de Design.",
        "`Todo` não é código; próxima = `iniciar_design` via `process_event`.",
        "Código / `/opsx:apply` só após `Status=Pronto para Dev` (T8).",
        "Alan único em T1/T7/T15. Agent não arrasta essas colunas. T16 = `process_event fechar_release`.",
        "Clientes: Cursor Agent (cooperativo); Grok Build, OpenCode e dsh (cooperativos até ensaio deny na branch de integração).",
        "Não reivindique modo Auto no Cursor, no Grok, no OpenCode nem no dsh.",
        "Skills canônicas: `.cursor/skills/` neste repo. Overlay on-demand; runbook = skill `covenant-flow`.",
        "",
        "Quando a tarefa precisar de portas/URLs, Drive, banco ou release/lote/PROD:",
        "",
        f"`Read {doc}`",
        "",
        "Fora desses tópicos, não carregue o overlay.",
        "",
    ]
    nonempty = [ln for ln in lines if ln.strip()]
    if len(nonempty) > 40:
        raise OverlayInvalid("AGENTS.md template exceeded 40 non-empty lines")
    return "\n".join(lines)
