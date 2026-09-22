"""The archetype vocabulary, and whether the industry model differentiates.

The benchmark names 37 site types and the simulation could generate six, so
`density_mix_rows` copied the estate shape and dropped the name. Every industry
sharing a shape produced an identical estate: fourteen plant-centric industries
priced the same, and chemicals, semiconductors and household products returned
byte-identical baselines.

Grouped by network character rather than industry vocabulary, because that is
what decides the circuit. The same benchmark name appears at different
bandwidths across industries - MANUFACTURING_PLANT at 10.5 Gbps and at 1.1 -
which is the proof that the name is not the requirement.
"""
from collections import defaultdict


def test_every_benchmark_archetype_maps_to_a_generatable_one():
    """An unmapped name is a site type the estate can never contain, which is
    how 43 of 47 benchmarks came to be inert."""
    from app.domain import bics, industry_benchmark

    names = {r["archetype_code"]
             for r in industry_benchmark.seeded()["rows"]}
    unmapped = sorted(n for n in names
                      if bics.canonical_archetype(n) is None)
    assert not unmapped, unmapped


def test_every_canonical_archetype_can_actually_be_built():
    """A mapping target with no prior is unpriceable scope."""
    from app.domain import bics
    from app.seed import ARCHETYPES

    buildable = {row[0] for row in ARCHETYPES}
    targets = set(bics.ARCHETYPE_OF_BENCHMARK.values())
    assert targets <= buildable, sorted(targets - buildable)


def test_the_five_new_types_exist_with_their_own_character():
    """Each was added because its network character differs from anything
    already generatable - not to give the vocabulary more words."""
    from app.seed import ARCHETYPES

    priors = {row[0]: row for row in ARCHETYPES}
    for name in ("PLANT", "REMOTE_SITE", "CONTROL_CENTER", "NETWORK_SITE",
                 "TERMINAL"):
        assert name in priors, name

    # a remote extraction site has no fixed line, so its primary is wireless
    assert priors["REMOTE_SITE"][4] == "MOBILE_5G"
    # an unmanned tower has no users at all
    assert priors["NETWORK_SITE"][1] == 0
    # a control room is the site whose loss stops the business
    assert priors["CONTROL_CENTER"][3] == "1.00"
    assert priors["CONTROL_CENTER"][6] == "1.00"
    # a plant at multi-gigabit buys Ethernet; DIA is quoted only to 1 Gbps,
    # and a DIA primary made every large plant unpriced scope
    assert priors["PLANT"][4] == "ETHERNET"


def test_industries_sharing_a_shape_no_longer_share_an_estate():
    """The defect this whole change exists for. All six shapes previously
    resolved to exactly one archetype mix each."""
    from app.domain import bics
    from app.seed import DENSITY_MIX

    mix = defaultdict(set)
    for industry, archetype, _band, _share in DENSITY_MIX:
        mix[industry].add(archetype)

    by_shape = defaultdict(set)
    for industry in mix:
        if industry in bics.SHAPE_OF_BICS:
            by_shape[bics.shape_for(industry)].add(
                tuple(sorted(mix[industry])))

    # plant-centric holds 14 industries and network-centric 12; each must now
    # carry more than one estate
    for shape in ("plant-centric", "network-centric", "few-large"):
        assert len(by_shape[shape]) > 1, (
            f"{shape} still resolves to one estate for every industry in it")


def test_each_industry_leads_with_its_own_representative_site():
    """The benchmark says which operating site an industry is built around,
    and that is the part the mix used to throw away."""
    from app.domain import bics
    from app.seed import DENSITY_MIX, INDUSTRY_BENCHMARK

    mix = defaultdict(set)
    for industry, archetype, _band, _share in DENSITY_MIX:
        mix[industry].add(archetype)

    for industry, expected in (("DIVERSIFIED_MINING", "REMOTE_SITE"),
                               ("UTILITIES", "CONTROL_CENTER"),
                               ("TOWER_COMPANY", "NETWORK_SITE"),
                               ("PORT", "TERMINAL"),
                               ("CHEMICALS", "PLANT")):
        assert expected in mix[industry], (industry, sorted(mix[industry]))


def test_every_mix_still_sums_to_one():
    """Substitution must not touch the shares. They are the one thing here
    that is neither supplied nor derivable."""
    from decimal import Decimal

    from app.seed import DENSITY_MIX

    totals = defaultdict(Decimal)
    for industry, _archetype, _band, share in DENSITY_MIX:
        totals[industry] += Decimal(share)
    wrong = {i: str(t) for i, t in totals.items() if t != Decimal("1.0000")}
    assert not wrong, wrong


def test_every_archetype_in_a_mix_has_a_fallback_bandwidth():
    """Four guards reported unpriceable scope the moment the vocabulary grew.
    A new site type needs a figure in every shape or the industries holding it
    cannot price."""
    from app.domain import industries
    from app.seed import DENSITY_MIX

    in_mix = {archetype for _i, archetype, _b, _s in DENSITY_MIX}
    for shape, table in industries.SHAPE_BANDWIDTH.items():
        missing = sorted(in_mix - set(table))
        assert not missing, (shape, missing)
