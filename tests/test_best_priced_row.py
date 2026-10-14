"""Choosing between two approved rate-card rows for the same circuit.

The card can hold a seeded assumption and a researched price that displaces
it, both approved, both keyed (country, product, bandwidth) - which is
exactly how `priors` is keyed. Both collided and query order decided.

It decided for the seed. Approving six researched prices, including GB MPLS
at GBP 200 against a seeded USD 1,000, moved the 26-company set by exactly
nothing, because every one lost to the assumption it was meant to replace.
"""
import types

import pytest

from app.domain import estimate


def _row(id, grade, base, country="GB", product="DIA", bw=100,
         basis="SEED"):
    return types.SimpleNamespace(id=id, country=country, product=product,
                                 bandwidth_mbps=bw, evidence_grade=grade,
                                 base=base, price_basis=basis)


def test_an_approved_price_beats_a_seed_of_the_same_grade():
    """The defect coming back by another road.

    The seed stamped every rate grade E, so a grade tie between a promoted
    price and a seeded one could not happen and the id was a harmless last
    resort. Then the seed started carrying the real grade of the five rows
    that came from a UK leased-line market survey, and GB DIA at 100 Mbps
    had two grade C rows: the survey-derived seed at USD 335 and the
    approved Virgin Media price at GBP 185. "GB-DIA-100" sorts before
    "GB-DIA-100-researched", so the assumption displaced the approval and
    the British estates got more expensive - this function's own bug,
    re-opened by better evidence somewhere else.
    """
    kept = estimate.best_priced_rows([
        _row("GB-DIA-100", "C", 335, basis="SEED"),
        _row("GB-DIA-100-researched", "C", 185, basis="PROMOTED")])
    assert [r.base for r in kept] == [185]


def test_the_approval_wins_whichever_order_they_arrive_in():
    rows = [_row("GB-DIA-100", "C", 335, basis="SEED"),
            _row("GB-DIA-100-researched", "C", 185, basis="PROMOTED")]
    assert estimate.best_priced_rows(rows)[0].base == 185
    assert estimate.best_priced_rows(list(reversed(rows)))[0].base == 185


def test_evidence_still_outranks_who_set_the_row():
    """Basis breaks a tie; it does not overturn one. A seeded grade C beats
    a promoted grade E, because the grade is the stronger statement."""
    kept = estimate.best_priced_rows([
        _row("GB-DIA-100", "C", 335, basis="SEED"),
        _row("GB-DIA-100-researched", "E", 185, basis="PROMOTED")])
    assert [r.base for r in kept] == [335]


def test_an_interpolation_loses_to_a_seed_it_ties_with():
    """An interpolated row inherits its anchors' grade, so it can tie with
    them. It is last because nobody ever chose its value."""
    kept = estimate.best_priced_rows([
        _row("GB-DIA-200", "C", 400, bw=200, basis="INTERPOLATED"),
        _row("GB-DIA-200-seeded", "C", 450, bw=200, basis="SEED")])
    assert [r.base for r in kept] == [450]


def test_a_researched_price_beats_the_seed_it_displaces():
    kept = estimate.best_priced_rows([
        _row("GB-DIA-100", "E", 335),
        _row("GB-DIA-100-researched", "C", 185)])
    assert [r.base for r in kept] == [185]


def test_the_order_the_query_returned_them_in_does_not_matter():
    """The defect was that it did."""
    rows = [_row("GB-DIA-100-researched", "C", 185), _row("GB-DIA-100", "E", 335)]
    assert estimate.best_priced_rows(rows)[0].base == 185
    assert estimate.best_priced_rows(list(reversed(rows)))[0].base == 185


def test_different_keys_are_all_kept():
    kept = estimate.best_priced_rows([
        _row("a", "E", 1, bw=100), _row("b", "E", 2, bw=500),
        _row("c", "E", 3, product="MPLS"), _row("d", "E", 4, country="US")])
    assert len(kept) == 4


@pytest.mark.parametrize("better,worse", [("A", "B"), ("B", "C"),
                                          ("C", "D"), ("D", "E"), ("E", "F")])
def test_every_grade_beats_the_one_below_it(better, worse):
    kept = estimate.best_priced_rows([_row("x", worse, 999),
                                      _row("y", better, 1)])
    assert kept[0].base == 1


def test_a_tie_is_broken_stably_rather_than_by_query_order():
    """Two rows of equal evidence is not a question this can answer, but
    giving a different answer on each run is strictly worse than giving the
    same one."""
    rows = [_row("zzz", "C", 2), _row("aaa", "C", 1)]
    assert estimate.best_priced_rows(rows)[0].id == "aaa"
    assert estimate.best_priced_rows(list(reversed(rows)))[0].id == "aaa"


def test_an_unknown_grade_loses_to_a_known_one():
    """A row whose grade nobody set should not outrank one somebody did."""
    kept = estimate.best_priced_rows([_row("x", None, 999),
                                      _row("y", "E", 1)])
    assert kept[0].base == 1
