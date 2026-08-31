"""Static checks on the Streamlit pages.

py_compile catches a syntax error and nothing else, so a page that references
a name it never imported compiles cleanly and raises NameError in the browser -
in front of the analyst, on whichever branch happens to run. That is how
`pd.DataFrame` reached page 2 without pandas being imported: the line sat
inside a conditional that only fires after a corroboration returns observed
candidates, so it was never executed until it was.

These run over the pages as source. They cannot prove a page works, but they
close the two failure modes that are mechanically detectable and have both
already happened.
"""
import ast
import builtins
import pathlib

import pytest

PAGES = sorted((pathlib.Path(__file__).resolve().parents[1]
                / "analyst_ui" / "streamlit_app").rglob("*.py"))


def _bound_and_used(tree):
    bound, used = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name):
            (bound if isinstance(node.ctx, (ast.Store, ast.Del))
             else used).add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound |= set(node.names)
    return bound, used


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_a_page_imports_every_name_it_uses(page):
    """The defect this catches reaches the analyst, not the build: a name used
    on a rarely-taken branch raises NameError mid-render."""
    bound, used = _bound_and_used(ast.parse(page.read_text()))
    missing = sorted(used - bound - set(dir(builtins)))
    assert not missing, (
        f"{page.name} uses {missing} without importing or defining them")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_a_page_does_not_use_browser_storage(page):
    """Not supported in this environment, and it fails silently rather than
    loudly - which is worse than not working."""
    text = page.read_text()
    for banned in ("localStorage", "sessionStorage"):
        assert banned not in text, f"{page.name} references {banned}"


def test_every_page_compiles():
    import py_compile
    for page in PAGES:
        py_compile.compile(str(page), doraise=True)


def test_the_simulation_footprint_opens_runnable():
    """Zero was the honest default and made the page unusable: the site-count
    guard refuses an all-zero footprint, so nothing could be run without
    typing first. One site per country is small enough that nobody mistakes it
    for a finding - the actual concern - while leaving the page reachable."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert '"archetype": "BRANCH", "sites": 1' in text, (
        "the in-scope-country default must be at least one site")
    assert '"sites": 0' not in text, (
        "a zero default puts the page behind a guard it cannot pass")


# --------------------------------------------- simulation footprint payload
def _clean():
    """The page is a Streamlit script, so the helper is lifted out by source
    rather than imported - importing it would execute the page."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    src = page.read_text()
    ns = {}
    exec(src[src.index("ARCHETYPES = ("):
             src.index('if st.button("Run simulation"')], ns)
    return ns["_clean_footprint"]


@pytest.mark.parametrize("rows,expected_rows,expect_problem", [
    ([{"country": "DE", "archetype": "BRANCH", "sites": 1}], 1, False),
    # The dynamic editor always shows a trailing blank row. Clicking into it
    # used to put {"country": null, ...} in the payload, which failed schema
    # validation with a message about string types that told the analyst
    # nothing about the row they had touched.
    ([{"country": "DE", "archetype": "BRANCH", "sites": 1},
      {"country": None, "archetype": None, "sites": None}], 1, False),
    # pandas turns an empty cell into NaN, and str(nan) is the truthy string
    # "nan" - so a truthiness check keeps it and the row arrives as country
    # "NAN". Checked explicitly instead.
    ([{"country": float("nan"), "archetype": float("nan"),
       "sites": float("nan")}], 0, False),
    ([{"country": " de ", "archetype": " branch ", "sites": 5}], 1, False),
    ([{"country": "DE", "archetype": "BRANCHES", "sites": 5}], 0, True),
    ([{"country": "GER", "archetype": "BRANCH", "sites": 5}], 0, True),
    ([{"country": "DE", "archetype": "DC", "sites": -1}], 0, True),
])
def test_the_footprint_payload_survives_what_the_editor_produces(
        rows, expected_rows, expect_problem):
    pd = pytest.importorskip("pandas")
    cleaned, problems = _clean()(pd.DataFrame(rows))
    assert len(cleaned) == expected_rows
    assert bool(problems) is expect_problem


def test_a_bad_archetype_is_reported_not_corrected():
    """A misspelled archetype is a typo the analyst can fix; a coerced one is
    a site type they did not choose, priced at a bandwidth they did not pick."""
    pd = pytest.importorskip("pandas")
    _, problems = _clean()(pd.DataFrame(
        [{"country": "DE", "archetype": "BRANCHES", "sites": 5}]))
    assert problems and "BRANCH, LARGE_OFFICE" in problems[0]


def test_a_failed_footprint_load_is_not_silent():
    """A promoted footprint that fails to load looked identical to one that was
    never promoted: the editor fell back to placeholders with no explanation,
    so researched counts appeared to vanish and the run proceeded on defaults
    that looked like findings."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert "_ev_failed" in text
    assert "Could not load the promoted site list" in text
    assert "fallen back to placeholder values" in text


def test_the_empty_footprint_message_names_the_case():
    """A promoted footprint belongs to one case. Switching cases empties the
    list, and a message that does not say which case invites the conclusion
    that the promotion was lost."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    assert "belongs to one" in page.read_text()


def test_the_footprint_editor_reopens_on_what_was_last_run():
    """Reported as "it collapses to default". The editor was transient: an
    analyst typed counts, ran the simulation, and the rerun that followed
    rebuilt the table from the placeholder - so the numbers they had just
    entered disappeared, and the page looked as though it had discarded them.

    Precedence is promoted evidence, then the last run, then a placeholder:
    what you last ran is a better starting point than a guess and a worse one
    than a researched count."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert "/simulations\")" in text, "the page must read the run history"
    assert "elif _last:" in text
    assert text.index("if _rows:") < text.index("elif _last:"), (
        "promoted evidence must outrank the last typed footprint")


def test_a_typed_footprint_can_be_saved_without_running_it():
    """Reported as "still showing 1 site". The editor persisted only what was
    *run*: typing a site list and not running it lost the list, and running a
    placeholder made the placeholder the thing that stuck. Saving is now its
    own act."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert 'Save footprint' in text
    assert '"analyst_footprint"' in text
    assert text.index("elif _saved:") < text.index("elif _last:"), (
        "a deliberately saved footprint must outrank whatever happened to be "
        "run last")
    assert text.index("if _rows:") < text.index("elif _saved:"), (
        "promoted evidence still outranks anything typed")
