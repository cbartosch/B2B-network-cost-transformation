"""Does the bottom-up estimate agree with what the company disclosed?

Specification 0.4: public spend evidence prepopulates `outside_in_tco_calibration`
- "Calibrate bottom-up current TCO against disclosed or proxy spend", with the
control "Show direct, derived and residual components separately."

The system had both halves and never put them together. ANCHOR takes a
disclosed figure and apportions it into layers; BUILD_UP constructs a total
from sites, circuits and rates. Nothing ran both on one case and asked whether
they agreed - and that comparison is the only self-check the estimate has.

If a company discloses 8.4m of network spend and the model builds up to 5.1m,
that is a finding before any client conversation. What it is not is a single
"variance" number, which is why the spec insists on three parts:

  **Direct**    layers the disclosure explicitly covers. If the annual report
                says "network and connectivity", access and transport are
                direct and a SASE licence probably is not.

  **Derived**   layers the model built that the disclosure does not separate.
                A disclosed total that bundles operations with circuits cannot
                be split by arithmetic, and pretending otherwise invents a
                precision the source does not have.

  **Residual**  what neither explains. This is the number worth arguing about,
                and collapsing it into the other two is how a calibration
                becomes a reassurance.

A calibration never adjusts the estimate. It reports. An estimate tuned until
it matches a disclosure has been fitted to one number and has stopped being a
measurement - the same reason the validation corpus refuses to feed the model.
"""
from decimal import Decimal

# How close is close enough to say the two agree. Deliberately wide: a
# disclosed figure is an annual report line item and a bottom-up estimate is a
# model of an estate, and demanding they match to a percent would report a
# false discrepancy on every case.
#
# Governed rather than hardcoded would be better; it is a constant here because
# there is no evidence for any particular value and a governed threshold nobody
# has calibrated is a hardcoded one with extra steps.
AGREES_WITHIN = Decimal("0.15")

# Why a calibration can be inconclusive rather than pass or fail. Three
# different situations that a single "variance" number would flatten.
AGREES = "AGREES"
MODEL_LOW = "MODEL_LOW"          # bottom-up under the disclosure
MODEL_HIGH = "MODEL_HIGH"        # bottom-up over it
NOT_COMPARABLE = "NOT_COMPARABLE"  # the two do not cover the same thing

# What a disclosed figure might not include, which is the first thing to check
# when the two disagree. Named so a reader can rule them out rather than
# assuming the model is wrong.
COMMON_EXCLUSIONS = (
    "mobile and fixed voice, often a separate line",
    "internal IT staff, where the disclosure is a supplier spend figure",
    "one-time and project costs, where the disclosure is run-rate",
    "sites outside the modelled scope - subsidiaries, joint ventures",
    "equipment capital, where the disclosure is operating expenditure",
)


class CalibrationInvalid(ValueError):
    """A comparison that would not mean anything."""


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def calibrate(*, bottom_up, disclosed, direct_layers: list,
              layer_totals: dict, disclosure_note: str | None = None,
              currency: str | None = None) -> dict:
    """The bottom-up total against a disclosed figure, in three parts.

    `layer_totals` is {layer: annual value} from the build-up.
    `direct_layers` names the layers the disclosure explicitly covers - an
    analyst's reading of the source, not something arithmetic can decide.

    Deliberately refuses to guess which layers are covered. A disclosure saying
    "network costs" might mean circuits only or circuits plus the team that
    runs them, and the difference is the whole answer.
    """
    built = _dec(bottom_up)
    stated = _dec(disclosed)
    if built is None or stated is None:
        raise CalibrationInvalid(
            "a calibration needs both a bottom-up total and a disclosed "
            "figure; one of them alone is an estimate, not a check on one")
    if stated <= 0:
        raise CalibrationInvalid(
            f"a disclosed figure of {stated} cannot be calibrated against. "
            f"Zero is not a disclosure, it is the absence of one.")
    if not direct_layers:
        raise CalibrationInvalid(
            "name the layers this disclosure covers. A disclosure saying "
            "'network costs' might mean circuits only or circuits plus the "
            "team that runs them, and the difference is the whole answer - "
            "arithmetic cannot decide it and guessing would invent the result.")

    direct = sum((_dec(v) or Decimal(0) for k, v in layer_totals.items()
                  if k in direct_layers), Decimal(0))
    derived = sum((_dec(v) or Decimal(0) for k, v in layer_totals.items()
                   if k not in direct_layers), Decimal(0))
    residual = stated - direct

    # Measured against the disclosure, because that is the figure with a
    # source. Dividing by the model's own output would measure the model
    # against itself.
    variance = (residual / stated) if stated else Decimal(0)
    within = abs(variance) <= AGREES_WITHIN

    verdict = (AGREES if within else
               MODEL_LOW if residual > 0 else MODEL_HIGH)

    return {
        "bottom_up_total": str(built),
        "disclosed_total": str(stated),
        "currency": currency,
        # The three parts the spec requires, never collapsed into one number.
        "direct": str(direct),
        "direct_layers": sorted(direct_layers),
        "derived": str(derived),
        "derived_layers": sorted(k for k in layer_totals
                                 if k not in direct_layers),
        "residual": str(residual),
        "variance_pct": str((variance * 100).quantize(Decimal("0.1"))),
        "verdict": verdict,
        "agrees_within": str(AGREES_WITHIN),
        "disclosure_note": disclosure_note,
        "check_first": list(COMMON_EXCLUSIONS) if not within else [],
        "note": _explain(verdict, residual, variance, direct, derived),
    }


def _explain(verdict, residual, variance, direct, derived) -> str:
    """What the three parts mean together, in the reader's terms."""
    if verdict == AGREES:
        return (
            f"the modelled layers come to {direct} against a disclosed "
            f"{direct + residual}, within {AGREES_WITHIN:.0%}. That is "
            f"agreement between two independent constructions, which is worth "
            f"more than either alone - and it is not proof that both are "
            f"right in the same way.")
    if verdict == MODEL_LOW:
        return (
            f"the model builds {direct} of directly comparable cost against a "
            f"disclosed figure {residual} higher - {variance:.0%}. Before "
            f"concluding the estimate is short, rule out what the disclosure "
            f"may include that the model does not.")
    return (
        f"the model builds {direct} against a disclosed figure {abs(residual)} "
        f"lower - {abs(variance):.0%}. A bottom-up estimate above a disclosed "
        f"total usually means the footprint or the rates are high, or the "
        f"disclosure covers less of the estate than the model does.")


def as_assumption(calibration: dict) -> dict | None:
    """A failing calibration as a gap for the assumption register.

    Returns None when the two agree: a calibration that passed is not a
    question anyone needs to answer, and registering it would fill the request
    with items the client cannot act on.
    """
    if calibration.get("verdict") == AGREES:
        return None
    return {
        "gap": "bottom-up estimate does not match disclosed spend",
        "detail": calibration["note"],
        "costs": ("the credibility of the whole baseline - two independent "
                  "constructions of the same number disagree"),
        "closes_it": ("confirm what the disclosed figure covers, and whether "
                      "the modelled scope matches it"),
    }
