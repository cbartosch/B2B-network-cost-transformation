"""Where the footprint comes from.

This rule lived in the simulation page as four branches of Streamlit logic and
was wrong in a different way on four separate occasions: it ignored the case's
own scope, then it discarded typed counts on rerun, then it persisted only what
had been run, then it never read the known-facts register at all. Each fix was
correct and none was the last, because the rule was expressed in the one place
that could not be tested.
"""
import uuid

import pytest
from sqlalchemy import insert

from app import db
from app.domain import footprint


def _case(session, **over):
    case_id = str(uuid.uuid4())
    values = dict(case_id=case_id, created_by="t",
                  subject_entity_legal_name="Adolf Wuerth GmbH & Co. KG",
                  country_of_domicile="DE",
                  in_scope_countries=["DE", "FR", "GB", "US", "NL", "SG", "AE"])
    values.update(over)
    session.execute(insert(db.case).values(**values))
    session.commit()
    return case_id


def _fact(session, case_id, value, *, subject="Adolf Wuerth GmbH & Co. KG",
          state="PENDING", fact_class="Location footprint"):
    session.execute(insert(db.known_fact).values(
        known_fact_id=str(uuid.uuid4()), case_id=case_id,
        fact_class=fact_class, subject=subject, value_base=value, unit="sites",
        asserted_by="CB", basis="THIRD_PARTY_REPORT",
        verifiability="PUBLICLY_VERIFIABLE", corroboration_state=state))
    session.commit()


def test_a_registered_fact_reaches_the_footprint_without_being_applied(session):
    """The failure reported four times: a fact sat in the register while the
    simulation ran on placeholders, because applying it meant finding a panel
    and clicking through it."""
    case_id = _case(session)
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT_UNALLOCATED"
    assert out["unallocated_sites"] == 1000
    # Deliberately not a row of 1000. A row asserts that every site in it is
    # identical, and the whole row is priced at that archetype's tier.
    assert out["footprint"] == []
    assert out["needs_split"] is True


def test_a_bulk_total_is_never_emitted_as_one_row(session):
    """100 sites are never identical.

    A footprint row states that every site in it shares one bandwidth, one
    primary and backup product, one dual-access probability and one
    users-per-site figure - and the whole row is costed at that archetype's
    tier. Emitting 1000 sites as a single BRANCH row priced an entire estate at
    a tier nobody chose, and it looked like a footprint rather than the
    unallocated number it was.

    Inventing a split would be worse: a plausible mix is still a mix nobody
    decided, and it would be priced as though someone had."""
    case_id = _case(session)
    _fact(session, case_id, 1000)
    out = footprint.resolve(session, case_id)
    assert out["footprint"] == []
    assert out["unallocated_sites"] == 1000
    assert "cannot sit in one row" in out["split_note"]
    assert out["suggested_country"] == "DE"


def test_a_corroborated_fact_beats_an_uncorroborated_one(session):
    case_id = _case(session)
    _fact(session, case_id, 500, subject="Wuerth", state="UNCORROBORATED")
    _fact(session, case_id, 2900, state="CORROBORATED")
    out = footprint.resolve(session, case_id)
    assert out["unallocated_sites"] == 2900
    assert "not used" in out["detail"], (
        "the competing count must be reported, not silently dropped")


def test_a_contradicted_fact_loses_to_a_pending_one(session):
    case_id = _case(session)
    _fact(session, case_id, 9999, state="CONTRADICTED")
    _fact(session, case_id, 1000, state="PENDING")
    assert footprint.resolve(session, case_id)["unallocated_sites"] == 1000


def test_the_register_fixes_the_total_and_the_table_only_splits_it(session):
    """The ordering was backwards, and that was the whole complaint.

    A registered fact is a deliberate, attributed, dated statement by a named
    person; the footprint table is a working surface. Ranking the surface above
    the register let a scratch edit silently override what the team had
    recorded - and a register anything can override is not a register.

    So the fact fixes the total, the saved rows provide the breakdown, and a
    disagreement between them is named rather than resolved."""
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 350}])
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT_SPLIT"
    assert out["register_total"] == 1000
    assert out["split_total"] == 350
    assert out["diverges"] is True
    assert "register is not changed by this page" in out["split_note"]
    # The analyst's breakdown is still what runs - overwriting it would be its
    # own kind of discarding.
    assert out["footprint"][0]["sites"] == 350


