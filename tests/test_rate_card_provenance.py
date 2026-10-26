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
    """GB DIA at 100, 500, 1000 and 10000, GB Ethernet at 500, 1000 and
    10000. Seven keys from eight source rows, because the Virgin Media tariff
    and the survey band describe the same circuit and merge."""
    assert {k for k in seed.SOURCED_PROVENANCE if k[0] == "GB"} == {
        ("GB", "DIA", 100), ("GB", "DIA", 500), ("GB", "DIA", 1000),
        ("GB", "DIA", 10000), ("GB", "ETHERNET", 500),
        ("GB", "ETHERNET", 1000), ("GB", "ETHERNET", 10000)}


def test_uk_dia_reaches_10_gbps_at_the_surveys_band():
    """DIA stopped at 1 Gbps, so the 10 Gbps DIA backups beside urban 10 Gbps
    sites went unpriced once those sites were no longer cut to 1 Gbps. The
    survey's 10 Gbps band prices them, as its 500 Mbps band does, and the
    steps between 1 and 10 Gbps are interpolated on it."""
    from decimal import Decimal as D

    grade, source = seed.SOURCED_PROVENANCE[("GB", "DIA", 10000)]
    assert grade == "C" and "Purple" in source
    fx = D(seed.SOURCED_FX["GBP"])
    _c, _p, _l, _bw, low, base, high = _row("GB", "DIA", 10000)
    assert (low, base, high) == (int(800 * fx), int((800 + 3500) * fx / 2),
                                 int(3500 * fx))
    assert ("GB", "DIA", 5000) in seed._DERIVED_TIER_KEYS


def _row(country, product, mbps):
    return next(r for r in seed.PRIORS
                if (r[0], r[1], int(r[3])) == (country, product, mbps))


def test_uk_dia_500_prices_at_the_surveys_band_not_its_seed():
    """GB DIA 500 was a seed at GBP 515, unsourced and at the top of every
    2026 figure for the circuit. It takes the survey's 500 Mbps band, the one
    the card already prices Ethernet at, with the sellers' prices it was
    checked against named on the row."""
    from decimal import Decimal as D

    grade, source = seed.SOURCED_PROVENANCE[("GB", "DIA", 500)]
    assert grade == "C"
    assert "Vodafone" in source and "Virgin Media" in source
    fx = D(seed.SOURCED_FX["GBP"])
    _c, _p, _l, _bw, low, base, high = _row("GB", "DIA", 500)
    assert (low, base, high) == (int(250 * fx), int((250 + 600) * fx / 2),
                                 int(600 * fx))


def test_australia_prices_dedicated_internet_at_what_its_sellers_publish():
    """Australia's DIA seeds ran AUD 2,072 to 2,590 from 300 Mbps up - 3.7 to
    5 times the 36-month prices Vocus and Swoop publish for dedicated
    business internet. 500 Mbps and 1 Gbps take those prices, graded C, and
    convert back to the Australian dollars they were quoted in."""
    from decimal import Decimal as D

    usd_to_aud = D("1.48")              # the card's own USD->AUD row
    for mbps, low, high in ((500, 469, 499), (1000, 699, 1499)):
        grade, source = seed.SOURCED_PROVENANCE[("AU", "DIA", mbps)]
        assert grade == "C" and "retail" in source
        _c, _p, _l, _bw, lo, base, hi = _row("AU", "DIA", mbps)
        assert abs(D(lo) * usd_to_aud - low) < 2, (mbps, lo)
        assert abs(D(hi) * usd_to_aud - high) < 2, (mbps, hi)
        assert abs(D(base) * usd_to_aud - D(low + high) / 2) < 2, (mbps, base)


def _seeded(country, product, mbps):
    return next(r for r in seed._SEEDED_ROWS
                if (r[0], r[1], int(r[3])) == (country, product, mbps))


def test_a_tier_with_nothing_sourced_below_keeps_the_seeds_step():
    """Sourcing AU DIA at 500 left the 300 Mbps seed at AUD 2,072 over a 500
    Mbps rate of about 484, with nothing sourced beneath it to interpolate
    from. It keeps the step the seeded card took between the two, applied to
    the sourced 500 Mbps band, so a smaller circuit is never priced above a
    larger one."""
    from decimal import Decimal as D

    step = D(_seeded("AU", "DIA", 300)[5]) / D(_seeded("AU", "DIA", 500)[5])
    _c, _p, _l, _bw, lo3, base3, hi3 = _row("AU", "DIA", 300)
    _c, _p, _l, _bw, lo5, base5, hi5 = _row("AU", "DIA", 500)
    assert base3 < base5
    assert abs(D(lo3) - D(lo5) * step) < 2 and abs(D(hi3) - D(hi5) * step) < 2


