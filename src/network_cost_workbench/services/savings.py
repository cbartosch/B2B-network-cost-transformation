from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


_CENTS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class SavingsResult:
    current_tco: Decimal
    target_tco: Decimal
    savings: Decimal
    savings_rate: Decimal | None


_BILLING_PERIODS: dict[str, Decimal] = {
    "MONTHLY": Decimal("12"),
    "QUARTERLY": Decimal("4"),
    "ANNUAL": Decimal("1"),
}


def annualize(amount: Decimal, billing_frequency: str) -> Decimal:
    try:
        factor = _BILLING_PERIODS[billing_frequency.upper()]
    except KeyError as exc:
        raise ValueError(f"unsupported billing frequency: {billing_frequency}") from exc
    return (amount * factor).quantize(_CENTS, rounding=ROUND_HALF_UP)


def calculate_savings(current_tco: Decimal, target_tco: Decimal) -> SavingsResult:
    current = current_tco.quantize(_CENTS, rounding=ROUND_HALF_UP)
    target = target_tco.quantize(_CENTS, rounding=ROUND_HALF_UP)
    savings = (current - target).quantize(_CENTS, rounding=ROUND_HALF_UP)
    rate = None if current == 0 else (savings / current * Decimal("100")).quantize(Decimal("0.01"))
    return SavingsResult(current, target, savings, rate)


def calculate_delta(current_savings: Decimal, prior_savings: Decimal) -> Decimal:
    return (current_savings - prior_savings).quantize(_CENTS, rounding=ROUND_HALF_UP)


def net_present_value(cash_flows: list[Decimal], annual_discount_rate: Decimal) -> Decimal:
    if annual_discount_rate <= Decimal("-1"):
        raise ValueError("annual discount rate must be greater than -100%")
    total = Decimal("0")
    for year, cash_flow in enumerate(cash_flows):
        total += cash_flow / ((Decimal("1") + annual_discount_rate) ** year)
    return total.quantize(_CENTS, rounding=ROUND_HALF_UP)
