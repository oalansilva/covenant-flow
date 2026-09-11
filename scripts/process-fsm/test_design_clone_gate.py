from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from design_clone_gate import (
    BLOCKED,
    CATALOG_REL,
    PASS,
    canonical_proto_html,
    classify,
    clone_gate_ok,
    copied_utf8_sum,
    default_catalog_path,
    evaluate_clone_gate,
    is_new_exempt,
    load_catalog_file,
    load_head_catalog,
    parse_live_route,
    requires_existing_clone,
    routes_from_catalog,
)

ROOT = Path(__file__).resolve().parent
R1_PATH = ROOT / "fixtures" / "792-r1-gallery.html"
R1_SHA256 = "068581d6b9b2171b7534cb1250575bf4a61ea9b0e428047ffff387e98341efd7"
PANEL_INDEX = ROOT / "fixtures" / "790-panel-index.html"
SIBLING_CLONE = ROOT / "fixtures" / "790-sibling-landing-clone.html"
V4_CLONE = ROOT / "fixtures" / "v4-landing-clone.html"
AUTH_ROUTES = {"/monitor", "/favorites", "/combo/discovery", "/combo/select"}
LANDING_TEXTS = (
    "Comprar ou vender cripto? O Cripto Farol responde.",
    "FAQ",
    "Quero meus 6 meses grátis",
)

SEEDED = default_catalog_path().read_text(encoding="utf-8")

MONITOR_HTML = """<!doctype html>
<!-- COPIED:start -->
<table class="signals">
  <th>Status</th><th>Preço</th><th>Distância</th><th>7d</th>
  <th>Risco até stop</th><th>Tags</th><th>Operar</th><th>Par / Estratégia</th>
</table>
<!-- COPIED:end -->
"""

LANDMARKS_NO_COPIED = """<!doctype html>
<table class="signals">
  <th>Status</th><th>Preço</th><th>Distância</th><th>7d</th>
  <th>Risco até stop</th><th>Tags</th><th>Operar</th><th>Par / Estratégia</th>
</table>
"""

