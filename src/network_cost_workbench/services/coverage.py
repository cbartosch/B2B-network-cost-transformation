from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CoverageMetric:
    name: str
    numerator: Decimal
    denominator: Decimal
    weight: Decimal

    @property
    def ratio(self) -> Decimal:
        if self.denominator <= 0:
            return Decimal("0")
        value = self.numerator / self.denominator
        return min(max(value, Decimal("0")), Decimal("1"))


@dataclass(frozen=True, slots=True)
class CoverageResult:
    score: Decimal
    metrics: tuple[CoverageMetric, ...]


def calculate_weighted_coverage(metrics: list[CoverageMetric]) -> CoverageResult:
    if not metrics:
        raise ValueError("at least one coverage metric is required")
    total_weight = sum((metric.weight for metric in metrics), Decimal("0"))
    if total_weight <= 0:
        raise ValueError("coverage weights must sum to a positive value")
    weighted = sum((metric.ratio * metric.weight for metric in metrics), Decimal("0"))
    score = (weighted / total_weight) * Decimal("100")
    return CoverageResult(score=score.quantize(Decimal("0.01")), metrics=tuple(metrics))


def rank_material_gap(
    annual_spend: Decimal,
    uncertainty: Decimal,
    criticality: Decimal,
) -> Decimal:
    """Return a deterministic, unbounded materiality priority score.

    Inputs use non-negative values; uncertainty and criticality are normally in [0, 1].
    """
    if min(annual_spend, uncertainty, criticality) < 0:
        raise ValueError("materiality inputs must be non-negative")
    return (annual_spend * uncertainty * criticality).quantize(Decimal("0.01"))
