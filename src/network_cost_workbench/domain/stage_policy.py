from collections.abc import Iterable

from network_cost_workbench.domain.enums import EvidenceClass, StageVersion


class StagePolicyError(ValueError):
    """Raised when evidence is consumed before its permitted stage."""


_STAGE_ALLOWED: dict[StageVersion, frozenset[EvidenceClass]] = {
    StageVersion.V0: frozenset(
        {
            EvidenceClass.PUBLIC_FACT,
            EvidenceClass.PUBLIC_DERIVED,
            EvidenceClass.BENCHMARK_PRIOR,
            EvidenceClass.ANALYST_ASSUMPTION,
        }
    ),
    StageVersion.V1: frozenset(
        {
            EvidenceClass.PUBLIC_FACT,
            EvidenceClass.PUBLIC_DERIVED,
            EvidenceClass.BENCHMARK_PRIOR,
            EvidenceClass.ANALYST_ASSUMPTION,
            EvidenceClass.MANAGEMENT_RESPONSE,
        }
    ),
    StageVersion.V2: frozenset(
        {
            EvidenceClass.PUBLIC_FACT,
            EvidenceClass.PUBLIC_DERIVED,
            EvidenceClass.BENCHMARK_PRIOR,
            EvidenceClass.ANALYST_ASSUMPTION,
            EvidenceClass.MANAGEMENT_RESPONSE,
            EvidenceClass.CONTRACT,
            EvidenceClass.INVOICE,
            EvidenceClass.SERVICE_ORDER,
            EvidenceClass.CIRCUIT_INVENTORY,
            EvidenceClass.HIGH_LEVEL_ARCHITECTURE,
        }
    ),
    StageVersion.V3: frozenset(EvidenceClass) - frozenset(
        {
            EvidenceClass.MARKET_QUOTE,
            EvidenceClass.MARKET_BID,
            EvidenceClass.REALIZED_INVOICE,
            EvidenceClass.DISCONNECT_EVIDENCE,
        }
    ),
    StageVersion.V4: frozenset(EvidenceClass) - frozenset(
        {EvidenceClass.REALIZED_INVOICE, EvidenceClass.DISCONNECT_EVIDENCE}
    ),
    StageVersion.V5: frozenset(EvidenceClass),
}


def allowed_evidence(stage: StageVersion) -> frozenset[EvidenceClass]:
    return _STAGE_ALLOWED[stage]


def validate_evidence(stage: StageVersion, evidence_classes: Iterable[EvidenceClass]) -> None:
    supplied = set(evidence_classes)
    prohibited = supplied - _STAGE_ALLOWED[stage]
    if prohibited:
        names = ", ".join(sorted(item.value for item in prohibited))
        raise StagePolicyError(f"{stage.value} cannot consume evidence classes: {names}")
