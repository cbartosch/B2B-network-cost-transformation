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


def _page(fragment: str):
    """Find a page by a distinctive part of its name, not its number.

    33 lookups used `startswith("4_")`. Reordering the workflow so dispositions
    precede simulation renumbered both files, and every one of those tests
    silently began asserting against the wrong page - which is how a rename
    turned into twenty-odd failures that named the assertion rather than the
    cause.
    """
    matches = [p for p in PAGES if fragment.lower() in p.name.lower()]
    assert len(matches) == 1, (
        f"{fragment!r} matches {[m.name for m in matches]} - the lookup has to "
        f"be unambiguous or a test can assert against the wrong page")
    return matches[0]


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
    page = _page("Simulation")
    text = page.read_text()
    assert '"archetype": "BRANCH", "sites": 1' in text, (
        "the in-scope-country default must be at least one site")
    assert '"sites": 0' not in text, (
        "a zero default puts the page behind a guard it cannot pass")


# --------------------------------------------- simulation footprint payload
def _clean():
    """The page is a Streamlit script, so the helper is lifted out by source
    rather than imported - importing it would execute the page.

    Bounded by the function definition rather than by a constant above it:
    slicing from `ARCHETYPES = (` broke when the constant moved, and eight
    tests failed with "substring not found", which names the slice and not the
    cause."""
    src = _page("Simulation").read_text()
    # Bounded by the next line at column zero that is not part of the
    # function, found by indentation rather than by guessing a marker: `\nif `
    # matched an `if` *inside* the function and the slice ran into page code
    # that referenced undefined names.
    start = src.index("def _clean_footprint(")
    tail = src[start:].splitlines()
    end = start + len(tail[0]) + 1
    for line in tail[1:]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        end += len(line) + 1
    ns = {"re": __import__("re")}
    exec("ARCHETYPES = (\"BRANCH\", \"LARGE_OFFICE\", \"WAREHOUSE\", "
         "\"DC\", \"STORE\")\n" + src[start:end], ns)
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
    page = _page("Simulation")
    text = page.read_text()
    assert "_ev_failed" in text
    assert "Could not load the promoted site list" in text
    assert "fallen back to placeholder values" in text


def test_the_empty_footprint_message_names_the_case():
    """A promoted footprint belongs to one case. Switching cases empties the
    list, and a message that does not say which case invites the conclusion
    that the promotion was lost."""
    page = _page("Simulation")
    assert "belongs to one" in page.read_text()


def test_the_footprint_editor_reopens_on_what_was_last_run():
    """Reported as "it collapses to default". The editor was transient: an
    analyst typed counts, ran the simulation, and the rerun that followed
    rebuilt the table from the placeholder - so the numbers they had just
    entered disappeared, and the page looked as though it had discarded them.

    Precedence is promoted evidence, then the last run, then a placeholder:
    what you last ran is a better starting point than a guess and a worse one
    than a researched count."""
    page = _page("Simulation")
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
    page = _page("Simulation")
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
    page = _page("Simulation")
    text = page.read_text()
    assert "/known-facts" in text, "the page must read the register"
    assert '"Location footprint"' in text
    assert "Use this count" in text


def test_the_register_count_does_not_invent_a_site_type():
    """The register records how many sites there are, not what kind. A bank
    branch is a STORE under the archetype definitions and is priced at a
    different bandwidth and product from BRANCH, so guessing would silently
    change the estimate."""
    page = _page("Simulation")
    text = page.read_text()
    assert "asked rather than guessed" in text
    assert '"Site type"' in text


def test_decimal_fields_are_coerced_before_formatting():
    """value_base arrives as a JSON string, so formatting it with :g raises
    rather than rendering - a NameError-class defect that only fires on the
    branch where a fact actually exists."""
    page = _page("Simulation")
    assert "def _num(value):" in page.read_text()


def test_the_known_fact_subject_is_prefilled_from_the_case():
    """A blank subject cost a malformed fact - "(None sites)", unresolvable
    forever - and it fragments the register: corroboration and the public
    prefill both match on (fact_class, subject), so "HVB" and "UniCredit Bank
    GmbH" typed on different days are two facts about the same thing that
    never meet."""
    page = _page("Known_facts")
    text = page.read_text()
    assert 'value=_entity' in text, "the subject must default to the case entity"
    assert "subject_entity_legal_name" in text
    assert "Also on this case" in text, (
        "the aliases and in-scope countries are the other legitimate subjects; "
        "showing them is cheaper than the analyst guessing the house style")


