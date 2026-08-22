from decimal import Decimal

from network_cost_workbench.services.coverage import (
    CoverageMetric,
    calculate_weighted_coverage,
    rank_material_gap,
)


def test_weighted_coverage() -> None:
    result = calculate_weighted_coverage(
        [
            CoverageMetric("spend", Decimal("80"), Decimal("100"), Decimal("3")),
            CoverageMetric("contracts", Decimal("50"), Decimal("100"), Decimal("1")),
        ]
    )
    assert result.score == Decimal("72.50")


def test_material_gap_ranking() -> None:
    score = rank_material_gap(Decimal("1000000"), Decimal("0.5"), Decimal("0.8"))
    assert score == Decimal("400000.00")