def test_promoted_research_outranks_everything(session):
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 350}])
    _fact(session, case_id, 1000)
    session.execute(insert(db.evidenced_footprint).values(
        id=str(uuid.uuid4()), case_id=case_id, country="DE",
        archetype="STORE", sites=371, source_count=3, band_low=341,
        band_high=400, promoted_by="Priya Raman"))
    session.commit()
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "PROMOTED_RESEARCH"
    assert out["footprint"][0]["sites"] == 371


def test_a_fact_of_another_class_is_not_a_footprint(session):
    case_id = _case(session)
    _fact(session, case_id, 5000, fact_class="Remote-user population")
    assert footprint.resolve(session, case_id)["origin"] == "SCOPE_PLACEHOLDER"


def test_a_case_with_scope_and_nothing_else_is_still_runnable(session):
    case_id = _case(session)
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "SCOPE_PLACEHOLDER"
    assert len(out["footprint"]) == 7
    assert all(r["sites"] == 1 for r in out["footprint"])


def test_a_case_with_no_scope_falls_back_to_illustrative(session):
    case_id = _case(session, in_scope_countries=[], country_of_domicile=None)
    assert footprint.resolve(session, case_id)["origin"] == "ILLUSTRATIVE"


def test_a_valueless_fact_is_ignored(session):
    case_id = _case(session)
    session.execute(insert(db.known_fact).values(
        known_fact_id=str(uuid.uuid4()), case_id=case_id,
        fact_class="Location footprint", subject="Wuerth", value_base=None,
        unit="sites", asserted_by="CB", basis="INDUSTRY_KNOWLEDGE",
        verifiability="PUBLICLY_VERIFIABLE"))
    session.commit()
    assert footprint.resolve(session, case_id)["origin"] == "SCOPE_PLACEHOLDER"


def test_a_saved_placeholder_does_not_outrank_the_register(session):
    """Two of my own changes combined into this.

    Running a simulation persists the footprint, so an edit is not lost on the
    rerun that follows - which meant running the placeholder saved the
    placeholder. That saved placeholder then outranked a registered fact of
    1000 sites, because a saved footprint is normally a decision. The
    convenience of one change became the blocker for another.

    A save that exactly matches what the placeholder would produce records
    nothing anybody decided, so it is treated as absent."""
    case_id = _case(session, analyst_footprint=[
        {"country": c, "archetype": "BRANCH", "sites": 1}
        for c in ["DE", "FR", "GB", "US", "NL", "SG", "AE"]])
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT_UNALLOCATED"
    assert out["unallocated_sites"] == 1000


def test_a_saved_footprint_is_used_when_the_register_holds_nothing(session):
    """With no registered fact there is no total to reconcile against, so the
    saved rows are simply what runs."""
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 350}])
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "ANALYST_SAVED"
    assert out["footprint"][0]["sites"] == 350


def test_nothing_in_this_module_writes_to_the_register():
    """A fact is immutable until a user changes it on page 2. This module
    reads."""
    import inspect
    src = inspect.getsource(footprint)
    for write in ("insert(", "update(", "delete(", "session.commit"):
        assert write not in src, f"footprint resolution must not {write}"


def test_a_deliberate_single_site_footprint_still_wins(session):
    """The placeholder rule has to be narrow. One site in one country that an
    analyst meant is not the placeholder - it does not match the country set -
    and must not be discarded as though it were."""
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "BRANCH", "sites": 1}])
    _fact(session, case_id, 1000)

    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT_SPLIT"
    assert out["footprint"][0]["sites"] == 1
    assert out["diverges"] is True


def test_a_breakdown_that_sums_to_the_registered_total_does_not_diverge(session):
    """The normal case once an analyst has split it: same total, distributed."""
    case_id = _case(session, analyst_footprint=[
        {"country": "DE", "archetype": "STORE", "sites": 880},
        {"country": "FR", "archetype": "STORE", "sites": 120}])
    _fact(session, case_id, 1000)
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT_SPLIT"
    assert out["diverges"] is False
    assert sum(r["sites"] for r in out["footprint"]) == 1000