def test_the_register_panel_sits_above_the_footprint_editor():
    """Its purpose is to fill the editor, so below it is the one place it
    cannot do that - it rendered off-screen under the table."""
    page = _page("Simulation")
    text = page.read_text()
    assert text.index("/known-facts") < text.index("fp = st.data_editor"), (
        "the register panel must render before the editor it populates")


def test_running_a_footprint_also_saves_it():
    """Two separate acts meant an analyst could edit, run, move to the next
    page and lose the edit: it lived in the run's parameters and nowhere the
    case could see. Running a footprint is a clear enough statement that you
    meant it."""
    page = _page("Simulation")
    text = page.read_text()
    run_at = text.index('if _run_col.button("Run simulation"')
    assert '"analyst_footprint": footprint' in text[run_at:run_at + 1200]


def test_an_unsaved_edit_warns_before_the_page_is_left():
    """Streamlit discards an edited table on page switch, so silence here
    loses work with no trace."""
    page = _page("Simulation")
    assert "Unsaved changes" in page.read_text()


def test_disagreeing_registered_counts_are_flagged():
    """Two Location footprint facts filed under different names for the same
    company are two facts about one thing, and neither will corroborate the
    other - the register matches on subject."""
    page = _page("Simulation")
    text = page.read_text()
    assert "registered site counts disagree" in text
    assert "matches on subject" in text


def test_the_simulation_page_resolves_the_footprint_server_side():
    """The precedence was four branches of interface logic and wrong four
    times. One endpoint, one rule, tested in test_footprint_resolution.py."""
    page = _page("Simulation")
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
    page = _page("Known_facts")
    text = page.read_text()
    assert "Could not load the register" in text
    assert "load failure, not an empty register" in text
    assert "do not re-enter facts" in text


def test_the_empty_register_message_names_the_case():
    """Facts belong to one case. A message that does not say which invites the
    conclusion that they were lost."""
    page = _page("Known_facts")
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
    page = _page("Known_facts")
    text = page.read_text()
    assert "st.form(" not in text, (
        "a form on this page loses a part-typed fact the moment the analyst "
        "looks at another page")
    for key in ("kf_subject", "kf_base", "kf_asserted_by", "kf_unit"):
        assert f'key="{key}"' in text, f"{key} is not keyed, so it is not kept"


def test_a_rejected_registration_keeps_what_was_typed():
    """This asserted "Cleared only on success", which 4.97.0 removed: the form
    is no longer cleared at all, because clearing it read as the entry having
    been lost.

    So this test and test_registering_a_fact_does_not_empty_the_form asserted
    opposite behaviour for six releases, and the suite was never run to find
    out. What both actually protect is that a failure never costs the analyst
    their typing - checked here on the failure path."""
    text = _page("Known_facts").read_text()
    error_path = text.index('st.error(r["_error"])')
    after = text[error_path:error_path + 400]
    assert "_kf_reset" not in after, (
        "a rejected registration must not request a form reset")


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
    page = _page("Known_facts")
    assert "Register for" in page.read_text()


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_widget_key_is_written_after_its_widget_exists(page):
    """Streamlit raises StreamlitAPIException on this, and only when the
    branch runs - so it compiles, renders, and fails the first time somebody
    presses the button.

    The reset that clears the entry form had exactly this shape: it wrote every
    widget key from inside the button handler, which is necessarily after the
    widgets were created. The fix is to request the reset and perform it at the
    top of the next run, before any widget exists.
    """
    import re

    lines = page.read_text().splitlines()
    first_use = {}
    for i, line in enumerate(lines, 1):
        for key in re.findall(r'key="([A-Za-z_0-9]+)"', line):
            first_use.setdefault(key, i)

    offenders = []
    for i, line in enumerate(lines, 1):
        match = re.search(
            r'st\.session_state\[\s*["\']([A-Za-z_0-9]+)["\']\s*\]\s*=', line)
        if not match:
            continue
        key = match.group(1)
        if key in first_use and i > first_use[key]:
            offenders.append(
                f"line {i} assigns {key!r}, whose widget is created at line "
                f"{first_use[key]}")
    assert not offenders, (
        f"{page.name}: " + "; ".join(offenders)
        + ". Request the change and apply it at the top of the next run.")


