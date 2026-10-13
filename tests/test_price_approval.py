"""Admitting a researched price into the rate card.

`approved` gates five readers and decides whether a figure prices every
circuit at its tier in every case. It was a bare boolean defaulting to True,
with no route to set it and no record of who had: the system could propose a
price under governance and could not dispose of one.
"""
import types
from decimal import Decimal

import pytest

from app.domain import promotion


class _Session:
    def __init__(self, row):
        self.row, self.updated, self.committed = row, None, False

    def execute(self, stmt):
        if self.row is not None and getattr(stmt, "_values", None) is None:
            return types.SimpleNamespace(first=lambda: self.row)
        self.updated = stmt
        return types.SimpleNamespace(first=lambda: self.row)

    def commit(self):
        self.committed = True


def _row(base="1987.00"):
    return types.SimpleNamespace(
        id="US-DIA-10000-researched", country="US", product="DIA",
        bandwidth_mbps=10000, base=Decimal(base), low=Decimal(base),
        high=Decimal(base), evidence_grade="C")


def _approve(**kw):
    s = _Session(_row())
    kw.setdefault("approved_by", "a steward")
    return promotion.approve_price(s, row_id="US-DIA-10000-researched", **kw)


# ---------------------------------------------- the band is the point

def test_a_point_price_gains_the_cards_own_width():
    """`estimate.widen` spreads a band about its base by scaling the gap, so
    a zero-width range stays zero-width through every widening. An approved
    point price is immune to CR-06 evidence widening - a grade C single
    observation presented as exact, inside an outside-in estimate."""
    out = _approve()
    assert Decimal(out["low"]) == Decimal("1490.25")
    assert Decimal(out["high"]) == Decimal("2483.75")
    assert out["band_origin"] == "CARD_DEFAULT_WIDTH"


def test_the_inherited_width_is_the_one_the_card_already_asserts():
    """Not a judgement introduced at approval: measured off the card, where
    280 DIA rows, 89 MPLS and 356 Ethernet all sit at exactly this."""
    assert promotion.CARD_BAND_SHARE == Decimal("0.25")


def test_a_stated_band_is_used_as_given():
    out = _approve(low=Decimal("1800"), high=Decimal("2200"))
    assert Decimal(out["low"]) == 1800 and Decimal(out["high"]) == 2200
    assert out["band_origin"] == "STATED_ON_APPROVAL"


def test_a_zero_width_band_is_reachable_but_has_to_be_asked_for():
    """Refusing it outright would be the system overruling a person who has
    a reason. It just cannot be the default."""
    out = _approve(low=Decimal("1987.00"), high=Decimal("1987.00"))
    assert Decimal(out["low"]) == Decimal(out["high"]) == Decimal("1987")
    assert out["band_origin"] == "STATED_ON_APPROVAL"


def test_a_band_that_does_not_contain_the_price_is_refused():
    """A band states uncertainty about a number. One that excludes the
    observation is moving the number under another name."""
    with pytest.raises(promotion.NotPromotable) as e:
        _approve(low=Decimal("2100"), high=Decimal("2200"))
    assert "does not contain" in str(e.value)


# ------------------------------------------------------- attribution

def test_approval_must_be_attributed():
    with pytest.raises(promotion.NotPromotable) as e:
        _approve(approved_by="")
    assert "named person" in str(e.value)


def test_an_unknown_row_is_refused():
    s = _Session(None)
    with pytest.raises(promotion.NotPromotable):
        promotion.approve_price(s, row_id="nope", approved_by="a steward")


def test_the_table_can_record_who_approved():
    from app import db
    cols = [c.name for c in db.unit_cost_prior.c]
    assert "approved_by" in cols and "approved_at" in cols


def test_the_result_says_what_approval_means():
    assert "every case" in _approve()["note"]
