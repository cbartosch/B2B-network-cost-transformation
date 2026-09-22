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


def test_the_lock_disables_six_fields():
    """A canary. If this changes, the message below has to change with it."""
    assert len(_locked_labels(_page())) == 6


def test_the_message_names_every_locked_field():
    """It named four of six. Industry and aliases were silent."""
    message = _message().lower()
    for token in ("legal name", "identifier", "domicile", "alias",
                  "industry", "perimeter"):
        assert token in message, f"the lock message does not mention {token}"


def test_the_message_says_how_many():
    """A count is checkable by a reader; a list is not."""
    message = _message()
    assert "Six fields are locked" in message


def test_the_message_separates_provenance_from_modelling():
    """Four fields are attributes of the confirmed entity. Aliases and
    industry are not - they govern which sources a search accepts and which
    estate shape the model applies. One reason does not cover both."""
    message = _message()
    assert "arguably should not be" in message
    assert "an attribute of the confirmed entity" in message


def test_the_route_out_is_stated():
    message = _message()
    assert "resolve and confirm the entity again" in message