def test_registering_a_fact_does_not_empty_the_form():
    """Clearing on success reads as the entry having been lost - which is what
    it was reported as. It is also the wrong default for the work: the next
    fact is usually the same subject with a different class or value, faster
    to edit than to retype. Emptying it is a deliberate act."""
    page = _page("Known_facts")
    text = page.read_text()
    success = text.index("api.flash(_msg)")
    after = text[success:success + 600]
    assert "_kf_reset" not in after, (
        "the success path must not request a form reset")
    assert "Clear the form" in text, (
        "there still has to be a way to empty it on purpose")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_widget_has_both_a_default_and_a_session_state_key(page):
    """Streamlit warns that the widget was given a default and also had its
    value set through session state, and the session-state value silently
    wins - so the default is misleading rather than wrong."""
    import re
    offenders = re.findall(
        r'\.(?:number_input|text_input|slider|selectbox|date_input)\('
        r'[^)]*\bvalue=[^)]*\bkey="[A-Za-z_0-9]+"', page.read_text())
    assert not offenders, (
        f"{page.name}: {len(offenders)} widget(s) pass both value= and key=")


def test_the_declared_spend_table_does_not_open_pre_filled():
    """It opened with 1,000,000 for every in-scope country - which nobody reads
    as a placeholder, because it is the right order of magnitude for a real
    telecom spend. It fed the declared-spend crosscheck, so the run reported a
    divergence computed against a figure nobody supplied."""
    page = _page("Run_V0")
    text = page.read_text()
    # step=1_000_000.0 on the anchor input is a stepper increment, not a
    # value - the test has to distinguish those or it fails on something
    # legitimate and gets weakened rather than fixed.
    import re
    invented = [m.group(0) for m in
                re.finditer(r'estimated_annual_spend"?\s*:\s*[\d_]{4,}', text)]
    assert not invented, f"the spend table opens pre-filled: {invented}"
    assert "an invented number produces an invented divergence" in text


def test_the_estimate_drivers_are_not_interface_defaults():
    """5,000 users and 900 per site went straight into the baseline, and had to
    be retyped on every visit - so the figure in use was whatever the defaults
    happened to be."""
    page = _page("Run_V0")
    text = page.read_text()
    assert "5_000)" not in text and "900.0)" not in text
    assert "declared_users" in text and "declared_ops_cost_per_site" in text
    assert "Save these inputs to the case" in text


def test_blank_spend_rows_are_not_sent():
    """A blank row arrived as {"": nan}, which is a country nobody named."""
    page = _page("Run_V0")
    text = page.read_text()
    assert 'r["estimated_annual_spend"] == r["estimated_annual_spend"]' in text, (
        "NaN must be filtered - it is not a spend figure")


def test_research_reports_each_domain_as_it_completes():
    """A run is fifteen to twenty minutes and reported nothing until the last
    domain finished - so a domain that found four sourced quantities and one
    that abstained were indistinguishable for a quarter of an hour, and there
    was no reason to keep watching.

    Streamlit flushes as the script runs, so writing inside the loop is enough;
    the requirement is that the write is inside it."""
    page = _page("Domain_dispositions")
    text = page.read_text()

    loop = text.index("for i, d in enumerate(pending, start=1):")
    after_loop = text.index('st.session_state["_research_log"] = lines')
    body = text[loop:after_loop]
    assert "with log:" in body, (
        "per-domain output must be written inside the walk, not after it")
    for shown in ("verified source(s)", "quantity(ies)", "budget_note",
                  "failure_detail"):
        assert shown in body, f"{shown} is not reported per domain"


def test_the_research_log_survives_the_refresh():
    """The run ended with st.rerun() to refresh the disposition table, which
    discarded everything the loop had written."""
    page = _page("Domain_dispositions")
    text = page.read_text()
    assert '_research_log' in text
    assert 'st.session_state.get("_research_log")' in text, (
        "the log has to be read back after the rerun or it is written and lost")
    assert "Clear this log" in text


