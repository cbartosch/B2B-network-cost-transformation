"""Baseline to target, one step per lever, in the order they compound.

Three things the scenario output does not show on its own:

  * ORDER. Levers compound - each acts on what the ones before it left. As a
    flat list they read as additive and a reader adds them up. Repricing a
    circuit and then deleting it is the classic double count and it is
    invisible in a list.
  * BASIS. A governed lever, an analyst's estimate, and a lever that found
    nothing to act on are identical in a total and mean entirely different
    things.
  * WHAT WAS NOT COUNTED. A lever with no cost pool contributes nothing, and
    a bridge that omits it presents a smaller opportunity as a complete one.
"""
from decimal import Decimal

from app.domain import savings_bridge as bridge


SCENARIOS = {
    "A": {"levers": [
        {"lever_id": "LEV-REPRICE-001", "family": "Same-service repricing",
         "saving_base": "2416000", "cost_layers": ["L0"]}],
        "levers_not_applicable": []},
    "B": {"levers": [],
          "levers_not_applicable": [
              {"lever_id": "LEV-MPLS-001", "family": "MPLS substitution",
               "reason": "acts on service_class in ['IPVPN'], and this "
                         "estate's service classes are DIA, ETHERNET"}]},
    "C": {"levers": [],
          "levers_not_applicable": [
              {"lever_id": "LEV-SASE-001", "family": "Platform consolidation",
               "reason": "acts on L2/L4, and this estimate has no baseline "
                         "for L2/L4"}]},
}


def _built():
    return bridge.waterfall(SCENARIOS, current_total="20000000",
                            extra_steps=[{
                                "step": "Backbone to hyperscaler",
                                "saving": "1570000",
                                "because": "no PoP baseline in the model"}])


def _list_estimates_source(api: str) -> str:
    """The body of list_estimates, by AST rather than by byte count.

    Both scans below took the 2,600 characters after `def list_estimates(`.
    That window was measured against the code as it stood, so explaining a
    fix inside the function pushed what they look for out of it - the check
    failed on a comment, with nothing wrong in the code. The same shape has
    now been found five times in this suite.
    """
    import ast

    tree = ast.parse(api)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "list_estimates")
    return ast.get_source_segment(api, fn)


def test_the_steps_compound_rather_than_adding():
    """Each step starts where the last one ended."""
    built = _built()
    for step in built["steps"]:
        assert Decimal(step["to"]) == Decimal(step["from"]) - Decimal(
            step["saving"])
    chain = built["steps"]
    for earlier, later in zip(chain, chain[1:]):
        assert later["from"] == earlier["to"]


def test_it_reconciles():
    """A bridge that nearly reconciles has lost something, and the thing it
    lost is what somebody will ask about."""
    assert bridge.reconciles(_built())


def test_a_governed_lever_and_an_estimate_are_distinguishable():
    built = _built()
    bases = {s["basis"] for s in built["steps"]}
    assert bridge.GOVERNED in bases
    assert bridge.ESTIMATE in bases
    assert built["governed_saving"] != built["total_saving"], (
        "an estimate must not be folded into the governed total")


def test_a_lever_with_no_baseline_is_a_hole_not_a_zero():
    """"No cost pool to act on" and "worth nothing" are different findings,
    and only the first is a gap in the model."""
    built = _built()
    kinds = {k["basis"] for k in built["not_counted"]}
    assert bridge.NO_BASELINE in kinds
    assert bridge.NOT_APPLICABLE in kinds


def test_what_was_not_counted_never_enters_the_total():
    built = _built()
    counted = sum(Decimal(s["saving"]) for s in built["steps"])
    assert Decimal(built["total_saving"]) == counted
    assert built["not_counted"], "the sample has two"


def test_the_governed_share_is_reported():
    """A bridge that is mostly estimate is a hypothesis with a chart."""
    built = _built()
    assert Decimal(built["governed_share"]) < 1
    assert Decimal(built["governed_share"]) > 0


def test_the_note_names_the_levers_that_found_nothing():
    note = _built()["note"]
    assert "compound" in note
    assert "Platform consolidation" in note
    assert "not one worth zero" in note


