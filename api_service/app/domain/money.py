"""Decimal money. Spec 16: authoritative monetary calculations use Decimal with
per-currency rounding. Floats never touch a published figure."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28
TWO = Decimal("0.01")


def D(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value) -> Decimal:
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def as_str(value) -> str:
    """Serialise for JSON without going through float."""
    return str(money(value))


class Range:
    """Low/base/high triple. Cost increases stay negative; nothing is floored to zero."""

    __slots__ = ("low", "base", "high")

    def __init__(self, low, base, high):
        self.low, self.base, self.high = D(low), D(base), D(high)

    def __add__(self, other):
        return Range(self.low + other.low, self.base + other.base, self.high + other.high)

    def __sub__(self, other):
        # low-minus-high and high-minus-low: a saving range narrows correctly
        return Range(self.low - other.high, self.base - other.base, self.high - other.low)

    def scale(self, factor):
        f = D(factor)
        return Range(self.low * f, self.base * f, self.high * f)

    def to_dict(self):
        return {"low": as_str(self.low), "base": as_str(self.base), "high": as_str(self.high)}

    @classmethod
    def zero(cls):
        return cls(0, 0, 0)
