"""What the analyst sees while a domain is running.

Seventeen domains, each a live provider call carrying a web search plus an
independent fetch of every source it cites - one to three minutes apiece, so a
full pass is most of an hour.

The status line reported "[0s elapsed]" and never moved, because it was
written before the call and Streamlit cannot update a widget while a
synchronous request is in flight. A frozen clock reads as a hung run, which is
the one thing a progress line exists to disprove.
"""
import ast
from pathlib import Path


def _page():
    root = Path(__file__).resolve().parents[1]
    return next(root.glob(
        "analyst_ui/streamlit_app/pages/4_Domain_dispositions.py")).read_text()


def test_the_status_line_does_not_promise_a_live_clock():
    """A number that cannot advance is worse than no number: it tells the
    analyst the run is stuck when it is working."""
    source = _page()
    assert "s elapsed]" not in source, (
        "an elapsed counter written before a blocking call cannot move")


def test_it_says_what_is_happening_and_how_long_it_takes():
    """The honest substitute for a live clock: name the work and its expected
    duration, so a two-minute wait is recognisable as normal."""
    # Normalised, because the f-string wraps across two source lines and a
    # literal substring match fails on the break. Asserting the rendered
    # words rather than their layout.
    source = " ".join(_page().split())
    assert 'searching and " f"fetching now' in source or \
        "searching and fetching now" in source
    assert "one to three minutes" in source


def test_it_reports_real_time_for_the_domains_that_finished():
    """Elapsed time is knowable for work that has completed, and that is the
    part worth showing - it tells the analyst how much of the hour is left."""
    source = _page()
    assert "done in" in source


def test_the_search_timeout_allows_the_work_it_describes():
    """A page promising minutes against a transport that gives up in seconds
    is how every search-using call failed three times over before 4.71."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "config.py").exists())
    config = (app / "config.py").read_text()

    search = float(ast.literal_eval(
        config.split('LLM_SEARCH_TIMEOUT_SECONDS = float(\n        os.getenv("LLM_SEARCH_TIMEOUT_SECONDS", ')[1].split(")")[0]))
    assert search >= 300, (
        f"a search-carrying call is minutes; {search}s does not allow it")

    # and the page must wait longer than the server will
    page = _page()
    assert "timeout=600.0" in page, (
        "the client must outlast the provider timeout, or a call that would "
        "have returned is reported as a client error")