COPIED_ZERO = """<!doctype html>
<table class="signals">
  <th>Status</th><th>Preço</th><th>Distância</th><th>7d</th>
  <th>Risco até stop</th><th>Tags</th><th>Operar</th><th>Par / Estratégia</th>
</table>
<!--COPIED:startCOPIED:end-->
"""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def _repo_with_catalog(tmp_path: Path, catalog_text: str) -> Path:
    repo = tmp_path / "repo"
    catalog = repo / CATALOG_REL
    catalog.parent.mkdir(parents=True)
    catalog.write_text(catalog_text, encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", CATALOG_REL)
    _git(
        repo,
        "-c",
        "user.email=t@t.test",
        "-c",
        "user.name=t",
        "commit",
        "-m",
        "seed catalog",
    )
    return repo


def _change(tmp_path: Path, design: str) -> Path:
    change = tmp_path / "change"
    change.mkdir()
    (change / "proposal.md").write_text("# p\n", encoding="utf-8")
    (change / "design.md").write_text(design, encoding="utf-8")
    (change / "tasks.md").write_text("# t\n", encoding="utf-8")
    specs = change / "specs" / "x"
    specs.mkdir(parents=True)
    (specs / "spec.md").write_text("# s\n", encoding="utf-8")
    return change


def _proto(tmp_path: Path, html: str, name: str = "index.html") -> Path:
    proto = tmp_path / "proto"
    proto.mkdir()
    (proto / name).write_text(html, encoding="utf-8")
    return proto


def test_seeded_catalog_has_four_auth_routes_and_public_landing():
    data = load_catalog_file(default_catalog_path())
    assert data.get("version") == 1
    routes = routes_from_catalog(data)
    assert set(routes) == AUTH_ROUTES | {"landing"}
    monitor = routes["/monitor"]
    assert monitor.get("kind") == "authenticated"
    assert monitor.get("kind") != "public"
    assert "table.signals" in monitor["selectors"]
    for text in ("Status", "Preço", "Risco até stop", "Operar"):
        assert text in monitor["texts"]
    landing = routes["landing"]
    assert landing["kind"] == "public"
    assert landing["live_url"] == "https://criptofarol.com.br/"
    assert landing["source"] == "frontend/public/prototypes/cripto-farol-landing-v4/index.html"
    assert landing["selectors"] == [".faq-section", ".button-primary"]
    for text in LANDING_TEXTS:
        assert text in landing["texts"]


def test_existing_landmarks_and_copied_pass(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\nlive_route: /monitor\nsurface: existing\n")
    proto = _proto(tmp_path, MONITOR_HTML)
    assert clone_gate_ok(change, proto, repo) is True


def test_copied_absent_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\nlive_route: /monitor\n")
    proto = _proto(tmp_path, LANDMARKS_NO_COPIED)
    assert clone_gate_ok(change, proto, repo) is False
    assert copied_utf8_sum(LANDMARKS_NO_COPIED) == 0


def test_copied_zero_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\nlive_route: /monitor\n")
    proto = _proto(tmp_path, COPIED_ZERO)
    assert copied_utf8_sum(COPIED_ZERO) == 0
    assert clone_gate_ok(change, proto, repo) is False


def test_missing_head_key_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\nlive_route: /profile\n")
    proto = _proto(tmp_path, MONITOR_HTML)
    assert clone_gate_ok(change, proto, repo) is False


def test_worktree_only_key_does_not_pass(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    catalog = repo / CATALOG_REL
    catalog.write_text(
        SEEDED
        + "\n/profile:\n  selectors: []\n  texts: [\"Perfil\"]\n",
        encoding="utf-8",
    )
    assert "/profile" not in routes_from_catalog(load_head_catalog(repo))
    change = _change(tmp_path, "UI impact: affected\nlive_route: /profile\n")
    proto = _proto(tmp_path, "<!-- COPIED:start -->Perfil<!-- COPIED:end -->")
    assert clone_gate_ok(change, proto, repo) is False


def test_affected_proto_without_fields_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\n")
    proto = _proto(tmp_path, MONITOR_HTML)
    assert clone_gate_ok(change, proto, repo) is False


def test_surface_new_exempts_catalog_and_copied(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\nsurface: new\n")
    proto = _proto(tmp_path, "<p>no landmarks</p>")
    assert clone_gate_ok(change, proto, repo) is True


def test_live_route_na_justified_exempts(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(
        tmp_path,
        "UI impact: affected\nlive_route: N/A harness-only; no product route\n",
    )
    proto = _proto(tmp_path, "<p>no landmarks</p>")
    assert clone_gate_ok(change, proto, repo) is True


def test_r1_gallery_sha256_blocked_against_monitor():
    raw = R1_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == R1_SHA256
    assert len(raw) == 21275
    html = raw.decode("utf-8")
    assert "table.signals" not in html
    assert classify(html, "/monitor") == BLOCKED


def test_evaluate_injected_catalog_does_not_replace_head_lookup(tmp_path: Path):
    design = "UI impact: affected\nlive_route: /monitor\n"
    proto = _proto(tmp_path, MONITOR_HTML)
    repo = _repo_with_catalog(tmp_path, "version: 1\n")
    assert evaluate_clone_gate(design, proto, repo) is False


def _panel_plus_sibling(tmp_path: Path) -> Path:
    proto = tmp_path / "proto"
    proto.mkdir()
    (proto / "index.html").write_text(PANEL_INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    (proto / "landing.html").write_text(SIBLING_CLONE.read_text(encoding="utf-8"), encoding="utf-8")
    return proto


def test_parse_live_route_accepts_landing_and_na():
    assert parse_live_route("live_route: landing\n") == ("landing", "")
    value, justification = parse_live_route("live_route: N/A harness-only; no product route\n")
    assert value == "N/A"
    assert "harness-only" in justification


def test_requires_existing_clone_and_new_exempt_treat_landing():
    assert requires_existing_clone("landing", "new") is True
    assert requires_existing_clone("/monitor", None) is True
    assert requires_existing_clone("N/A", "new") is False
    assert is_new_exempt("landing", "new", "x") is False
    assert is_new_exempt("N/A", "new", "harness") is True


def test_canonical_proto_html_index_only_not_concatenate(tmp_path: Path):
    proto = _panel_plus_sibling(tmp_path)
    html = canonical_proto_html(proto)
    assert "Copy alinhada ao Spot" in html
    assert "button-primary" not in html
    assert copied_utf8_sum(html) == 0
    combined = "".join(path.read_text(encoding="utf-8") for path in sorted(proto.glob("*.html")))
    assert classify(combined, "landing") == PASS
    assert classify(html, "landing") == BLOCKED


def test_canonical_proto_html_single_file_fallback(tmp_path: Path):
    proto = tmp_path / "proto"
    proto.mkdir()
    (proto / "only.html").write_text(V4_CLONE.read_text(encoding="utf-8"), encoding="utf-8")
    assert "index.html" not in {path.name for path in proto.glob("*.html")}
    assert classify(canonical_proto_html(proto), "landing") == PASS
    (proto / "extra.html").write_text("<p>other</p>", encoding="utf-8")
    assert canonical_proto_html(proto) == ""


def test_panel_index_plus_sibling_clone_fails_against_landing(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: affected\nlive_route: landing\nsurface: existing\n")
    proto = _panel_plus_sibling(tmp_path)
    panel = PANEL_INDEX.read_text(encoding="utf-8")
    assert "Copy alinhada ao Spot" in panel
    assert panel.count("<h2") >= 6
    assert "DEPOIS" in panel
    assert "./landing.html" in panel
    assert "COPIED" not in panel
    assert clone_gate_ok(change, proto, repo) is False
    assert classify(panel, "landing") == BLOCKED


def test_v4_clone_as_index_passes_landing_not_via_790_path(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    html = V4_CLONE.read_text(encoding="utf-8")
    assert "790" not in V4_CLONE.name
    proto = _proto(tmp_path, html)
    assert "790" not in str(proto.resolve())
    change = _change(tmp_path, "UI impact: affected\nlive_route: landing\n")
    assert clone_gate_ok(change, proto, repo) is True
    assert classify(html, "landing") == PASS
    assert copied_utf8_sum(html) > 0


def test_ui_none_harness_na_new_without_proto_passes(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(
        tmp_path,
        "UI impact: none\nlive_route: N/A harness-only; no product route\nsurface: new\n",
    )
    assert clone_gate_ok(change, None, repo) is True


def test_existing_or_landing_without_proto_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    existing = _change(tmp_path, "UI impact: affected\nsurface: existing\n")
    assert clone_gate_ok(existing, None, repo) is False
    (existing / "design.md").write_text("UI impact: none\nlive_route: landing\n", encoding="utf-8")
    assert clone_gate_ok(existing, None, repo) is False


def test_ui_none_plus_existing_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, SEEDED)
    change = _change(tmp_path, "UI impact: none\nsurface: existing\n")
    proto = _proto(tmp_path, "<p>not a clone</p>")
    assert clone_gate_ok(change, proto, repo) is False
    (change / "design.md").write_text(
        "UI impact: none\nlive_route: landing\nsurface: new\n",
        encoding="utf-8",
    )
    assert clone_gate_ok(change, None, repo) is False


def test_landing_declared_without_head_key_refuses(tmp_path: Path):
    repo = _repo_with_catalog(tmp_path, "version: 1\n")
    change = _change(tmp_path, "UI impact: affected\nlive_route: landing\n")
    proto = _proto(tmp_path, V4_CLONE.read_text(encoding="utf-8"))
    catalog = repo / CATALOG_REL
    catalog.write_text(SEEDED, encoding="utf-8")
    assert "landing" not in routes_from_catalog(load_head_catalog(repo))
    assert clone_gate_ok(change, proto, repo) is False
