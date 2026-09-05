"""Money in one currency, or an explicit conversion that says so.

Audit finding: every seeded prior is USD, the anchor carried no currency at
all, `fx_convention` was collected by pre-flight and read by no calculation,
and `match_prior` never considered currency. So a GBP anchor entered against
USD priors was arithmetic on mixed units - a 21.3% understatement - and the
snapshot then labelled the result with the case's base currency, asserting a
currency the calculation never established.

Three rules, in order of how much they matter.

**Same currency needs no conversion, and that is the common case.** A GB
engagement against GB priors in GBP converts nothing. The machinery exists for
the case where it cannot be avoided.

**A conversion is recorded, not applied silently.** Every converted figure
carries the rate, the date and the pair. An estimate whose baseline moved 21%
because of an exchange rate must say so where a reader looks, not in a log.

**A missing rate refuses rather than assumes.** There is no default of 1.0:
treating an unknown rate as parity is exactly the error this module exists to
prevent, and it would be invisible.
"""
from decimal import Decimal

# ISO 4217 for the currencies the seeded rate card and the in-scope countries
# actually use. Not a complete list, deliberately: a currency nobody has a rate
# for should be refused by name rather than accepted and mishandled.
KNOWN = ("USD", "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK",
         "AED", "SGD", "AUD", "CAD", "JPY", "INR", "BRL", "MXN", "ZAR")


class CurrencyMismatch(ValueError):
    """Two figures in different currencies with no rate to bridge them."""


class UnknownCurrency(ValueError):
    """A currency code nothing can price."""


def normalise(code) -> str | None:
    """An ISO code, or None. Refuses what it does not know.

    Uppercased and checked, because "gbp" and "GBP" are the same currency and
    "POUNDS" is not a currency code at all - and accepting it would put a
    figure in the model that nothing downstream can convert.
    """
    if code is None:
        return None
    text = str(code).strip().upper()
    if not text:
        return None
    if text not in KNOWN:
        raise UnknownCurrency(
            f"{code!r} is not a currency this model can price. Known: "
            f"{', '.join(KNOWN)}. A figure in an unlisted currency is refused "
            f"rather than treated as one of these.")
    return text


def convert(amount, *, frm: str, to: str, rates: dict) -> dict:
    """An amount in `to`, with the arithmetic that produced it.

    Returns a record rather than a number. A converted figure that looks like
    an unconverted one is how a 21% exchange-rate movement disappears into a
    baseline, and the caller should have to carry the provenance to use the
    value.

    `rates` maps a pair to a rate: {("GBP", "USD"): Decimal("1.27")}. An
    inverse is derived when the direct pair is absent, because holding both
    directions invites them to disagree.
    """
    source, target = normalise(frm), normalise(to)
    if source is None or target is None:
        raise CurrencyMismatch(
            f"a conversion needs both currencies; got {frm!r} -> {to!r}")

    if source == target:
        return {"amount": Decimal(str(amount)), "currency": target,
                "rate": Decimal("1"), "converted": False,
                "note": f"already in {target}"}

    rate = rates.get((source, target))
    inverted = False
    if rate is None:
        back = rates.get((target, source))
        if back is not None and Decimal(str(back)) != 0:
            rate = Decimal("1") / Decimal(str(back))
            inverted = True
    if rate is None:
        raise CurrencyMismatch(
            f"no rate for {source}->{target}. Refused rather than assumed: a "
            f"missing rate treated as parity is the error this exists to "
            f"prevent, and it would be invisible in the result.")

    rate = Decimal(str(rate))
    return {"amount": Decimal(str(amount)) * rate, "currency": target,
            "rate": rate, "converted": True, "inverted": inverted,
            "note": (f"{source} {amount} x {rate} = {target} "
                     f"{Decimal(str(amount)) * rate}"
                     + (" (inverse of the stored pair)" if inverted else ""))}


def reconcile(figures: list, *, to: str, rates: dict) -> dict:
    """Several figures into one currency, or a refusal naming what is missing.

    `figures` is [{"amount": ..., "currency": ...}, ...]. Used where a baseline
    is assembled from priors in more than one currency, which the model has
    never been able to express and would previously have summed regardless.
    """
    target = normalise(to)
    converted, missing = [], []
    for figure in figures:
        try:
            converted.append(convert(figure["amount"],
                                     frm=figure.get("currency"), to=target,
                                     rates=rates))
        except CurrencyMismatch as exc:
            missing.append({"figure": figure, "reason": str(exc)})

    return {
        "currency": target,
        "total": sum((c["amount"] for c in converted), Decimal(0)),
        "converted": [c for c in converted if c["converted"]],
        "unconvertible": missing,
        # Whether the total means anything. A total assembled from three of
        # five figures is not a total, and reporting it beside the two it could
        # not convert would invite it to be read as one.
        "complete": not missing,
        "note": (f"{len(converted)} figure(s) in {target}"
                 if not missing else
                 f"{len(missing)} figure(s) could not be converted, so this "
                 f"total covers only part of the input and must not be read "
                 f"as the whole"),
    }


def assert_single_currency(rows: list, *, field: str = "currency") -> str | None:
    """The currency every row shares, or a refusal.

    The cheapest control and the one that catches the real case: a rate card
    seeded entirely in USD priced against a GBP anchor. Rather than converting,
    this refuses and names both - because at V0 the right answer is usually to
    fix the rate card, not to apply an exchange rate to a grade E assumption.
    """
    found = {normalise(r.get(field)) if isinstance(r, dict)
             else normalise(getattr(r, field, None)) for r in rows}
    found.discard(None)
    if len(found) > 1:
        raise CurrencyMismatch(
            f"these figures are in {sorted(found)} and no conversion has been "
            f"applied. Converting a grade E assumption across an exchange rate "
            f"adds a second unevidenced step to an unevidenced number; fixing "
            f"the rate card is usually the right answer at this stage.")
    return found.pop() if found else None