def test_an_edited_placeholder_is_not_a_placeholder(session):
    """Changing one count makes it a decision about that country."""
    rows = [{"country": c, "archetype": "BRANCH", "sites": 1}
            for c in ["DE", "FR", "GB", "US", "NL", "SG", "AE"]]
    rows[0]["sites"] = 900
    case_id = _case(session, analyst_footprint=rows)
    _fact(session, case_id, 1000)
    assert footprint.resolve(session, case_id)["origin"] == "KNOWN_FACT_SPLIT"


def test_clearing_the_saved_footprint_falls_back_to_the_register(session):
    case_id = _case(session, analyst_footprint=[])
    _fact(session, case_id, 1000)
    assert footprint.resolve(session, case_id)["origin"] == "KNOWN_FACT"


def test_the_resolver_says_why_each_source_was_not_used(session):
    """The control that should have existed five rounds ago. "The register is
    ignored" was unanswerable from the interface, so each round was spent
    inferring which branch had fired."""
    case_id = _case(session)
    out = footprint.resolve(session, case_id)
    trace = {c["source"]: c for c in out["considered"]}
    assert set(trace) >= {"PROMOTED_RESEARCH", "ANALYST_SAVED", "KNOWN_FACT"}
    assert trace["PROMOTED_RESEARCH"]["used"] is False
    assert "promoted" in trace["PROMOTED_RESEARCH"]["reason"]
    assert "register is empty" in trace["KNOWN_FACT"]["reason"]


def test_the_reason_distinguishes_a_missing_fact_from_an_unusable_one(session):
    """A fact that is present but unusable looked identical to no fact at all,
    and that ambiguity is what made this undiagnosable without reading the
    database by hand."""
    from sqlalchemy import insert
    case_id = _case(session)
    session.execute(insert(db.known_fact).values(
        known_fact_id=str(uuid.uuid4()), case_id=case_id,
        fact_class="Remote-user population", subject="Wuerth",
        value_base=5000, unit="users", asserted_by="CB",
        basis="INDUSTRY_KNOWLEDGE", verifiability="PUBLICLY_VERIFIABLE"))
    session.commit()

    out = footprint.resolve(session, case_id)
    reason = next(c["reason"] for c in out["considered"]
                  if c["source"] == "KNOWN_FACT")
    assert "Remote-user population" in reason, (
        "naming what the register does hold is what turns a dead end into a "
        "diagnosis")


def test_a_placeholder_save_says_so_in_the_trace(session):
    case_id = _case(session, analyst_footprint=[
        {"country": c, "archetype": "BRANCH", "sites": 1}
        for c in ["DE", "FR", "GB", "US", "NL", "SG", "AE"]])
    _fact(session, case_id, 1000)
    out = footprint.resolve(session, case_id)
    assert out["origin"] == "KNOWN_FACT"
    reason = next(c["reason"] for c in out["considered"]
                  if c["source"] == "ANALYST_SAVED")
    assert "placeholder" in reason


# --------------------------- a total proposes a split rather than blocking
def _mix_rows():
    from app.seed import DENSITY_MIX
    import types as _t
    return [_t.SimpleNamespace(industry=i, archetype=a, density_band=b,
                               share=s)
            for i, a, b, s in DENSITY_MIX]


class _MixSession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _q):
        import types as _t
        return _t.SimpleNamespace(all=lambda: self._rows)


def _propose(total, industry, rows=None):
    from app.domain import footprint
    wanted = industry or "DEFAULT"
    pool = [r for r in (rows or _mix_rows())
            if r.industry in (wanted, "DEFAULT")]
    return footprint.propose_split(_MixSession(pool), total=total,
                                   country="DE", industry=industry)


def test_a_registered_total_proposes_a_split_instead_of_an_empty_table():
    """2,023 sites arrived with an empty table and a message saying nothing
    would be guessed. Right about silent invention, wrong about the remedy: the
    analyst had to invent the split anyway, with no help, and the page was
    blocked until they did."""
    out = _propose(2023, "RETAIL")
    assert out["rows"], "a total with a governed mix must propose something"
    assert len(out["rows"]) >= 4, "a real estate is several clusters"
    assert out["basis"] == "INDUSTRY_DEFAULT"


