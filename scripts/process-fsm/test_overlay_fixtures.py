"""Shared overlay fixtures for process-fsm tests. Not shipped as consumer overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from overlay import column_names, empty_template

# Fixture ids for join tests (consumer overlay, not packaged Python).
FIELD_ID = "PVTSSF_lAHOAAHtBM4BV8b2zhRUdMM"
COLUMN_IDS = {
    "Em Refinamento": "fed46e78",
    "Todo": "4c26ac72",
    "Design": "bd47fbe8",
    "Aprovação de Design": "b45bf4aa",
    "Pronto para Dev": "0257f58c",
    "Em desenvolvimento": "fe1ad960",
    "Code Review": "b1858de0",
    "QA": "9220bf8c",
    "Done": "e02597eb",
    "Homologado": "dfcb47b5",
    "Pronto": "8ca47888",
    "Cancelado": "ce5cd459",
}


def filled_overlay_dict(**overrides: Any) -> dict[str, Any]:
    data = empty_template()
    data["board"] = {
        "owner": "oalansilva",
        "number": 1,
        "status_field_id": FIELD_ID,
        "project_id": "PVT_kwHOAAHtBM4BV8b2",
        "status_options": dict(COLUMN_IDS),
    }
    data["repo"] = "oalansilva/crypto"
    data["product_globs"] = ["backend/**", "frontend/src/**"]
    data["design_globs"] = ["openspec/changes/**", "frontend/public/prototypes/**"]
    data["integration_branch"] = "develop"
    data["production_branch"] = "main"
    data["pin"] = "v1.0.0"
    data["canonical_paths"] = {"dev": "/tmp/canonical-dev", "prod": "/tmp/canonical-prod"}
    data["forbidden_worktrees"] = ["/tmp/forbidden"]
    data["overlay_doc"] = "docs/overlay.md"
    data["clients"] = {
        "cursor": {"auto": True},
        "grok": {"auto": False},
        "opencode": {"auto": False},
    }
    data["impeccable"] = {"critique_dir": ".impeccable/critique", "design_md": "DESIGN.md"}
    data["runtime"] = {"playwright": "frontend/tests"}
    data["environments"] = {
        "dev": {
            "source": "/tmp/canonical-dev",
            "url": "https://dev.example.test",
            "db": "app_dev",
            "services": ["dev-backend.service"],
        },
        "prod": {
            "source": "/tmp/canonical-prod",
            "url": "https://example.test",
            "db": "app",
            "services": ["prod-backend.service"],
        },
    }
    data["release"] = {
        "restart": "./restart",
        "migrate": "alembic upgrade head",
        "build": "npm run build",
        "health_url": "https://example.test/api/health",
    }
    data.update(overrides)
    assert list((data["board"]["status_options"]).keys()) == column_names()
    return data


def write_overlay(repo: Path, **overrides: Any) -> Path:
    dest = repo / ".covenant-flow" / "overlay.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        yaml.safe_dump(
            filled_overlay_dict(**overrides),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return dest
