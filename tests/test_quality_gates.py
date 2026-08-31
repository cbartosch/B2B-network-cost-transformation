

# ---------------------------------------------- corroboration reports what it found
def test_a_different_unit_is_reported_not_discarded():
    """Observed in the field. A fact asserting 400 *sites* met six sources
    stating 30 to 770 *branches*, and the comparison silently `continue`d past
    every one of them, reporting only "none stated a comparable value". The
    unit difference is real and must not be papered over - but hiding the
    figures is worse than either, because they are the answer to the question
    the analyst was actually asking."""
    from decimal import Decimal as D
    from app.domain.known_facts import _compare_candidates

    cands = [{"publisher": "Fair Finance Guide", "public_value": 371,
              "unit": "branches", "as_of": "2023"},
             {"publisher": "relbanks", "public_value": 579, "unit": "branches"}]
    state, _, reason, detail = _compare_candidates(
        asserted=400, unit="sites", currency=None, candidates=cands,
        tolerance=D("0.10"))

    assert state == "UNCORROBORATED"
    assert len(detail["other_unit"]) == 2
    assert "371" in reason and "branches" in reason
    assert "derivation" in reason, (
        "the reason should say what to do instead, not only what failed")


def test_a_wide_spread_weakens_a_match_rather_than_hiding_it():
    from decimal import Decimal as D
    from app.domain.known_facts import _compare_candidates
    cands = [{"publisher": "a", "public_value": 30, "unit": "branches"},
             {"publisher": "b", "public_value": 371, "unit": "branches"},
             {"publisher": "c", "public_value": 770, "unit": "branches"}]
    state, _, reason, _ = _compare_candidates(
        asserted=400, unit="branches", currency=None, candidates=cands,
        tolerance=D("0.10"))
    assert state == "CORROBORATED"
    assert "disagree widely" in reason, (
        "a nearest-match inside tolerance drawn from sources spanning 30 to "
        "770 is weak evidence and has to say so")
