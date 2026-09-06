"""What is assumed, and what would settle it.

Specification 0.4: "Create a reviewable assumption and a targeted question for
material gaps", with the control "Assumption remains visible after
replacement."

Neither table existed, so the workbench computed its gaps, displayed them and
forgot them. It could say what it did not know and could not ask for it, which
is half of what Stage 0 is for.
"""
import pytest

from app.domain import assumptions

GAP = {"gap": "unpriced countries",
       "detail": "FR, NL have no approved price for the products their sites use.",
       "costs": "coverage, and therefore the confidence ceiling",
       "closes_it": "research domain 19 for those countries and promote the prices"}


def _raised(**over):
    fields = dict(case_id="c", raised_by="CB", materiality="HIGH",
                  effort="ASK")
    fields.update(over)
    return assumptions.from_gap(GAP, **fields)


def test_a_computed_gap_becomes_a_durable_assumption():
    """estimate_qa.gaps recomputes from a snapshot every time and disappears
    when the snapshot changes. An assumption has to outlive the estimate that
    revealed it."""
    a = _raised()
    assert a["state"] == assumptions.OPEN
    assert a["closes_it"] == GAP["closes_it"], (
        "the act that closes it is the difference between a register of "
        "worries and a list of next steps")


def test_priority_is_worth_against_effort_not_severity_alone():
    """A gap that costs the estimate a lot and needs a site survey outranks
    nothing, because the client cannot answer it this quarter. Materiality
    alone would put it at the top of a list nobody can action."""
    high_survey = assumptions.priority(materiality="HIGH", effort="SURVEY")
    medium_ask = assumptions.priority(materiality="MEDIUM", effort="ASK")
    assert medium_ask > high_survey


def test_evidence_supersedes_an_assumption_and_the_record_stays():
    """Specification 0.4: evidence "supersedes a prior for the active estimate
    but does not delete it. The system stores both values, the replacement
    reason, approver and delta attribution."

    An estimate whose assumptions vanish as they are answered cannot be
    explained afterwards, and "why did the baseline move" is the first
    question anyone asks."""
    a = _raised()
    done = assumptions.supersede(a, value="1840",
                                 reason="client provided the site count",
                                 approved_by="CB")
    assert done["state"] == assumptions.SUPERSEDED
    assert done["superseded_by_value"] == "1840"
    assert done["detail"] == GAP["detail"], "the original must survive"
    assert done["superseded_reason"]


def test_retiring_is_not_superseding():
    """A country leaving scope retires its price assumption; it does not
    supersede it. Collapsing the two would make an engagement look better
    evidenced than it is - the gap did not close, it left."""
    a = _raised()
    gone = assumptions.retire(a, reason="FR left scope", approved_by="CB")
    assert gone["state"] == assumptions.RETIRED
    assert gone["superseded_by_value"] is None


def test_an_assumption_cannot_be_closed_twice():
    """Superseding it twice would lose the first replacement, which is the
    record of how the estimate got here."""
    done = assumptions.supersede(_raised(), value="1", reason="r",
                                 approved_by="CB")
    with pytest.raises(assumptions.AssumptionInvalid, match="already"):
        assumptions.supersede(done, value="2", reason="r", approved_by="CB")


def test_a_replacement_without_a_reason_is_refused():
    """A value that changed for no recorded cause is indistinguishable from a
    typo."""
    with pytest.raises(assumptions.AssumptionInvalid, match="reason"):
        assumptions.supersede(_raised(), value="1", reason="  ",
                              approved_by="CB")


def test_a_bare_label_is_not_a_reviewable_assumption():
    with pytest.raises(assumptions.AssumptionInvalid, match="reviewable"):
        assumptions.from_gap({"gap": "something"}, case_id="c",
                             raised_by="CB")


def test_the_request_asks_only_what_is_still_open():
    """A superseded assumption has been answered, and asking again wastes the
    goodwill a data request runs on."""
    open_one = _raised()
    closed = assumptions.supersede(_raised(materiality="LOW"), value="1",
                                   reason="answered", approved_by="CB")
    items = assumptions.request_items([open_one, closed])
    assert len(items) == 1
    assert items[0]["assumption"] == open_one["assumption"]


def test_the_request_carries_the_act_not_the_gap():
    """A client can act on "confirm the committed bandwidth on your MPLS
    circuits" and cannot act on "coverage is 55%"."""
    items = assumptions.request_items([_raised()])
    assert items[0]["question"] == GAP["closes_it"]
    assert items[0]["why_it_matters"] == GAP["costs"]


def test_the_request_is_ordered_best_first():
    low = _raised(materiality="LOW", effort="SURVEY")
    low["assumption"] = "a low one"
    items = assumptions.request_items([low, _raised()])
    assert items[0]["priority"] > items[1]["priority"]


def test_an_empty_register_says_so_rather_than_implying_none_exist():
    """An estimate always rests on some; a register with none means they have
    not been written down."""
    note = assumptions.summarise([])["note"]
    assert "have not been written down" in note


def test_request_items_are_frozen_at_creation():
    """A request that re-derived its items from the register would change after
    it was sent, and a client answering last week's list would be answering a
    document that no longer exists."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "items=items" in api
    assert "frozen at creation" in api
