"""Every industry reaches a published benchmark.

The dropdown has offered 47 BICS codes since 4.220.0, and 24 of the 27 older
workbench codes have no benchmark row of their own. A case created before that
load - DHL on PARCEL_LOGISTICS, for instance - therefore got no bandwidth, no
committed share, no dual access and no criticality from the benchmark at all.
It fell back to this repository's seeded defaults without saying so.

Mapped rather than filled in. Writing 24 new benchmark rows would be 24 new
assumptions; pointing at an existing row reuses supplied data and a reader can
check whether the mapping is reasonable.
"""
from pathlib import Path


def _codes():
    from app.domain import industries
    return {row[0] for row in industries.INDUSTRIES} - {"DEFAULT"}


def _benchmarked():
    from app.domain import industry_benchmark
    return {r["industry_code"] for r in industry_benchmark.seeded()["rows"]}


def test_every_industry_resolves_to_a_benchmark():
    """The point of the whole change. No selectable industry may fall back to
    a seeded default without a benchmark behind it."""
    from app.domain import bics

    unresolved = sorted(c for c in _codes()
                        if bics.benchmark_code(c) is None)
    assert not unresolved, unresolved


def test_no_mapping_points_at_a_row_that_does_not_exist():
    """A mapping to a missing code is worse than no mapping: it looks
    resolved and silently is not."""
    from app.domain import bics

    benchmarked = _benchmarked()
    broken = sorted(c for c in _codes()
                    if bics.benchmark_code(c) not in benchmarked)
    assert not broken, broken


def test_a_bics_code_answers_for_itself():
    """The mapping must not redirect a code that already has a row."""
    from app.domain import bics

    for code in _benchmarked():
        assert bics.benchmark_code(code) == code, code


def test_every_mapped_target_carries_bandwidth_and_resilience():
    """Resolving to a benchmark row is not enough - the row's industry has to
    have archetype bandwidth and resilience keyed against it, or the posture
    still falls back to the archetype default."""
    from app.domain import bics
    from app.seed import ARCHETYPE_BANDWIDTH, _archetype_resilience

    with_bandwidth = {i for i, _a, _m in ARCHETYPE_BANDWIDTH}
    with_resilience = {i for i, _a, _d, _c, _t in _archetype_resilience()}
    for code in sorted(_codes()):
        target = bics.benchmark_code(code)
        assert target in with_bandwidth, f"{code} -> {target}: no bandwidth"
        assert target in with_resilience, f"{code} -> {target}: no resilience"


def test_a_broad_mapping_says_that_it_is_broad():
    """"Manufacturing" priced as a diversified industrial is a choice worth
    seeing, not a silent substitution."""
    from app.domain import bics

    for code in ("MANUFACTURING", "RETAIL", "FINANCIAL_SERVICES",
                 "GOVERNMENT", "PUBLIC_SAFETY"):
        assert code in bics.LEGACY_MAPPING_IS_BROAD, code
        assert bics.LEGACY_MAPPING_IS_BROAD[code].strip()


def test_both_lookups_use_the_mapping():
    """Bandwidth and resilience are read in two separate queries. Mapping one
    and not the other would leave half the posture on the default."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()

    assert "_bench_code = bics.benchmark_code(_industry)" in api
    assert "db.industry_benchmark.c.industry_code == _bench_code" in api
    assert "db.archetype_resilience.c.industry == _bench_code" in api
