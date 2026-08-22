from decimal import Decimal
from typing import Any

from prefect import flow, task

from network_cost_workbench.services.coverage import CoverageMetric, calculate_weighted_coverage
from network_cost_workbench.services.savings import calculate_savings


@task
def calculate_stage0_coverage(metrics: list[dict[str, str]]) -> str:
    result = calculate_weighted_coverage(
        [
            CoverageMetric(
                name=item["name"],
                numerator=Decimal(item["numerator"]),
                denominator=Decimal(item["denominator"]),
                weight=Decimal(item["weight"]),
            )
            for item in metrics
        ]
    )
    return str(result.score)


@task
def calculate_stage0_savings(current_tco: str, target_tco: str) -> dict[str, str | None]:
    result = calculate_savings(Decimal(current_tco), Decimal(target_tco))
    return {
        "current_tco": str(result.current_tco),
        "target_tco": str(result.target_tco),
        "savings": str(result.savings),
        "savings_rate_percent": None if result.savings_rate is None else str(result.savings_rate),
    }


@flow(name="stage0-outside-in")
def stage0_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the deterministic Stage 0 calculation path.

    Public research and LLM-assisted evidence gathering are intentionally separate child workflows.
    This first implementation proves the stage contract without fabricating an agent result.
    """
    coverage = calculate_stage0_coverage(payload["coverage_metrics"])
    savings = calculate_stage0_savings(payload["current_tco"], payload["target_tco"])
    return {"stage": "V0", "coverage_percent": coverage, "savings": savings}
