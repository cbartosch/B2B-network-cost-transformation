from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from network_cost_workbench.domain.enums import StageVersion, ValueStatus


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter ISO-like code")
        object.__setattr__(self, "currency", self.currency.upper())


@dataclass(frozen=True, slots=True)
class EstimateSnapshot:
    engagement_id: UUID
    stage: StageVersion
    current_tco: Money
    target_tco: Money
    value_status: ValueStatus
    estimate_snapshot_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    prior_snapshot_id: UUID | None = None
    stage_status: str = "COMPLETE"
    covered_spend_percentage: Decimal = Decimal("100")

    @property
    def savings(self) -> Money:
        if self.current_tco.currency != self.target_tco.currency:
            raise ValueError("current and target TCO currencies must match")
        return Money(self.current_tco.amount - self.target_tco.amount, self.current_tco.currency)
