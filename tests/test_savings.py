from decimal import Decimal

from network_cost_workbench.services.savings import annualize, calculate_savings, net_present_value


def test_negative_savings_are_preserved() -> None:
    result = calculate_savings(Decimal("100"), Decimal("120"))
    assert result.savings == Decimal("-20.00")
    assert result.savings_rate == Decimal("-20.00")


def test_billing_frequency_is_governed() -> None:
    assert annualize(Decimal("100"), "MONTHLY") == Decimal("1200.00")
    assert annualize(Decimal("100"), "QUARTERLY") == Decimal("400.00")


def test_npv() -> None:
    assert net_present_value([Decimal("-100"), Decimal("60"), Decimal("60")], Decimal("0.1")) == Decimal("4.13")