def test_the_proposed_rows_sum_to_the_total():
    """A split that does not add up is worse than no split - it reads as
    arithmetic. Rounding each share independently loses sites."""
    for total in (1, 7, 100, 2023, 4000, 12345):
        rows = _propose(total, "RETAIL")["rows"]
        assert sum(r["sites"] for r in rows) == total, total


def test_the_proposal_says_it_is_a_default_and_not_a_finding():
    """The whole difference between this and silently inventing a mix."""
    note = _propose(2023, "RETAIL")["note"]
    assert "governed default, not a finding" in note
    assert "Nothing is saved until you save or run" in note


def test_an_unknown_sector_falls_back_and_says_which():
    out = _propose(2023, "SHIPBUILDING")
    assert out["basis"] == "GENERIC_DEFAULT"
    assert sum(r["sites"] for r in out["rows"]) == 2023


def test_a_retail_estate_is_mostly_stores_and_a_logistics_one_is_not():
    """If every sector proposed the same shape the mix would buy nothing."""
    def share_of(industry, archetype):
        rows = _propose(1000, industry)["rows"]
        return sum(r["sites"] for r in rows if r["archetype"] == archetype)

    assert share_of("RETAIL", "STORE") > 900
    assert share_of("LOGISTICS", "WAREHOUSE") > 600
    assert share_of("LOGISTICS", "STORE") < 300


def test_every_proposed_row_carries_a_density_band():
    """The point of proposing at all: an estate split only by site type is
    still priced as though every store could take the same circuit."""
    for row in _propose(2023, "RETAIL")["rows"]:
        assert row["density"], row


def test_nothing_is_proposed_for_a_zero_total():
    assert _propose(0, "RETAIL")["rows"] == []


def test_every_seeded_mix_sums_to_one():
    """A mix summing to less silently drops sites; summing to more invents
    them, and largest remainder would hide both."""
    from collections import defaultdict
    from decimal import Decimal

    from app.seed import DENSITY_MIX
    totals = defaultdict(Decimal)
    for industry, _a, _b, share in DENSITY_MIX:
        totals[industry] += Decimal(share)
    for industry, total in totals.items():
        assert total == Decimal("1.0000"), f"{industry} sums to {total}"


def test_every_mix_names_an_archetype_and_band_the_model_knows():
    """A row naming a band serviceability has never heard of would price as
    unclustered, silently undoing the split."""
    from app.seed import ARCHETYPES, DENSITY_BANDS, DENSITY_MIX
    known_archetypes = {a for a, *_ in ARCHETYPES}
    for _i, archetype, band, _s in DENSITY_MIX:
        assert archetype in known_archetypes, archetype
        assert band in DENSITY_BANDS, band


# ------------------------------- the analyst chooses which total to model
class _Fact:
    def __init__(self, **kw):
        self.__dict__.update({
            "known_fact_id": "f1", "fact_class": "Location footprint",
            "subject": "Boots UK Limited", "value_base": 1840,
            "value_low": None, "value_high": None, "unit": "sites",
            "corroboration_state": "PENDING", "asserted_by": "CB",
            "basis": "THIRD_PARTY_REPORT", "supplied_note": None, **kw})


class _FactSession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _q):
        import types as _t
        return _t.SimpleNamespace(all=lambda: self._rows,
                                  first=lambda: (self._rows or [None])[0])


def _candidates(rows):
    from app.domain import footprint
    return footprint.total_candidates(_FactSession(rows), case_id="c")


def test_two_complementary_facts_are_offered_with_their_sum():
    """The defect: 1,840 UK stores and 89 Ireland stores are both true, and the
    resolver's rule - best standing, then largest value - took 1,840 and
    silently dropped Ireland.

    No rule can tell a rival count from a complementary one. Only a person
    reading the units can, so the sum is offered as a choice."""
    out = _candidates([
        _Fact(known_fact_id="uk", value_base=1840, unit="retail stores (UK)"),
        _Fact(known_fact_id="ie", value_base=89, unit="stores (Ireland)")])
    ids = [c["known_fact_id"] for c in out["choices"]]
    assert ids[:2] == ["uk", "ie"] or set(ids[:2]) == {"uk", "ie"}
    assert "SUM" in ids
    total = next(c for c in out["choices"] if c["known_fact_id"] == "SUM")
    assert total["sites"] == 1929


