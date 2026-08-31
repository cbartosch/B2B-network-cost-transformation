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


def test_the_simulation_page_reads_the_known_facts_register():
    """The gap behind "I entered 341 and the code is ignoring it".

    A known fact of class "Location footprint" binds the sites driver at
    estimate time on page 6, and this page never read the register at all - so
    a registered count sat there while the editor showed a placeholder and the
    analyst was told to type it again."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert "/known-facts" in text, "the page must read the register"
    assert '"Location footprint"' in text
    assert "Use this count" in text


def test_the_register_count_does_not_invent_a_site_type():
    """The register records how many sites there are, not what kind. A bank
    branch is a STORE under the archetype definitions and is priced at a
    different bandwidth and product from BRANCH, so guessing would silently
    change the estimate."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert "asked rather than guessed" in text
    assert '"Site type"' in text


def test_decimal_fields_are_coerced_before_formatting():
    """value_base arrives as a JSON string, so formatting it with :g raises
    rather than rendering - a NameError-class defect that only fires on the
    branch where a fact actually exists."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    assert "def _num(value):" in page.read_text()


def test_the_known_fact_subject_is_prefilled_from_the_case():
    """A blank subject cost a malformed fact - "(None sites)", unresolvable
    forever - and it fragments the register: corroboration and the public
    prefill both match on (fact_class, subject), so "HVB" and "UniCredit Bank
    GmbH" typed on different days are two facts about the same thing that
    never meet."""
    page = next(p for p in PAGES if p.name.startswith("2_"))
    text = page.read_text()
    assert 'value=_entity' in text, "the subject must default to the case entity"
    assert "subject_entity_legal_name" in text
    assert "Also on this case" in text, (
        "the aliases and in-scope countries are the other legitimate subjects; "
        "showing them is cheaper than the analyst guessing the house style")


def test_the_register_panel_sits_above_the_footprint_editor():
    """Its purpose is to fill the editor, so below it is the one place it
    cannot do that - it rendered off-screen under the table."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert text.index("/known-facts") < text.index("fp = st.data_editor"), (
        "the register panel must render before the editor it populates")


def test_running_a_footprint_also_saves_it():
    """Two separate acts meant an analyst could edit, run, move to the next
    page and lose the edit: it lived in the run's parameters and nowhere the
    case could see. Running a footprint is a clear enough statement that you
    meant it."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    run_at = text.index('if _run_col.button("Run simulation"')
    assert '"analyst_footprint": footprint' in text[run_at:run_at + 1200]


def test_an_unsaved_edit_warns_before_the_page_is_left():
    """Streamlit discards an edited table on page switch, so silence here
    loses work with no trace."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    assert "Unsaved changes" in page.read_text()


def test_disagreeing_registered_counts_are_flagged():
    """Two Location footprint facts filed under different names for the same
    company are two facts about one thing, and neither will corroborate the
    other - the register matches on subject."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert "registered site counts disagree" in text
    assert "matches on subject" in text


def test_the_simulation_page_resolves_the_footprint_server_side():
    """The precedence was four branches of interface logic and wrong four
    times. One endpoint, one rule, tested in test_footprint_resolution.py."""
    page = next(p for p in PAGES if p.name.startswith("4_"))
    text = page.read_text()
    assert "/footprint\")" in text
    for gone in ("elif _saved:", "elif _last:", "/simulations\")"):
        assert gone not in text, f"{gone} is precedence logic that moved server-side"


def test_a_register_that_fails_to_load_is_not_reported_as_empty():
    """The reported symptom: "info entered under known facts is lost, after
    returning to the page all is empty."

    The list read `.get("known_facts", [])` with no error handling, so a failed
    load rendered "No known facts registered" - identical to an empty
    register. Re-entering the facts is the natural response, and it produces
    duplicates under slightly different subjects that never corroborate each
    other."""
    page = next(p for p in PAGES if p.name.startswith("2_"))
    text = page.read_text()
    assert "Could not load the register" in text
    assert "load failure, not an empty register" in text
    assert "do not re-enter facts" in text


def test_the_empty_register_message_names_the_case():
    """Facts belong to one case. A message that does not say which invites the
    conclusion that they were lost."""
    page = next(p for p in PAGES if p.name.startswith("2_"))
    assert "belong to one case" in page.read_text()


@pytest.mark.parametrize("page", [p for p in PAGES if p.name != "api_client.py"],
                         ids=lambda p: p.name)
def test_no_confirmation_is_swallowed_by_a_rerun(page):
    """st.success() immediately followed by st.rerun() shows nothing: the
    message is written and the script restarts before the browser renders it.
    Every place that confirmed an action and then reran was silent, so a
    successful registration looked like a form that had cleared itself for no
    reason. api.flash() carries the message across."""
    lines = page.read_text().splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if "st.success(" not in line:
            continue
        window = "\n".join(lines[i:i + 5])
        if "st.rerun()" in window:
            offenders.append(f"{page.name}:{i + 1}")
    assert not offenders, (
        f"confirmation discarded by an immediate rerun at {offenders}; use "
        f"api.flash() instead")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_a_page_that_flashes_also_renders_it(page):
    """A flash nobody renders is the silence it was meant to fix."""
    text = page.read_text()
    if "api.flash(" in text and page.name != "api_client.py":
        assert "api.show_flash()" in text, (
            f"{page.name} records a confirmation and never renders it")


# ------------------------------------------------ drafts must survive a switch
def test_the_known_fact_entry_does_not_use_a_form():
    """This was the actual complaint, reported four times, and I kept fixing
    the register instead.

    st.form withholds its widget values from session state until submit, so
    navigating to another page mid-entry discards everything typed. Keyed
    widgets outside a form write as they change, so a half-finished fact
    survives a page switch."""
    page = next(p for p in PAGES if p.name.startswith("2_"))
    text = page.read_text()
    assert "st.form(" not in text, (
        "a form on this page loses a part-typed fact the moment the analyst "
        "looks at another page")
    for key in ("kf_subject", "kf_base", "kf_asserted_by", "kf_unit"):
        assert f'key="{key}"' in text, f"{key} is not keyed, so it is not kept"


def test_the_draft_is_cleared_only_on_success():
    """A rejected registration must keep what was typed. Clearing on failure
    makes the analyst enter it twice to find out what was wrong."""
    page = next(p for p in PAGES if p.name.startswith("2_"))
    text = page.read_text()
    assert "Cleared only on success" in text


def test_the_new_case_entry_does_not_use_a_form():
    """Same trap, same cost: a part-typed case starts from nothing."""
    app_py = next(p for p in PAGES if p.name == "app.py")
    text = app_py.read_text()
    assert 'st.form("new_case")' not in text
    assert 'key="nc_by"' in text


def test_the_case_picker_keeps_its_selection():
    """The cause of "I registered a fact and it is not shown".

    The picker had no index, so it reset to the first entry on every visit to
    the home page - and the list is ordered newest-first. Creating a second
    case therefore switched the active one silently, and every page showed
    that case's empty register. The facts were never lost; they were being
    looked for under the wrong id."""
    app_py = next(p for p in PAGES if p.name == "app.py")
    text = app_py.read_text()
    assert "index=_index" in text, (
        "without an index the picker resets to the newest case on every visit")
    assert 'st.session_state.get("case_id")' in text
    assert "Active case is now" in text, (
        "a silent switch is indistinguishable from data loss, so it is "
        "announced")


def test_the_known_facts_page_names_the_case_it_is_listing():
    page = next(p for p in PAGES if p.name.startswith("2_"))
    assert "Register for" in page.read_text()
