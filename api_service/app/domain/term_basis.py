"""Two prices on different terms, brought onto one basis.

A 36-month rate with equipment included is not comparable to a 12-month one
without, and the model held `term_months`, `sla`, `taxes_included`,
`equipment_included` and `managed_services_included` on every prior while
nothing read any of them. So a benchmark on a different commercial basis was
compared against the rate card as though the two were the same number.

Warn and normalise, rather than refuse. Currency had a correct answer to fall
back on - the same money in one unit - and this does not: a case whose only
available benchmark is on a 12-month term should still be able to use it, with
the adjustment visible.

**The adjustment is an assumption and is graded as one.** A 12-month price is
higher than a 36-month price for the same circuit, and the amount is a market
convention rather than a measurement. The factors here are evidence grade E,
which means a normalised rate is never better evidence than the assumption used
to move it - and the result carries both figures so a reader can see what was
done.

**Normalisation never silently improves a price.** Every adjusted figure
reports the original, the factor and why, on the same principle as the currency
conversion: a converted number that looks unconverted is how a 21% movement
disappears into a baseline.
"""
from decimal import Decimal

# The basis everything is brought onto. 36 months because every seeded prior
# declares it, so the common case adjusts nothing - and an adjustment that
# fires on every row is one nobody reads.
REFERENCE_TERM_MONTHS = 36

# What a term is worth relative to the reference, as a multiplier on the
# monthly rate. Shorter terms cost more per month: the carrier recovers its
# install and its risk over fewer of them.
#
# Evidence grade E. These are market convention, not measurement, and a rate
# normalised with them is not better evidence than they are. An engagement with
# real term pricing should replace them - the governed set exists for that.
TERM_FACTORS = {
    1: Decimal("1.35"),      # rolling monthly, the most expensive way to buy
    12: Decimal("1.15"),
    24: Decimal("1.05"),
    36: Decimal("1.00"),     # the reference
    60: Decimal("0.93"),
}

# What an included component is worth as a share of the monthly rate, for
# bringing an "equipment included" price onto a bare basis. Also grade E, and
# also replaceable.
INCLUSION_FACTORS = {
    "equipment_included": Decimal("0.08"),
    "managed_services_included": Decimal("0.15"),
}

# A tax-inclusive price is not adjusted by a factor, because the rate depends
# on the country and the model has no tax table. It is reported as
# not-normalisable instead - an honest gap rather than an invented number.
TAX_NOT_MODELLED = ("taxes_included",)


class NotNormalisable(ValueError):
    """A basis difference this model cannot bridge."""


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def term_factor(months) -> Decimal | None:
    """The multiplier from `months` onto the reference term.

    Interpolates between the nearest declared terms rather than refusing an
    undeclared one: a 30-month contract is a real contract, and rejecting it
    would push the analyst to mislabel it as 24 or 36.
    """
    wanted = _dec(months)
    if wanted is None or wanted <= 0:
        return None
    key = int(wanted)
    if key in TERM_FACTORS:
        return TERM_FACTORS[key]

    known = sorted(TERM_FACTORS)
    if key < known[0] or key > known[-1]:
        # Outside the range the convention covers. Clamped rather than
        # extrapolated: a 120-month price is a different kind of deal and
        # projecting the curve to it would invent a discount nobody offers.
        return TERM_FACTORS[known[0] if key < known[0] else known[-1]]

    lower = max(k for k in known if k < key)
    upper = min(k for k in known if k > key)
    span = Decimal(upper - lower)
    weight = Decimal(key - lower) / span
    return TERM_FACTORS[lower] + (TERM_FACTORS[upper] - TERM_FACTORS[lower]) * weight


def normalise(rate, *, basis: dict, to_term: int = REFERENCE_TERM_MONTHS) -> dict:
    """One rate onto the reference basis, with the arithmetic that got it there.

    `basis` is the commercial description of the rate as sold: term_months,
    sla, taxes_included, equipment_included, managed_services_included.

    Returns the adjusted figure beside the original. A normalised rate that
    looks unnormalised is how an assumption becomes a fact.
    """
    original = _dec(rate)
    if original is None:
        raise NotNormalisable("a rate is needed to normalise")

    steps, warnings = [], []
    adjusted = original

    from_term = basis.get("term_months")
    factor_from = term_factor(from_term)
    factor_to = term_factor(to_term)
    if factor_from is None or factor_to is None:
        warnings.append(
            "no term is declared on this rate, so it is compared as though it "
            "were already on the reference basis - which it may not be")
    elif factor_from != factor_to:
        adjustment = factor_to / factor_from
        adjusted = adjusted * adjustment
        steps.append({
            "step": "term",
            "from": f"{from_term} months", "to": f"{to_term} months",
            "factor": str(adjustment.quantize(Decimal("0.0001"))),
            "why": ("a shorter term costs more per month - the carrier "
                    "recovers its install and its risk over fewer of them"),
        })
        warnings.append(
            f"adjusted from a {from_term}-month to a {to_term}-month basis "
            f"using a market-convention factor, which is evidence grade E. "
            f"The normalised rate is not better evidence than that assumption.")

    for field, share in INCLUSION_FACTORS.items():
        if basis.get(field):
            adjusted = adjusted * (Decimal(1) - share)
            steps.append({
                "step": field,
                "factor": str(Decimal(1) - share),
                "why": (f"the quoted rate includes {field.replace('_', ' ')}; "
                        f"the reference basis is bare, so the included "
                        f"component is removed to compare like with like"),
            })
            warnings.append(
                f"{field.replace('_', ' ')} was removed at a grade E share; "
                f"the real inclusion may be worth more or less on this rate")

    not_modelled = [f for f in TAX_NOT_MODELLED if basis.get(f)]
    if not_modelled:
        warnings.append(
            f"this rate is {', '.join(not_modelled).replace('_', ' ')} and the "
            f"model has no tax table, so no adjustment was made. The "
            f"comparison is off by the local rate, which is a known gap rather "
            f"than a small one.")

    return {
        "original": str(original),
        "normalised": str(adjusted.quantize(Decimal("0.01"))),
        "reference_term_months": to_term,
        "steps": steps,
        "adjusted": bool(steps),
        "warnings": warnings,
        # The grade a normalised rate can carry. Never better than E once an
        # adjustment has been applied, whatever the original was graded: the
        # figure now contains an assumption.
        "grade_ceiling": "E" if steps else None,
        "note": ("no adjustment needed - this rate is already on the reference "
                 "basis" if not steps else
                 f"{len(steps)} adjustment(s) applied. The original is kept "
                 f"beside the result: a normalised rate that looks "
                 f"unnormalised is how an assumption becomes a fact."),
    }


def comparable(left: dict, right: dict) -> dict:
    """Whether two rates were sold on the same terms, and where they differ.

    Reported, never enforced. Two rates on different bases can still be
    compared once normalised, and the point of naming the differences is that a
    reader can decide whether the adjustment is credible for this market.
    """
    fields = ("term_months", "sla", "taxes_included", "equipment_included",
              "managed_services_included")
    differences = {f: {"left": left.get(f), "right": right.get(f)}
                   for f in fields if left.get(f) != right.get(f)}
    return {
        "same_basis": not differences,
        "differences": differences,
        "note": ("both rates were sold on the same commercial basis"
                 if not differences else
                 f"{sorted(differences)} differ. Normalisation can bridge "
                 f"term and inclusions at grade E; an SLA difference it cannot "
                 f"bridge at all, because a premium SLA is a different service "
                 f"rather than the same one priced differently."),
    }
