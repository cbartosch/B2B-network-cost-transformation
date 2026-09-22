"""No screen may hold its own list of the site types.

The simulation page held `("BRANCH", "LARGE_OFFICE", "WAREHOUSE", "DC",
"STORE")` as a literal. Every type added since was accepted by the API and
rejected by the page: CAMPUS from 4.219.0, five more at sim-2.0.0, three more
at sim-2.3.0.

An analyst typing SERVICE_POINT was told it "is not one of BRANCH,
LARGE_OFFICE, WAREHOUSE, DC, STORE" by a build that had fourteen - and the
row it rejected was the largest in the estate.

The same shape as the intake page's industry list, whose own comment already
said a hardcoded list goes stale the moment the table gains a row. It said so
about a different list.
"""
import ast
import re
from pathlib import Path


def _seeded_archetypes():
    from app.seed import ARCHETYPES
    return {row[0] for row in ARCHETYPES}


def _pages():
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "analyst_ui" / "streamlit_app").rglob("*.py"))


def test_no_page_hardcodes_a_list_of_site_types():
    """A literal naming three or more archetypes is a copy of the table."""
    seeded = _seeded_archetypes()
    offenders = []
    for path in _pages():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                continue
            names = {e.value for e in node.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            hits = names & seeded
            # the fallback for an unreachable API is allowed, and is the only
            # place a literal may name them
            if len(hits) < 3 or "BRANCH" not in hits:
                continue
            # A literal reached only when the API did not answer is allowed:
            # when it applies nothing can be run anyway, so a stale list
            # there cannot mislead anyone into a wrong estimate.
            #
            # Detected on the enclosing statement rather than the literal's
            # own line - a wrapped `or [...]` puts the fallback marker on the
            # line above, which the first version of this check missed.
            lines = path.read_text().splitlines()
            window = " ".join(
                lines[max(0, node.lineno - 3):node.lineno + 1])
            if 'get("archetypes")' in window:
                continue
            offenders.append(f"{path.name}:{node.lineno} {sorted(hits)}")
    assert not offenders, offenders


def test_the_simulation_page_reads_the_published_set():
    page = next(p for p in _pages() if p.name.startswith("5_Simulation"))
    source = page.read_text()
    assert 'get("archetypes")' in source, (
        "the page must take the site types from the API")


def test_the_api_publishes_them_from_the_table():
    """From archetype_prior - the same source the named-location route
    validates against, so the two cannot disagree."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert 'resolved["archetypes"] = sorted(' in api
    assert "select(db.archetype_prior)" in api


def test_the_fallback_is_only_for_an_unreachable_api():
    """A stale fallback cannot mislead: when it applies, nothing can be run
    anyway."""
    page = next(p for p in _pages() if p.name.startswith("5_Simulation"))
    source = page.read_text()
    match = re.search(r"ARCHETYPES = tuple\(\(_fp or \{\}\)\.get\(\"archetypes\"\)",
                      source)
    assert match, "the published set must be tried first"
