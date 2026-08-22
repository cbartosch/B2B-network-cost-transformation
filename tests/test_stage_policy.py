import pytest

from network_cost_workbench.domain.enums import EvidenceClass, StageVersion
from network_cost_workbench.domain.stage_policy import StagePolicyError, validate_evidence


def test_v0_rejects_invoice_evidence() -> None:
    with pytest.raises(StagePolicyError):
        validate_evidence(StageVersion.V0, [EvidenceClass.PUBLIC_FACT, EvidenceClass.INVOICE])


def test_v2_accepts_contracts_but_rejects_telemetry() -> None:
    validate_evidence(StageVersion.V2, [EvidenceClass.CONTRACT, EvidenceClass.INVOICE])
    with pytest.raises(StagePolicyError):
        validate_evidence(StageVersion.V2, [EvidenceClass.TELEMETRY])