def test_the_client_surfaces_the_exception_detail_the_api_sends():
    """The API's 500 handler reports the exception type, the message and the
    last frames outside PRODUCTION. The client read only `detail`, which the
    handler leaves as the bare "Internal Server Error" - so the diagnosis was
    sent on every failure and thrown away here.

    Several rounds went into narrowing a 500 by inference while its cause sat
    in a field nobody read."""
    client = next(p for p in PAGES if p.name == "api_client.py").read_text()
    assert 'body.get("error_type")' in client
    assert 'body.get("where")' in client
    assert '"_error_type"' in client, (
        "callers should be able to branch on the type, not only print it")


def test_an_empty_entity_identifier_warns_at_save_and_names_the_gate():
    """The asterisk was the only signal and it stopped nothing: a case could
    carry an empty identifier through intake, research and simulation, and the
    pre-flight BLOCK surfaced only when V0 was attempted.

    Parking a half-finished case is a real workflow; being surprised at
    publication is not."""
    page = _page("Intake")
    text = page.read_text()
    assert "pre-flight will " in text and "BLOCK" in text
    assert "You can save and come back" in text


def test_a_found_identifier_can_be_accepted_in_one_click():
    """The profile searched for these and showed them as a caption, so an
    analyst who had just been shown the LEI still had to retype it."""
    page = _page("Intake")
    text = page.read_text()
    assert "Set as entity identifier" in text
    assert '"entity_identifier": _pick' in text


# -------------------------------------------------- persistence across a switch
@pytest.mark.parametrize("page_prefix,widgets", [
    ("5_", ("seed", "ensemble_size")),
    ("6_", ("method", "anchor_value")),
])
def test_run_choices_survive_a_page_switch(page_prefix, widgets):
    """A pinned seed is the whole basis of the reproducibility claim, and an
    estimation method decides which question the estimate answers. Both were
    widget state, so switching page reverted them to 42/25/BUILD_UP without
    saying so - and a claim resting on a seed nobody kept is not a claim."""
    page = next(p for p in PAGES if p.name.startswith(page_prefix))
    text = page.read_text()
    assert "run_settings" in text
    for widget in widgets:
        assert f'"{widget}"' in text, f"{widget} is not persisted"


def test_the_prefilled_known_facts_are_editable():
    """A proposal is usually nearly right and wrong in one field - a stale
    as-of date, a loose unit, a value that needs rounding to the perimeter -
    and a take-it-or-leave-it control forced a retype into the form below to
    fix one cell."""
    page = _page("Known_facts")
    text = page.read_text()
    assert "st.data_editor(" in text
    assert 'key="pf_editor"' in text
    for editable in ("value_base", "value_low", "value_high", "unit", "as_of"):
        assert editable in text, editable
    assert 'disabled=["fact_class"' in text, (
        "the class routes the fact, so it is not a free-text field")


def test_editing_a_proposal_does_not_launder_the_source():
    """THIRD_PARTY_REPORT means a public source states this. Once the analyst
    has changed the number that is no longer true, and leaving the basis alone
    would let an edited value borrow the source's standing."""
    import inspect
    from app.domain import known_facts
    src = inspect.getsource(known_facts.accept_public_proposal)
    assert 'proposal.get("edited")' in src
    assert '"INDUSTRY_KNOWLEDGE"' in src


def test_unsaved_disposition_edits_warn_before_the_page_is_left():
    """An unsaved change to 24 dispositions is lost silently on a page switch.
    Warned rather than auto-saved: a disposition is a statement about evidence,
    and writing 24 of them because somebody scrolled would be worse than
    losing them."""
    page = _page("Domain_dispositions")
    text = page.read_text()
    assert "unsaved change(s)" in text
    assert "_changed" in text


# --------------------------------------------------- persistence across pages
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_page_uses_a_form_for_data_entry(page):
    """st.form withholds every widget value until submit, so navigating away
    mid-entry discards the lot. The intake block was sixteen fields behind one
    - and it is exactly what an analyst fills in over several sittings while
    looking things up."""
    assert "st.form(" not in page.read_text(), (
        f"{page.name} still has a form; a part-finished block will not survive "
        f"a page switch")