def test_a_single_total_offers_no_choice():
    """Offering a choice between one thing is noise."""
    out = _candidates([_Fact()])
    assert [c["known_fact_id"] for c in out["choices"]] == ["f1"]
    assert "nothing to choose between" in out["note"]


def test_the_explanation_carries_the_qualification():
    """"total UK entity headcount band" is usually the whole reason one of
    these is the right one."""
    out = _candidates([
        _Fact(known_fact_id="a", supplied_note="Republic of Ireland only"),
        _Fact(known_fact_id="b", value_base=1840)])
    a = next(c for c in out["choices"] if c["known_fact_id"] == "a")
    assert a["supplied_note"] == "Republic of Ireland only"


def test_an_unusable_fact_is_not_offered_but_is_explained():
    """A cost line filed as a footprint must not appear as a choice, and must
    not vanish either - the analyst has to know it was ignored."""
    out = _candidates([
        _Fact(known_fact_id="ok", value_base=1840),
        _Fact(known_fact_id="cost", value_base=460_000_000, unit="EUR/year")])
    assert [c["known_fact_id"] for c in out["choices"]] == ["ok"]
    assert out["rejected"] and out["rejected"][0]["known_fact_id"] == "cost"


def test_the_suggested_total_is_a_suggestion_not_a_decision():
    out = _candidates([_Fact(known_fact_id="a", value_base=1840),
                       _Fact(known_fact_id="b", value_base=89)])
    assert out["suggested"] in ("a", "b")
    assert "Nothing is chosen until you choose it" in out["note"]


def test_choosing_the_sum_is_attributed_to_the_person_who_chose_it():
    """It is their judgement that the facts are complementary, not a new
    source - so the synthetic total carries their name and the weakest
    corroboration standing of its parts."""
    import inspect
    from app.domain import footprint

    src = inspect.getsource(footprint._best_footprint_fact)
    assert 'chosen == "SUM"' in src
    assert "footprint_total_chosen_by" in src
    assert "min(" in src, "the sum cannot be better corroborated than its parts"


def test_a_chosen_fact_that_disappears_is_reported_not_silently_replaced():
    """Falling back silently would model a different estate under the same
    recorded decision."""
    import inspect
    from app.domain import footprint

    src = inspect.getsource(footprint._best_footprint_fact)
    assert "is no longer a usable" in src


def test_every_resolver_branch_returns_the_same_keys():
    """Six branches emitted between 6 and 15 keys, so every read on the page
    was a guess about which one had run - and `_fp["register_total"]` raised
    KeyError the moment a saved footprint with no register entry came back.

    Guarding each read is the same guess written out. One shape removes the
    question, and a branch with nothing to say about a key says None rather
    than omitting it."""
    import ast
    import inspect

    from app.domain import footprint

    contract = set(footprint.RESOLVED_SHAPE)
    assert "register_total" in contract and "origin" in contract

    tree = ast.parse(inspect.cleandoc(inspect.getsource(footprint.resolve)))
    branches = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Return) and node.value is not None):
            continue
        rendered = ast.unparse(node.value)
        if not rendered.startswith("{") and "_shaped(" not in rendered:
            continue
        branches += 1
        assert "_shaped(" in rendered, (
            f"a branch returns a bare dict, so its keys depend on which "
            f"path ran: {rendered[:90]}")
    assert branches >= 5, f"only {branches} branches seen - the sweep is blind"


def test_shaping_fills_a_missing_key_rather_than_dropping_it():
    from app.domain import footprint

    shaped = footprint._shaped({"origin": "ANALYST_SAVED", "footprint": []})
    assert shaped["register_total"] is None
    assert shaped["diverges"] is False
    assert shaped["other_footprint_facts"] == []
    # and a branch's own value always wins over the default
    assert footprint._shaped({"register_total": 1929})["register_total"] == 1929
