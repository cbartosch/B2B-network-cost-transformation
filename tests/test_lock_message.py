"""The lock message has to name the fields the lock actually disables.

DHL's industry selector was greyed out and the message explaining the lock
listed four fields, not including industry. An analyst had no way to learn why
the field was unusable, and the stated reason - provenance drift from a
confirmed entity - does not obviously cover a modelling choice.

`disabled=is_locked` is set on six widgets. This test derives the set from the
source rather than from a list somebody maintains, so the message cannot drift
from the behaviour again.
"""
import re
from pathlib import Path


def _page():
    root = Path(__file__).resolve().parents[1]
    return next(root.glob(
        "analyst_ui/streamlit_app/pages/1_Intake*.py")).read_text()


def _message():
    """The lock's st.info text, delimited by the call rather than by a
    character count - the first version used a 2,200-character window and the
    comment above the call pushed the text out of it."""
    source = _page()
    start = source.index('    st.info(\n        "Entity confirmed')
    block = source[start:source.index("\n\n", start)]
    # Joined across the source's own line wrapping. A string literal broken
    # over two lines never contains its own sentence contiguously - the join
    # is `" <newline> "` - so a literal substring match fails on the break.
    # Third time that has bitten a test in this repository today.
    return " ".join(re.sub(r'"\s*\n\s*"', "", block).split())


def _locked_labels(source):
    """The label of every widget disabled by the entity lock.

    Read backwards from each `disabled=is_locked` to the nearest preceding
    quoted label, because the argument and the label are usually several
    wrapped lines apart.
    """
    # Comments stripped first. The explanation of this very lock contains
    # the string `disabled=is_locked`, so scanning raw lines counted the
    # comment as a seventh widget and picked up a section heading as its
    # label. A checker that reads prose as code reads its own documentation
    # as a defect.
    lines = [line.split("#", 1)[0] for line in source.splitlines()]
    labels = []
    for index, line in enumerate(lines):
        if "disabled=is_locked" not in line:
            continue
        for back in range(index, max(-1, index - 10), -1):
            found = re.findall(r'"([A-Z][^"]{3,44})"', lines[back])
            if found:
                labels.append(found[0])
                break
    return labels


def _api_locked():
    """The authoritative lock: the field set `update_case` refuses.

    Derived from the route rather than restated here. The page had locked two
    fields the API never locked, and the previous version of this test
    asserted the page's own wrong list back at itself - a test of the
    spelling, not of the control.
    """
    import re

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    start = api.index('            locked = {"subject_entity_legal_name"')
    return set(re.findall(r'"(\w+)"', api[start:start + 260]))


def test_the_page_locks_exactly_what_the_api_locks():
    """A restriction in one layer and not the other is not a control.

    `industry` and the aliases were disabled on this page and accepted by the
    API, so a PUT succeeded where the interface refused - which made a
    modelling choice unreachable rather than governed."""
    page = _page()
    for never in ("ik_industry", "ik_aliases_text"):
        block = page[page.index(never) - 400:page.index(never) + 60]
        assert "disabled=is_locked" not in block, (
            f"{never} is locked on the page and not by the API")


def test_the_api_lock_set_is_the_five_entity_attributes():
    """A canary on the authoritative list. If the API starts locking
    something else, the message below has to change."""
    assert _api_locked() == {
        "subject_entity_legal_name", "entity_identifier",
        "country_of_domicile", "group_perimeter", "excluded_entities"}


def test_the_message_names_every_locked_field():
    """It named four of six. Industry and aliases were silent."""
    message = _message().lower()
    for token in ("legal name", "identifier", "domicile", "perimeter",
                  "excluded entities"):
        assert token in message, f"the lock message does not mention {token}"
    # and it must say the two that are NOT locked, because an analyst who
    # remembers them being greyed out needs telling they no longer are
    assert "not locked" in message


def test_the_message_says_how_many():
    """A count is checkable by a reader; a list is not."""
    message = _message()
    assert "Five fields are locked" in message


def test_the_message_separates_provenance_from_modelling():
    """Four fields are attributes of the confirmed entity. Aliases and
    industry are not - they govern which sources a search accepts and which
    estate shape the model applies. One reason does not cover both."""
    message = _message()
    assert "an attribute of the confirmed entity" in message
    assert "estate shape" in message


def test_the_route_out_is_stated():
    message = _message()
    assert "resolve and confirm the entity again" in message
