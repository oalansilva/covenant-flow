"""Machine/account selections. No repository override, picker or legacy fallback."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import subprocess
import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any, Mapping

import yaml

POLICY_PATH = Path(__file__).resolve().parents[2] / ".cursor/model-policy.yaml"
BANDS = ("juizo", "execucao")
CLIENTS = ("cursor", "codex", "grok", "opencode", "dsh")


class SelectionError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def _unique(loader: UniqueLoader, node: Any, deep: bool = False) -> dict:
    out = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in out:
            raise SelectionError(f"duplicate or non-string YAML key: {key!r}")
        out[key] = loader.construct_object(value_node, deep=deep)
    return out


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def selection_path() -> Path:
    return Path.home() / ".config/covenant-flow/model-selection.yaml"


def read_yaml(path: Path) -> tuple[dict, bytes]:
    try:
        body = path.read_bytes()
        data = yaml.load(body.decode("utf-8"), Loader=UniqueLoader)
    except (OSError, UnicodeError, yaml.YAMLError, SelectionError) as exc:
        raise SelectionError(f"cannot read {path}: {exc}; explicit migration required, no fallback") from exc
    if not isinstance(data, dict):
        raise SelectionError(f"expected YAML object: {path}")
    return data, body


def policy() -> dict:
    return read_yaml(POLICY_PATH)[0]


def role_band(role: str) -> str:
    band = policy()["roles"].get(role.lower())
    if band not in BANDS:
        raise SelectionError(f"unknown process role {role!r}; specify an exact policy role")
    return band


def request_role(arguments: Mapping) -> str:
    """Only native role/title fields classify; long prompt bodies cannot classify."""
    text = " ".join(str(arguments.get(k, "")) for k in ("agent_type", "subagent_type", "task_name", "description", "title"))
    text = text.lower().replace("_", "-")
    matches = [role for role in policy()["roles"] if re.search(r"(?<![a-z])" + re.escape(role) + r"(?![a-z])", text)]
    if len(matches) != 1:
        raise SelectionError(f"spawn role missing/ambiguous in native role/title fields: {text!r}")
    return matches[0]


def prompt_capture(arguments: Mapping, key: str = "model_selection_capture") -> dict:
    text = str(arguments.get("prompt") or arguments.get("message") or "")
    match = re.search(r"^" + re.escape(key) + r":\s*(\S+)\s*$", text, re.MULTILINE)
    if not match or not Path(match[1]).is_absolute():
        raise SelectionError(f"spawn prompt requires {key}: <absolute immutable JSON capture path>")
    return load_capture(match[1])


def validate_spawn(client: str, arguments: Mapping) -> dict:
    role = request_role(arguments)
    band = role_band(role)
    birth = validate_capture(prompt_capture(arguments), client=client, band=band, role=role)
    if arguments.get("resume") or arguments.get("resume_from") or arguments.get("task_id"):
        # Resume is not a new birth and must never select the current file pair.
        if any(k in arguments for k in ("model", "provider", "effort", "reasoning_effort", "variant")):
            raise SelectionError("resume cannot retune a living child; use its birth capture and verify observed runtime")
        return birth
    current = resolve(client, band, role=role)
    compare_wave(birth, current)
    if role in ("diff-reviewer", "code-reviewer", "assessment-a", "assessment-b"):
        compare_wave(prompt_capture(arguments, "model_selection_wave_capture"), birth)
    for key, value in birth["arguments"].items():
        if arguments.get(key) != value:
            raise SelectionError(f"{client}/{band}: explicit {key} mismatch; no inheritance/fallback")
    for key in ("provider", "model", "effort", "reasoning_effort", "reasoningEffort", "variant"):
        if key in arguments and key not in birth["arguments"]:
            raise SelectionError(f"{client}/{band}: unsupported spawn parameter {key}")
    return birth


def validate_document(data: Any) -> dict:
    p = policy()
    if not isinstance(data, dict) or set(data) != {"version", "clients"} or type(data.get("version")) is not int or data["version"] != p["schema_version"]:
        raise SelectionError("schema must contain only version: 1 and clients")
    clients = data["clients"]
    if not isinstance(clients, dict) or set(clients) - set(CLIENTS):
        raise SelectionError("clients must contain only cursor/codex/grok/opencode/dsh")
    for client, bands in clients.items():
        if not isinstance(bands, dict) or set(bands) - set(BANDS):
            raise SelectionError(f"{client}: only juizo/execucao bands are allowed")
        fields = set(p["clients"][client]["fields"])
        for band, entry in bands.items():
            if not isinstance(entry, dict) or set(entry) - fields:
                raise SelectionError(f"{client}/{band}: unknown selection fields")
            for key, value in entry.items():
                if not isinstance(value, str) or not value.strip() or value != value.strip():
                    raise SelectionError(f"{client}/{band}/{key}: non-empty unpadded string required")
    return data


def validate_entry(client: str, band: str, entry: Any, *, catalogue: Mapping | None = None) -> dict:
    p = policy()
    if client not in CLIENTS or band not in BANDS:
        raise SelectionError(f"unknown client/band {client}/{band}")
    contract = p["clients"][client]
    if not isinstance(entry, dict) or set(entry) - set(contract["fields"]):
        raise SelectionError(f"{client}/{band}: invalid or missing selection")
    for key in contract["required"]:
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise SelectionError(f"{client}/{band}: missing required {key}")
    if any(str(entry.get(k, "")).casefold() in {s.casefold() for s in p["forbid"]} for k in ("model", "label")):
        raise SelectionError(f"{client}/{band}: forbidden model {entry.get('model')!r}")
    if client == "cursor":
        if catalogue is None:
            try:
                result = subprocess.run(["cursor-agent", "models"], capture_output=True, text=True, timeout=10, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise SelectionError(f"{client}/{band}: capability_unavailable: cursor-agent models: {exc}") from exc
            catalogue = {line.split(" - ", 1)[0].strip(): True for line in result.stdout.splitlines() if " - " in line}
        if entry["model"] not in catalogue:
            raise SelectionError(f"{client}/{band}: model not advertised by native catalogue: {entry['model']}")
    if client == "grok":
        if catalogue is None:
            path = Path.home() / ".grok/models_cache.json"
            try:
                catalogue = json.loads(path.read_text())["models"]
                config_path = Path.home() / ".grok/config.toml"
                if config_path.exists():
                    catalogue = {**catalogue, **tomllib.loads(config_path.read_text()).get("model", {})}
            except (OSError, ValueError, KeyError) as exc:
                raise SelectionError(f"{client}/{band}: capability_unavailable: native catalogue {path}: {exc}") from exc
        if entry["model"] not in catalogue:
            raise SelectionError(f"{client}/{band}: model not advertised by native catalogue: {entry['model']}")
    if client == "codex":
        if catalogue is None:
            path = Path.home() / ".codex/models_cache.json"
            try:
                catalogue = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                raise SelectionError(f"{client}/{band}: capability_unavailable: native catalogue {path}: {exc}") from exc
        models = {x.get("slug"): x for x in catalogue.get("models", [])}
        model = models.get(entry["model"])
        if model is None:
            raise SelectionError(f"{client}/{band}: model not advertised by native catalogue: {entry['model']}")
        efforts = {x["effort"] for x in model.get("supported_reasoning_levels", [])}
        if entry["effort"] not in efforts:
            raise SelectionError(f"{client}/{band}: unsupported effort {entry['effort']!r} for {entry['model']}")
    # dsh effort compatibility is checked against llm.resolveModelInfo by the
    # active adapter before birth, rather than a perpetual effort allowlist.
    return copy.deepcopy(entry)


def native_arguments(client: str, entry: dict) -> dict:
    if client in ("cursor", "grok"):
        return {"model": entry["model"]}
    if client == "codex":
        return {"model": entry["model"], "reasoning_effort": entry["effort"]}
    if client == "dsh":
        return {"provider": entry["provider"], "model": entry["model"], **({"reasoning_effort": entry["effort"]} if "effort" in entry else {})}
    return {"model": {"providerID": entry["provider"], "modelID": entry["model"]}, **({"variant": entry["variant"]} if "variant" in entry else {})}


def resolve(client: str, band: str, *, role: str | None = None, catalogue: Mapping | None = None) -> dict:
    path = selection_path()
    if role is not None and role_band(role) != band:
        raise SelectionError(f"{path} {client}/{band}: role {role} requires {role_band(role)}")
    try:
        document, body = read_yaml(path)
        validate_document(document)
        entry = validate_entry(client, band, document["clients"].get(client, {}).get(band), catalogue=catalogue)
    except SelectionError as exc:
        raise SelectionError(f"{path} {client}/{band}: {exc}") from exc
    p = policy()
    arguments = native_arguments(client, entry)
    capture = {
        "version": 1, "attempt_id": str(uuid.uuid4()), "client": client, "band": band,
        "role": role, "selection": entry, "arguments": arguments,
        "source_path": str(path), "source_sha256": hashlib.sha256(body).hexdigest(),
        "policy_version": p["version"], "policy_sha256": digest(p),
        "capability_version": p["clients"][client]["contract"],
        "effective_sha256": digest({"client": client, "band": band, "arguments": arguments}),
    }
    capture["capture_sha256"] = digest(capture)
    return capture


def validate_capture(capture: Any, *, client: str | None = None, band: str | None = None, role: str | None = None) -> dict:
    if not isinstance(capture, dict) or capture.get("version") != 1:
        raise SelectionError("birth capture missing or invalid; cannot infer from current configuration")
    body = {k: v for k, v in capture.items() if k != "capture_sha256"}
    if digest(body) != capture.get("capture_sha256"):
        raise SelectionError("birth capture digest mismatch")
    c, b = capture.get("client"), capture.get("band")
    if c not in CLIENTS or b not in BANDS or (client and client != c) or (band and band != b):
        raise SelectionError("birth capture client/band mismatch")
    if role and role_band(role) != b:
        raise SelectionError(f"birth capture role {role} requires {role_band(role)}")
    if role and capture.get("role") != role:
        raise SelectionError(f"birth capture belongs to {capture.get('role')!r}, not {role!r}")
    # Live selections are never reread here. New policy prohibitions remain enforced.
    entry = capture.get("selection", {})
    p = policy()
    if not isinstance(entry, dict) or set(entry) - set(p["clients"][c]["fields"]) or any(not isinstance(entry.get(k), str) or not entry[k].strip() for k in p["clients"][c]["required"]):
        raise SelectionError("birth capture selection fields missing/invalid")
    if any(str(entry.get(k, "")).casefold() in {s.casefold() for s in p["forbid"]} for k in ("model", "label")):
        raise SelectionError("birth capture model now forbidden by policy")
    if native_arguments(c, entry) != capture.get("arguments") or digest({"client": c, "band": b, "arguments": capture["arguments"]}) != capture.get("effective_sha256"):
        raise SelectionError("birth capture effective arguments mismatch")
    return copy.deepcopy(capture)


def compare_wave(first: dict, next_capture: dict) -> None:
    validate_capture(first)
    validate_capture(next_capture)
    if first["effective_sha256"] != next_capture["effective_sha256"]:
        raise SelectionError("selection_changed: client/band effective selection changed between births; cancel partial wave")


def save_capture(path: Path, capture: dict) -> None:
    validate_capture(capture)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(capture, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_capture(path: str | Path) -> dict:
    try:
        return validate_capture(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as exc:
        raise SelectionError(f"cannot read birth capture {path}: {exc}") from exc


def migration_plan(legacy: Path, routes: dict) -> dict:
    """Explicit inputs only. Existing machine bytes always prevail."""
    target = selection_path()
    if target.exists() or target.is_symlink():
        return {"target": str(target), "action": "preserve_existing", "existing_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "write_allowed": False}
    data, body = read_yaml(legacy)
    clients: dict = {"cursor": {}, "grok": {}, "codex": {}}
    for band in BANDS:
        old = data.get(band, {})
        clients["cursor"][band] = {"label": old.get("label"), "model": old.get("slug")}
        grok = old.get("grok", {})
        if grok.get("effort") not in (None, "high"):
            raise SelectionError(f"legacy Grok {band} effort cannot be represented by tested model-only spawn contract; reconcile explicitly")
        clients["grok"][band] = {"label": grok.get("label"), "model": grok.get("slug")}
        clients["codex"][band] = {"label": "GPT-6 Astra" if band == "juizo" else "GPT-6.1 Sol", "model": "gpt-6-astra" if band == "juizo" else "gpt-6.1-sol", "effort": "medium" if band == "juizo" else "high"}
    unknown = []
    for client in ("opencode", "dsh"):
        if client in routes:
            clients[client] = copy.deepcopy(routes[client])
        else:
            unknown.append(client)
    document = {"version": 1, "clients": clients}
    validate_document(document)
    for client, bands in clients.items():
        for band in BANDS:
            validate_entry(client, band, bands.get(band))
    plan = {"target": str(target), "account": str(Path.home()), "action": "create_only", "legacy_source": str(legacy), "legacy_sha256": hashlib.sha256(body).hexdigest(), "document": document, "unmigrated_clients": unknown, "write_allowed": not unknown, "grok_effort": "legacy_high_no_separate_spawn_effort_demonstrated"}
    plan["plan_sha256"] = digest(plan)
    return plan


def apply_migration(plan: dict) -> None:
    if plan.get("plan_sha256") != digest({k:v for k,v in plan.items() if k != "plan_sha256"}) or not plan.get("write_allowed") or plan.get("action") != "create_only":
        raise SelectionError("migration plan invalid/incomplete or existing selection must be preserved")
    path = selection_path()
    if plan.get("target") != str(path) or plan.get("account") != str(Path.home()):
        raise SelectionError("migration plan belongs to a different host account")
    legacy = Path(plan["legacy_source"])
    if hashlib.sha256(legacy.read_bytes()).hexdigest() != plan["legacy_sha256"]:
        raise SelectionError("migration source changed; prepare a new plan")
    validate_document(plan["document"])
    for client, bands in plan["document"]["clients"].items():
        for band in BANDS:
            validate_entry(client, band, bands.get(band))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".model-selection-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            yaml.safe_dump(plan["document"], stream, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication without replacing a selection created since planning.
        os.link(temp, path)
    except FileExistsError as exc:
        raise SelectionError(f"existing selection preserved: {path}; prepare a new plan") from exc
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--client", required=True, choices=CLIENTS)
    r.add_argument("--band", required=True, choices=BANDS)
    r.add_argument("--role", required=True)
    r.add_argument("--capture", type=Path)
    r.add_argument("--wave-capture", type=Path)
    prep = sub.add_parser("prepare")
    prep.add_argument("--client", required=True, choices=CLIENTS)
    continuation = sub.add_parser("check-request")
    continuation.add_argument("--client", required=True, choices=CLIENTS)
    spawn = sub.add_parser("validate-spawn")
    spawn.add_argument("--client", required=True, choices=CLIENTS)
    sub.add_parser("validate")
    m = sub.add_parser("migration-plan")
    m.add_argument("--legacy", required=True, type=Path)
    m.add_argument("--routes", type=Path, help="explicit non-secret effective opencode/dsh selections")
    a = sub.add_parser("migrate")
    a.add_argument("--plan", required=True, type=Path)
    v = sub.add_parser("verify-capture")
    v.add_argument("--capture", required=True, type=Path)
    v.add_argument("--client", choices=CLIENTS)
    v.add_argument("--role", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-spawn":
            out = validate_spawn(args.client, json.load(sys.stdin))
        elif args.command == "check-request":
            inp = json.load(sys.stdin)
            birth = validate_capture(inp["capture"], client=args.client, role=inp["role"])
            out = {"capture": birth}
        elif args.command == "prepare":
            arguments = json.load(sys.stdin)
            role = request_role(arguments)
            out = resolve(args.client, role_band(role), role=role)
        elif args.command == "resolve":
            out = resolve(args.client, args.band, role=args.role)
            if args.wave_capture:
                compare_wave(load_capture(args.wave_capture), out)
            if args.capture:
                save_capture(args.capture, out)
        elif args.command == "validate":
            validate_document(read_yaml(selection_path())[0])
            out = [resolve(c, b) for c in CLIENTS for b in BANDS]
        elif args.command == "migration-plan":
            out = migration_plan(args.legacy, read_yaml(args.routes)[0] if args.routes else {})
        elif args.command == "migrate":
            apply_migration(json.loads(args.plan.read_text()))
            out = {"created": str(selection_path())}
        else:
            out = validate_capture(load_capture(args.capture), client=args.client, role=args.role)
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        return 0
    except (SelectionError, OSError, ValueError) as exc:
        print(f"model selection error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
