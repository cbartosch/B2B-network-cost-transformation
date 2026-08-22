from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from network_cost_workbench import __version__
from network_cost_workbench.domain.enums import EvidenceClass, StageVersion
from network_cost_workbench.domain.stage_policy import allowed_evidence
from network_cost_workbench.services.coverage import CoverageMetric, calculate_weighted_coverage
from network_cost_workbench.services.savings import calculate_savings

app = FastAPI(title="Network Cost Transformation Workbench", version=__version__)


class SavingsRequest(BaseModel):
    current_tco: Decimal = Field(ge=0)
    target_tco: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)


class CoverageMetricRequest(BaseModel):
    name: str
    numerator: Decimal = Field(ge=0)
    denominator: Decimal = Field(ge=0)
    weight: Decimal = Field(gt=0)


class CoverageRequest(BaseModel):
    metrics: list[CoverageMetricRequest] = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/stages")
def stages() -> list[dict[str, object]]:
    return [
        {
            "stage": stage.value,
            "allowed_evidence": sorted(item.value for item in allowed_evidence(stage)),
        }
        for stage in StageVersion
    ]


@app.post("/v1/calculations/savings")
def savings(request: SavingsRequest) -> dict[str, object]:
    result = calculate_savings(request.current_tco, request.target_tco)
    return {
        "currency": request.currency.upper(),
        "current_tco": str(result.current_tco),
        "target_tco": str(result.target_tco),
        "savings": str(result.savings),
        "savings_rate_percent": None if result.savings_rate is None else str(result.savings_rate),
    }


@app.post("/v1/calculations/coverage")
def coverage(request: CoverageRequest) -> dict[str, object]:
    try:
        result = calculate_weighted_coverage(
            [
                CoverageMetric(
                    name=item.name,
                    numerator=item.numerator,
                    denominator=item.denominator,
                    weight=item.weight,
                )
                for item in request.metrics
            ]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "score_percent": str(result.score),
        "metrics": [
            {"name": metric.name, "ratio": str(metric.ratio), "weight": str(metric.weight)}
            for metric in result.metrics
        ],
    }


@app.get("/v1/evidence-classes")
def evidence_classes() -> list[str]:
    return [item.value for item in EvidenceClass]
