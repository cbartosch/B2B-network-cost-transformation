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


def _row(id, grade, base, country="GB", product="DIA", bw=100):
    return types.SimpleNamespace(id=id, country=country, product=product,
                                 bandwidth_mbps=bw, evidence_grade=grade,
                                 base=base)


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