def test_the_bridge_reaches_the_estimate_response():
    """A module nothing imports is the defect validate_flow caught on the
    first run of this one."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert api.count('"savings_bridge": savings_bridge.waterfall(') == 2, (
        "both the run and the read response must carry it")


# ----------------------------------------- the bridge has to be visible
def test_the_bridge_is_derived_on_read_not_only_on_run():
    """It was only on the POST :run response, so the waterfall was visible
    for one page load on page 6 and invisible on the savings page that exists
    to discuss it.

    Derived from the stored scenarios rather than pinned beside them: it is a
    presentation of those scenarios, not a separate finding, and a pinned
    copy goes stale the first time the ordering or the exclusivity rules
    change. This session has found four stale copies of one thing."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    listing = _list_estimates_source(api)
    assert "savings_bridge.waterfall(" in listing
    assert 'record["savings_bridge"]' in listing


def test_a_snapshot_written_before_the_bridge_existed_does_not_break_the_page():
    """An old snapshot has scenarios shaped differently. Named rather than
    swallowed: a missing bridge on an old snapshot is expected and a missing
    bridge on a new one is a defect."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    listing = _list_estimates_source(api)
    assert '"unavailable"' in listing


def test_the_savings_page_renders_it():
    """A bridge in a response nobody reads is the defect validate_flow
    caught on the module's first run, one layer up."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/8_Savings*.py")).read_text()
    assert "savings_bridge" in page
    assert "How the saving is built" in page
    # and the two things a reader needs beyond the number
    assert "governed_share" in page
    assert "not_counted" in page

def test_the_listed_bridge_is_built_on_the_baseline_the_snapshot_stored(
        session, client):
    """Against the stored snapshot, not against the source text.

    The two tests above scan api.py for `savings_bridge.waterfall(` and
    `record["savings_bridge"]`, and both passed while the listing read
    `current_tco["base"]` - a key that does not exist, because current_tco is
    keyed by cost layer with the total under "total". It was always None, and
    `or 0` turned it into a baseline of zero, so page 8's "How the saving is
    built" showed Baseline 0, "0% of baseline", and a target run-rate equal
    to minus the saving.

    A source scan cannot see that: the call is there and the symbol is there,
    and it is the argument that is wrong. So this reads the number back.
    """
    import uuid

    from sqlalchemy import insert, select

    from app import db

    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(case_id=case_id, created_by="t"))
    session.execute(insert(db.estimate_snapshot).values(
        estimate_snapshot_id=str(uuid.uuid4()), case_id=case_id,
        version_label="V0", v0_status="COMPLETE",
        current_tco={"L0": {"low": "1", "base": "18000000", "high": "3"},
                     "total": {"low": "2", "base": "20000000", "high": "4"}},
        target_tco={}, scenarios=SCENARIOS, gross_run_rate_savings={},
        confidence={}, coverage={}, simulated_share=0.05, asserted_share=0.0,
        pins={}, levers=[]))
    session.commit()

    r = client.get(f"/v1/outside-in/cases/{case_id}/estimates")
    assert r.status_code == 200, r.text
    wf = r.json()["snapshots"][0]["savings_bridge"]

    assert "unavailable" not in wf, wf
    assert Decimal(wf["baseline"]) == Decimal("20000000"), (
        "the bridge was built on a baseline the snapshot does not hold")
    # And the rest of it follows from the baseline, so a zero there is not a
    # cosmetic error: it takes the percentage and the target with it.
    assert Decimal(wf["saving_pct"]) > 0
    assert (Decimal(wf["baseline"]) - Decimal(wf["total_saving"])
            == Decimal(wf["target"]))


def test_a_baseline_the_snapshot_cannot_supply_is_reported_not_zeroed(
        session, client):
    """The `or 0` that hid the bug above would hide the next one too.

    A snapshot with no usable total is an old or malformed one, and the
    listing already has a path for that: it names the failure rather than
    swallowing it. Zero is the one answer that is both wrong and plausible.
    """
    import uuid

    from sqlalchemy import insert

    from app import db

    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(case_id=case_id, created_by="t"))
    session.execute(insert(db.estimate_snapshot).values(
        estimate_snapshot_id=str(uuid.uuid4()), case_id=case_id,
        version_label="V0", v0_status="COMPLETE",
        current_tco={"L0": {"base": "18000000"}},      # no "total"
        target_tco={}, scenarios=SCENARIOS, gross_run_rate_savings={},
        confidence={}, coverage={}, simulated_share=0.05, asserted_share=0.0,
        pins={}, levers=[]))
    session.commit()

    r = client.get(f"/v1/outside-in/cases/{case_id}/estimates")
    assert r.status_code == 200, r.text
    wf = r.json()["snapshots"][0]["savings_bridge"]
    assert "unavailable" in wf, (
        "a bridge with no baseline to build on must say so, not report one "
        "built on zero")