def test_the_intake_fields_are_keyed():
    page = _page("Intake")
    text = page.read_text()
    assert text.count('key="ik_') >= 15, (
        "each intake field needs its own key or its value dies on navigation")
    assert 'st.button("Save intake block"' in text


def test_the_estimate_inputs_are_keyed():
    """Page 6 had seven inputs and no keys, so the method, the anchor value and
    the driver figures were all lost on leaving the page."""
    page = _page("Run_V0")
    assert page.read_text().count('key="v0_') >= 5


# ----------------------------------------------- the register is prefillable
def test_the_prefilled_proposals_are_editable():
    """A searched figure is usually nearly right and occasionally off by a unit
    or a perimeter. Forcing an analyst to reject the whole proposal and retype
    it discarded the part that was correct."""
    page = _page("Known_facts")
    text = page.read_text()
    assert "st.data_editor(" in text
    assert '"value_base": r["value_base"]' in text, (
        "the edited value must be what is registered, not the original")
    assert '"edited"' in text, (
        "an edited figure is no longer what the source said and the record has "
        "to know")


def test_an_edited_proposal_changes_its_basis():
    """THIRD_PARTY_REPORT attests that a public source states this. Once the
    number has been changed that attestation is false - it is the analyst's
    judgement informed by a source."""
    import inspect
    from app.domain import known_facts
    src = inspect.getsource(known_facts.accept_public_proposal)
    assert 'edited = bool(proposal.get("edited"))' in src
    assert '"INDUSTRY_KNOWLEDGE" if edited else "THIRD_PARTY_REPORT"' in src


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_page_renders_the_same_panel_twice(page):
    """An external audit found two "Ask about this estimate" panels on page 6:
    the feature was built twice in one session and the second commit did not
    notice the first. Both rendered, one of them calling a gate that raised.

    Duplicated UI does not fail - it just shows the analyst two of something
    and lets them use whichever they find first."""
    import re
    from collections import Counter

    headers = re.findall(r'st\.subheader\("([^"]+)"\)', page.read_text())
    repeated = [h for h, n in Counter(headers).items() if n > 1]
    assert not repeated, f"{page.name} renders {repeated} more than once"


@pytest.mark.parametrize("page", [p for p in PAGES if p.parent.name == "pages"],
                         ids=lambda p: p.name)
def test_the_heading_number_matches_the_page_position(page):
    """Reordering the workflow renamed two files and left their headings, so
    the menu said "4. Domain dispositions" and the page itself said "5." - and
    every instruction in the codebase that names a page by number became
    ambiguous about which one it meant."""
    import re

    heading = re.search(r'st\.title\("(\d+)\.', page.read_text())
    if not heading:
        return
    assert heading.group(1) == page.name.split("_")[0], (
        f"{page.name} displays '{heading.group(1)}.'")


PRIMARY_ACTIONS = {
    "1_Intake_and_entity_resolution.py": ("Save intake block", "Confirm"),
    "2_Known_facts.py": ("Register", "Clear the form"),
    "3_Pre_flight.py": ("Acknowledge",),
    "4_Domain_dispositions.py": ("Run research now", "Promote"),
    "5_Simulation.py": ("Run simulation", "Save footprint"),
    "6_Run_V0.py": ("Run V0", "Ask"),
    "8_Savings_recommendation.py": ("Run LLM-07", "Approve"),
    "9_V1_questionnaire.py": ("Save",),
}


@pytest.mark.parametrize("filename,actions", sorted(PRIMARY_ACTIONS.items()))
def test_a_page_keeps_the_action_it_exists_for(filename, actions):
    """The worst defect the first real test run exposed.

    The 4.119.0 edit that turned the public-prefill proposals into an editable
    table sliced from the proposals block to the next divider - and the manual
    entry form sat between them. For five releases the only way to add a known
    fact was to accept one the sweep had proposed, and no test noticed because
    every test about that form asserted on a phrase inside it rather than on the
    form being there.

    A register you cannot write to by hand is not a register of what the team
    knows."""
    page = next((p for p in PAGES if p.name == filename), None)
    assert page is not None, f"{filename} is gone"
    text = page.read_text()
    missing = [a for a in actions if f'button("{a}' not in text]
    assert not missing, f"{filename} no longer offers {missing}"
