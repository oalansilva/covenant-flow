"""Captured execution selection checks shared by release entry points."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ModelCheck:
    ok: bool
    divergence: bool
    auto_claimed: bool
    routed: bool
    message: str
    map_slug: str = ""
    runtime_slug: str = ""


def load_execucao_pair(root: str | Path, client: str, capture: dict | None = None) -> dict[str, str]:
    from model_selection import resolve, validate_capture
    birth = validate_capture(capture, client=client, band="execucao") if capture is not None else resolve(client, "execucao", role="fecho-lote")
    entry = birth["selection"]
    return {
        "key": f"machine.{client}.execucao",
        "label": str(entry.get("label") or ""),
        "slug": str(entry.get("model") or ""),
        "effort": str(entry.get("effort") or ""),
        "provider": str(entry.get("provider") or ""),
        "variant": str(entry.get("variant") or ""),
    }


def check_runtime_model(
    *,
    root: str | Path,
    client: str,
    runtime_slug: str,
    runtime_effort: str = "",
    runtime_provider: str = "",
    runtime_variant: str = "",
    client_can_route: bool = False,
    auto_claimed: bool = False,
    capture: dict | None = None,
) -> ModelCheck:
    from model_selection import SelectionError
    try:
        if capture is None:
            raise SelectionError("release operation birth capture required; do not compare a living parent to an edited file")
        pair = load_execucao_pair(root, client, capture)
    except SelectionError as exc:
        return ModelCheck(ok=False, divergence=True, auto_claimed=auto_claimed, routed=False, message=str(exc), map_slug="unavailable", runtime_slug=runtime_slug)
    if auto_claimed:
        return ModelCheck(
            ok=False,
            divergence=True,
            auto_claimed=True,
            routed=False,
            message="MUST NOT claim Auto mode; selection is not edited; stop T16 on this runtime",
            map_slug=pair["slug"],
            runtime_slug=runtime_slug,
        )
    observed = {"slug": runtime_slug, "effort": runtime_effort,
                "provider": runtime_provider, "variant": runtime_variant}
    mismatches = [
        field for field in observed
        if pair[field] and (
            observed[field] in (None, "", "unavailable", "not_applicable")
            or observed[field] != pair[field]
        )
    ]
    if not mismatches:
        return ModelCheck(
            ok=True,
            divergence=False,
            auto_claimed=False,
            routed=False,
            message=f"{pair['key']} matches runtime {runtime_slug}",
            map_slug=pair["slug"],
            runtime_slug=runtime_slug,
        )
    if client_can_route:
        return ModelCheck(
            ok=False,
            divergence=True,
            auto_claimed=False,
            routed=True,
            message=(
                f"runtime {runtime_slug} diverges from {pair['key']}={pair['slug']} "
                f"on {', '.join(mismatches)}; "
                "route the preserved manifesto to the execucao session; do not edit the selection"
            ),
            map_slug=pair["slug"],
            runtime_slug=runtime_slug,
        )
    return ModelCheck(
        ok=False,
        divergence=True,
        auto_claimed=False,
        routed=False,
        message=(
            f"runtime {runtime_slug} diverges from {pair['key']}={pair['slug']} "
            f"on {', '.join(mismatches)}; "
            "client cannot route sessions; declare the handoff; do not claim routing occurred; "
            "do not edit the selection; do not continue T16"
        ),
        map_slug=pair["slug"],
        runtime_slug=runtime_slug,
    )

