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
    and the survey band describe the same circuit and merge. (EE's business
    5G, sourced since, is another source and not the survey's.)"""
    assert {k for k in seed.SOURCED_PROVENANCE
            if k[0] == "GB" and k[1] != "MOBILE_5G"} == {
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
    # The 300 Mbps seed of EUR 906 sat above the same page's 500 Mbps range
    # once that was sourced too, so it is placed between the two now and its
    # source names both.
    between = next(r for r in seed.PRIORS
                   if (r[0], r[1], int(r[3])) == ("ES", "DIA", 300))
    hundred, five_hundred = (_row("ES", "DIA", bw)[5] for bw in (100, 500))
    assert hundred < int(between[5]) < five_hundred
    assert seed.SOURCED_DERIVED[("ES", "DIA", 300)][:2] == (
        "between", (100, 500))


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


def test_australia_prices_5g_at_telstras_business_plans():
    """Australia had no 5G rate of its own and priced 5G at APAC's, which was
    Singapore's seed alone. Telstra publishes its business 5G plans; each
    band runs from the ex-GST figure to the listed price, because the page
    does not say which it is, and converts back to Australian dollars."""
    from decimal import Decimal as D

    usd_to_aud = D("1.48")
    for mbps, low, high in ((50, D("72.73"), 80), (300, D("86.36"), 95)):
        grade, source = seed.SOURCED_PROVENANCE[("AU", "MOBILE_5G", mbps)]
        assert grade == "B" and "Telstra" in source and "GST" in source
        _c, _p, _l, _bw, lo, base, hi = _row("AU", "MOBILE_5G", mbps)
        assert abs(D(lo) * usd_to_aud - low) < 2, (mbps, lo)
        assert abs(D(hi) * usd_to_aud - high) < 2, (mbps, hi)


def test_singapore_prices_5g_at_its_operators_business_plans():
    """Singapore's 5G was a seed at about SGD 79 a month, and DBS's 1,100
    ATMs take it for their primary access. StarHub, M1 and Singtel publish
    business plans with 5G at SGD 15.00 to 45.42; the band runs from the
    cheapest to the dearest and converts back to Singapore dollars."""
    from decimal import Decimal as D

    usd_to_sgd = D("1.28")
    grade, source = seed.SOURCED_PROVENANCE[("SG", "MOBILE_5G", 50)]
    assert grade == "C"
    assert all(seller in source for seller in ("StarHub", "M1", "Singtel"))
    _c, _p, _l, _bw, lo, base, hi = _row("SG", "MOBILE_5G", 50)
    assert abs(D(lo) * usd_to_sgd - D("15.00")) < 2, lo
    assert abs(D(hi) * usd_to_sgd - D("45.42")) < 2, hi


def test_no_5g_tier_is_extrapolated_under_one_already_quoted():
    """The 100 Mbps 5G fill scales a country's 50 by 1.55. Scaled from
    Telstra's 50, it sat above Telstra's own 300; a 100 Mbps need takes the
    300 instead."""
    assert not any((r[0], r[1], int(r[3])) == ("AU", "MOBILE_5G", 100)
                   for r in seed.PRIORS)


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


def test_a_regional_tier_above_the_tier_above_it_is_placed_between_them(
        monkeypatch):
    """APAC's 100 Mbps 5G rested on Singapore's seed alone, at USD 96 above
    the 300 Mbps rate of 61 Australia's Telstra plans gave the region.
    Singapore's 5G is sourced now and the card holds no such tier, so the
    rule is checked on that case as it stood."""
    key = ("APAC", "MOBILE_5G", 100)
    monkeypatch.setattr(seed, "REGIONAL_MEMBERS", {key: ["SG"]})
    monkeypatch.setattr(seed, "REGIONAL_RECURVED", {})
    rows = seed._regional_monotone([
        ("APAC", "MOBILE_5G", "L0", 50, 42, 56, 79),
        ("APAC", "MOBILE_5G", "L0", 100, 54, 96, 162),
        ("APAC", "MOBILE_5G", "L0", 300, 58, 61, 64)])
    fifty, hundred, three_hundred = (row[5] for row in rows)
    assert fifty < hundred < three_hundred
    assert seed.REGIONAL_RECURVED == {key: (50, 300)}
    assert key not in seed.REGIONAL_MEMBERS
    assert "between this region's own 50 Mbps and 300 Mbps" in (
        seed._regional_source(key))


def test_a_backbone_row_is_not_dressed_as_a_median(card):
    """The backbone 10 Gbps Ethernet rows are seeded positions the regional
    derivation leaves alone, and their source keeps saying so."""
    row = card["EMEA-ETHERNET-10000"]
    assert row["sample_size"] is None
    assert row["source"].startswith("indicative starting position")


# ------------------------------------ a row a sourced rate sets says so
def test_a_tier_between_two_sourced_rows_names_them(card):
    """UK DIA 300 sits between the survey's 100 and 500 Mbps bands and read
    as a seeded position with nothing behind it. It names both now, and
    stays grade E: an interpolation is no quote for its own tier."""
    row = card["GB-DIA-300"]
    assert row["evidence_grade"] == "E"
    assert ("interpolated between this country's sourced 100 Mbps and "
            "500 Mbps rows") in row["source"]
    assert "UK leased line market survey" in row["source"]
    assert "no transaction" not in row["source"]


def test_a_tier_scaled_from_one_sourced_row_names_it(card):
    """Australia's DIA 300 has nothing sourced beneath it, so it takes the
    sourced 500 Mbps band at the seeded card's step; Singapore's 5G 100 is
    its sourced 50 scaled by the 5G fill. Both read as seeded positions."""
    for key, tier, seller in (("AU-DIA-300", "500 Mbps band", "Vocus"),
                              ("SG-MOBILE_5G-100", "50 Mbps row", "StarHub")):
        row = card[key]
        assert row["evidence_grade"] == "E", key
        assert f"this country's sourced {tier}" in row["source"], key
        assert seller in row["source"], key
        assert "no transaction" not in row["source"], key


def test_a_row_scaled_from_a_seed_is_still_a_seed(card):
    """The 5G fill scales every country's 50. Where the 50 is a seed, so is
    the 100, and it keeps saying so - the UAE's, since the US quotes its own
    5G at 100 Mbps."""
    assert card["AE-MOBILE_5G-100"]["source"].startswith(
        "indicative starting position")


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


# ------------------------------------------- business 5G above 100 Mbps
@pytest.mark.parametrize("country,mbps,seller", [
    ("US", 100, "Verizon"), ("US", 300, "T-Mobile"), ("GB", 150, "EE"),
    ("FR", 300, "Orange Pro"), ("DE", 300, "Telekom"), ("ES", 150, "Orange"),
    ("ES", 300, "Vodafone"), ("BE", 300, "Proximus"), ("NL", 300, "Odido"),
    ("PL", 300, "T-Mobile"), ("RO", 300, "Orange")])
def test_business_5g_above_100_mbps_is_priced_from_the_operators_own_pages(
        country, mbps, seller):
    """The card sold 5G at 50 and 100 Mbps only, so 14,580 best-effort backups
    asking for 110 or 275 Mbps were bought at 100. Each tier is a business
    plan on its operator's page, at the speed the page states."""
    grade, source = seed.SOURCED_PROVENANCE[(country, "MOBILE_5G", mbps)]
    assert grade in ("B", "C") and seller in source, source
    assert "retail" in source.lower()


def test_no_tier_costs_as_much_as_a_faster_one_in_its_scope():
    """A faster plan for the same money or less is the one a buyer takes. The
    UK's seeded 50 Mbps 5G at USD 45 sat above EE's 150 Mbps plans at GBP
    22-28, so it is not sold; a 50 Mbps need prices at the 150."""
    tiers = {}
    for c, p, _l, bw, _lo, base, _hi in seed.PRIORS:
        tiers.setdefault((c, p), {})[int(bw)] = float(base)
    for key, by_bw in tiers.items():
        ordered = [by_bw[bw] for bw in sorted(by_bw)]
        assert all(a < b for a, b in zip(ordered, ordered[1:])), (key, by_bw)
    assert ("GB", "MOBILE_5G", 50) in seed.DROPPED_FOR_FASTER
    assert not any((r[0], r[1], int(r[3])) == ("GB", "MOBILE_5G", 50)
                   for r in seed.PRIORS)


# ------------------------------------------- business fibre, Spain and Italy
@pytest.mark.parametrize("country,mbps,seller", [
    ("ES", 300, "Telefonica"), ("ES", 600, "Telefonica"),
    ("ES", 1000, "Telefonica"), ("ES", 2000, "Telefonica"),
    ("ES", 10000, "Telefonica"), ("IT", 1000, "Ehiweb"),
    ("IT", 2500, "TIM"), ("IT", 10000, "TIM")])
def test_business_fibre_is_priced_from_the_sellers_own_plans(
        country, mbps, seller):
    """Fibre broadband stopped at 1 Gbps, so the 2,750 Mbps backups at
    Nestle's and Danone's rural plants in Spain and Italy were bought at 1
    Gbps, below their primary. Both markets publish business plans up to 10
    Gbps; each tier is one of them, at the speed it is sold."""
    grade, source = seed.SOURCED_PROVENANCE[(country, "BROADBAND_PON", mbps)]
    assert grade == "C" and seller in source, source
    assert "retail" in source.lower()


def test_a_fibre_need_buys_the_plan_that_fits_it():
    """The workbook's Southern Europe cluster seeded Spain's and Italy's
    fibre at USD 65-110 from 100 to 500 Mbps, above Telefonica's 300 Mb at
    EUR 34.71 and Ehiweb's 1 Giga at 34.95. Those tiers are not sold: a 100
    Mbps need buys the 300 Mb plan in Spain and the 1 Giga in Italy, and a
    500 Mbps one the 600 Mb in Spain."""
    sold = {}
    for c, p, _l, bw, *_r in seed.PRIORS:
        if p == "BROADBAND_PON" and c in ("ES", "IT"):
            sold.setdefault(c, set()).add(int(bw))
    assert sold == {"ES": {300, 600, 1000, 2000, 10000},
                    "IT": {1000, 2500, 10000}}, sold
    dropped = seed.DROPPED_FOR_FASTER
    assert dropped[("ES", "BROADBAND_PON", 100)] == 300
    assert dropped[("ES", "BROADBAND_PON", 500)] == 600
    assert dropped[("IT", "BROADBAND_PON", 100)] == 1000


def test_no_plan_is_drawn_between_two_others():
    """Fibre broadband and 5G are sold as plans. A 3 Gbps step between
    Italy's 2.5 and 10 Giga, or a 500 Mbps one between Telefonica's 300 and
    600 Mb, is no plan anyone sells; the 2-9 Gbps steps describe Ethernet
    and DIA, which are sold at the speed ordered."""
    plans = seed._PLAN_PRODUCTS
    assert not [k for k in seed._DERIVED_TIER_KEYS if k[1] in plans]
    assert not [k for k, (how, *_r) in seed.SOURCED_DERIVED.items()
                if k[1] in plans and how in ("between", "below")]


def test_a_region_is_not_priced_at_a_minoritys_plans(card):
    """Southern Europe prices fibre from 100 Mbps to 1 Gbps across six to
    eight members, and Spain's and Italy's plans alone price 300 and 600
    Mbps and 2, 2.5 and 10 Gbps - below those tiers' bands. They stay
    Spain's and Italy's. The region keeps what most of its members price,
    and its gigabit median takes both countries' published plans in."""
    tiers = {int(r[3]) for r in seed.PRIORS
             if (r[0], r[1]) == ("EUROPE_SOUTH", "BROADBAND_PON")}
    assert tiers == {100, 250, 500, 1000}, tiers
    for region in ("EUROPE_SOUTH", "EMEA"):
        for bw in (300, 600, 2000, 2500, 10000):
            assert (region, "BROADBAND_PON", bw) in seed.REGIONAL_MINORITY
    gigabit = card["EUROPE_SOUTH-BROADBAND_PON-1000"]
    assert gigabit["sample_size"] == 8
    assert "ES (grade C" in gigabit["source"]
    assert "IT (grade C" in gigabit["source"]


def test_a_minoritys_plan_under_a_majoritys_band_leaves_the_region(
        monkeypatch):
    """The rule on its own: two of eight members sell 10 Gbps for less than
    the band all eight give 1 Gbps."""
    monkeypatch.setattr(seed, "REGIONAL_MEMBERS", {
        ("R", "BROADBAND_PON", 1000): list("ABCDEFGH"),
        ("R", "BROADBAND_PON", 10000): ["A", "B"]})
    monkeypatch.setattr(seed, "REGIONAL_MINORITY", {})
    rows = seed._drop_minority_plans([
        ("R", "BROADBAND_PON", "L0", 1000, 94, 126, 157),
        ("R", "BROADBAND_PON", "L0", 10000, 46, 56, 70)])
    assert [int(r[3]) for r in rows] == [1000]
    assert seed.REGIONAL_MINORITY == {("R", "BROADBAND_PON", 10000): 1000}
    assert ("R", "BROADBAND_PON", 10000) not in seed.REGIONAL_MEMBERS


def test_a_regional_spread_or_a_split_vote_is_left_to_the_rules_after():
    """Singapore's 100 Mbps 5G sits inside the band Australia and Singapore
    give 50 Mbps, and Western Europe's 50 rests on two of its four 5G
    markets against the UK's 150 on one. Neither is a minority's plan under
    a majority's band, so both are decided as they were: the 50 rescaled
    under Singapore's 100, and Western Europe's 50 dropped for the UK's
    150."""
    assert not [k for k in seed.REGIONAL_MINORITY if k[1] == "MOBILE_5G"]
    assert any((r[0], r[1], int(r[3])) == ("APAC", "MOBILE_5G", 100)
               for r in seed.PRIORS)
    assert seed.DROPPED_FOR_FASTER[("EUROPE_WEST", "MOBILE_5G", 50)] == 150
