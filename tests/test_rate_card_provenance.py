"""What the rate card knows about its own rows, and nearly threw away.

The card holds 1,397 rows. Six of them came from a UK leased-line market
survey and a published Virgin Media tariff, carrying grades C and B. The
seed converted them to USD and discarded everything else about them: the
builder bound the grade and the source to `_grade` and `_source` and
returned neither, then stamped every row grade E with a source line
reading "no transaction, quote or published benchmark behind it".

That sentence was true of 1,391 rows and false of the six. The card
understated its own evidence, in writing, and the understatement fed
`unsourced_price_share`, which caps confidence.
"""
import pytest

from app import seed


def test_the_sourced_rates_keep_their_grade():
    """The six rows with a source are not grade E."""
    assert seed.SOURCED_PROVENANCE, "no provenance carried at all"
    for key, (grade, source) in seed.SOURCED_PROVENANCE.items():
        assert grade and grade != "E", f"{key} graded {grade!r}"
        assert source and "no transaction" not in source, key


def test_the_uk_survey_rows_are_the_ones_carried():
    """GB DIA at 100 and 1000, GB Ethernet at 500, 1000 and 10000. Five
    keys from six source rows, because the Virgin Media tariff and the
    survey band describe the same circuit and merge."""
    assert set(seed.SOURCED_PROVENANCE) == {
        ("GB", "DIA", 100), ("GB", "DIA", 1000),
        ("GB", "ETHERNET", 500), ("GB", "ETHERNET", 1000),
        ("GB", "ETHERNET", 10000)}


def test_a_point_tariff_does_not_lend_its_grade_to_a_survey_band():
    """GB DIA 100 has both: a grade C survey band at 150-350 and a grade B
    Virgin Media entry price at 185. The tariff only moves the floor -
    base and high still come from the survey - so the row is worth what
    the survey is worth. Claiming B for a number the tariff did not set
    would be the overstatement this exercise keeps finding."""
    grade, source = seed.SOURCED_PROVENANCE[("GB", "DIA", 100)]
    assert grade == "C"
    assert "floor set by" in source, (
        "the tariff set the floor and the row should say so")


def test_every_other_row_is_still_an_assumption():
    """The point is not that the card is well sourced. 1,392 of 1,397 rows
    are an indicative starting position and must keep saying so."""
    keys = {(c, p, int(bw)) for c, p, l, bw, lo, ba, hi in seed.PRIORS}
    assert len(keys - set(seed.SOURCED_PROVENANCE)) > 1000


# ------------------------------------------- what --force may not delete

def test_the_seed_will_not_delete_rows_it_did_not_write():
    """`make seed` would have deleted every approved price.

    --force prunes any primary key the builder no longer produces, which
    is right for a threshold the code dropped. Promoted rates carry ids
    ending "-researched" and no builder emits those, so all ten approved
    prices read as stale - the documented operator command for applying a
    rate-card change would have deleted the entire output of the
    research-to-rate-card path and reported it as tidying.
    """
    from app import db

    assert "reference.unit_cost_prior" in seed.NOT_SEEDED
    guard = seed.NOT_SEEDED["reference.unit_cost_prior"]
    # The real column, compiled, so this breaks if price_basis is renamed
    # rather than passing against a stand-in that cannot know.
    clause = str(guard(db.unit_cost_prior).compile(
        compile_kwargs={"literal_binds": True}))
    assert "price_basis" in clause and "PROMOTED" in clause, clause


def test_a_builder_id_never_looks_like_a_promoted_one():
    """The guard is a safety net under a naming convention. If the seed
    ever emitted an id ending "-researched" the two would collide and the
    protection would be the only thing standing between an approved price
    and a delete."""
    for c, p, l, bw, lo, ba, hi in seed.PRIORS:
        assert not f"{c}-{p}-{bw}".endswith("-researched")