def test_a_filled_tier_is_scaled_from_the_seeded_curve():
    """Australia's Ethernet 10 Gbps is filled from its DIA 500 - 3.8 times it,
    a step measured between seeded tiers. Scaled from the sourced DIA 500, a
    fifth of the seed, it fell below Australia's own Ethernet gigabit."""
    from decimal import Decimal as D

    filled = _row("AU", "ETHERNET", 10000)[5]
    assert filled == int(D(_seeded("AU", "DIA", 500)[5]) * D("3.80"))
    assert filled > _row("AU", "ETHERNET", 1000)[5]


def test_a_point_on_a_sourced_tier_does_not_narrow_the_tiers_between():
    """The tiers between two sourced ones are drawn from their bands. Read
    row by row, Virgin Media's 185 entry price replaced the survey's 150-350
    band at 100 Mbps, and GB DIA 300 would have been drawn from one seller's
    cheapest tariff as though it were the market. It is drawn from the band
    the card prices 100 Mbps at."""
    import math
    from decimal import Decimal as D

    fx = D(seed.SOURCED_FX["GBP"])
    position = D(str(math.log(300 / 100) / math.log(500 / 100)))
    expected_low = int(150 * fx * ((250 * fx) / (150 * fx)) ** position)
    expected_high = int(350 * fx * ((600 * fx) / (350 * fx)) ** position)
    _c, _p, _l, _bw, low, _base, high = _row("GB", "DIA", 300)
    assert (low, high) == (expected_low, expected_high)


def test_spain_prices_a_100_mbps_circuit_at_its_market_not_its_300_seed():
    """Spain had no DIA tier below 300 Mbps, so 2,072 circuits needing 100
    priced at the 300 Mbps seed of EUR 906 - three to four times the range a
    Spanish comparison site gives for dedicated fibre. The range enters at
    grade D, its midpoint converting back to the EUR 250 it was quoted at."""
    from decimal import Decimal as D

    grade, source = seed.SOURCED_PROVENANCE[("ES", "DIA", 100)]
    assert grade == "D"
    assert "Kompara" in source and "dedicated" in source
    row = next(r for r in seed.PRIORS
               if (r[0], r[1], int(r[3])) == ("ES", "DIA", 100))
    usd_to_eur = D("0.8711")          # the card's own USD->EUR row
    assert abs(D(row[5]) * usd_to_eur - 250) < 1, row
    # The 300 Mbps seed it no longer stands in for is untouched: one sourced
    # tier has nothing to reprice between.
    seeded = next(r for r in seed.PRIORS
                  if (r[0], r[1], int(r[3])) == ("ES", "DIA", 300))
    assert int(seeded[5]) == 1040


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


# ------------------------------------------- a regional row says whose it is
@pytest.fixture(scope="module")
def card():
    from app import db
    builder = next(b for t, b in seed._rows() if t is db.unit_cost_prior)
    return {r["id"]: r for r in builder()}


def test_a_regional_row_names_the_countries_its_rate_came_from(card):
    """Every regional row read "no transaction, quote or published benchmark
    behind it" - Western Europe's 10 Gbps DIA too, which is the UK survey
    band carried for the region. It names its members now, counts them, and
    stays grade E: a UK price used for Germany is a starting point for
    research there, not evidence about it."""
    one = card["EUROPE_WEST-DIA-10000"]
    assert one["sample_size"] == 1 and one["evidence_grade"] == "E"
    assert "the rate of GB" in one["source"]
    assert "UK leased line market survey" in one["source"]

    many = card["EMEA-DIA-100"]
    assert many["sample_size"] > 1 and many["evidence_grade"] == "E"
    assert f"median of the {many['sample_size']} member" in many["source"]
    assert "ES (grade D" in many["source"] and "GB (grade C" in many["source"]
    assert "no transaction" not in many["source"]


def test_a_regional_tier_put_on_the_regions_curve_says_so(card):
    row = card["EUROPE_WEST-DIA-2000"]
    assert "interpolated between this region's own" in row["source"]
    assert row["sample_size"] is None


def test_a_backbone_row_is_not_dressed_as_a_median(card):
    """The backbone 10 Gbps Ethernet rows are seeded positions the regional
    derivation leaves alone, and their source keeps saying so."""
    row = card["EMEA-ETHERNET-10000"]
    assert row["sample_size"] is None
    assert row["source"].startswith("indicative starting position")


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
