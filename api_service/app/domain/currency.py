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


def _pivot_currency(fx_rows: list) -> str | None:
    """The currency this rate table is built around.

    Read off the rows rather than assumed to be USD: the table is a star
    and the centre of it is whatever appears most often on the from side.
    Hardcoding the pivot would be right today and silently wrong the first
    time somebody seeds a EUR-centred table.
    """
    counts: dict = {}
    for row in fx_rows:
        code = normalise(row.get("from_currency"))
        if code:
            counts[code] = counts.get(code, 0) + 1
    return max(counts, key=lambda c: counts[c]) if counts else None


def _cross(fx_rows: list, *, frm: str, to: str, convention, as_of):
    """A two-leg conversion through the table's pivot, or None."""
    pivot = _pivot_currency(fx_rows)
    if pivot is None or pivot in (frm, to):
        return None
    first = select_rate(fx_rows, frm=frm, to=pivot,
                        convention=convention, as_of=as_of)
    second = select_rate(fx_rows, frm=pivot, to=to,
                         convention=convention, as_of=as_of)
    if first is None or second is None:
        return None

    def _factor(picked):
        rate = Decimal(str(picked["rate"]))
        return Decimal(1) / rate if picked.get("inverted") else rate

    factor = _factor(first) * _factor(second)
    return {
        "factor": factor,
        "picked": {
            "rate": str(factor), "inverted": False,
            "via": pivot,
            "legs": [{"from": frm, "to": pivot, "rate": str(first["rate"]),
                      "inverted": first.get("inverted"),
                      "source": first.get("source"),
                      "evidence_grade": first.get("evidence_grade")},
                     {"from": pivot, "to": to, "rate": str(second["rate"]),
                      "inverted": second.get("inverted"),
                      "source": second.get("source"),
                      "evidence_grade": second.get("evidence_grade")}],
            "convention": first.get("convention"),
            "as_of": first.get("as_of"),
            # The weaker of the two legs, because a chain is as good as its
            # worst link and reporting the better one would overstate it.
            "evidence_grade": max(
                str(first.get("evidence_grade") or "E"),
                str(second.get("evidence_grade") or "E")),
            "exact": False,
            "source": f"cross-rate via {pivot}",
            "note": (f"no {frm}->{to} rate exists; converted through "
                     f"{pivot}, so this figure crossed two indicative "
                     f"rates rather than one"),
        },
    }


def rate_table(fx_rows: list, *, currencies, to: str, convention, as_of):
    """A conversion factor per source currency, or a refusal naming the gaps.

    The rate card was one currency for as long as every row in it was
    seeded. A researched price is stored in the currency its source quoted -
    deliberately, because stamping every promoted price USD once put a EUR
    tariff into the card as dollars, a 7-8% error before anything else
    happened - so the moment one is approved the card holds two.

    `assert_single_currency` refused that, and was right to while a mix
    could only mean a mistake. It is not a mistake any more: a card holding
    GBP, EUR and USD rows is a card that knows what each price was quoted
    in, which is strictly more than one that pretends they are all dollars.

    So each currency gets its own factor and each row converts at its own.
    Still a refusal where a rate is genuinely absent, naming every currency
    it could not convert rather than the first - a steward adding rates
    wants the list, not one at a time.
    """
    target = normalise(to)
    factors, detail, missing = {target: Decimal(1)}, {}, []
    for code in sorted({normalise(c) for c in currencies if normalise(c)}):
        if code == target:
            continue
        picked = select_rate(fx_rows, frm=code, to=target,
                             convention=convention, as_of=as_of)
        if picked is not None:
            rate = Decimal(str(picked["rate"]))
            factors[code] = (Decimal(1) / rate if picked.get("inverted")
                             else rate)
        else:
            # Through the table's own pivot.
            #
            # reference.fx_rate is a star: every row is USD -> X. So EUR to
            # CHF is not a pair it holds and never will be, and refusing it
            # means the card can only ever be USD or the case's own
            # currency - the same blockage in a new shape, and it stopped
            # Novartis and Nestle pricing at all.
            #
            # Not an invention: using a star table as a star table. It does
            # compound two rates, and both are recorded, because a figure
            # that crossed two indicative rates is weaker than one that
            # crossed one and the result should say so.
            legs = _cross(fx_rows, frm=code, to=target,
                          convention=convention, as_of=as_of)
            if legs is None:
                missing.append(code)
                continue
            picked, factors[code] = legs["picked"], legs["factor"]
        # Pinned per currency, because a baseline that moved on an exchange
        # rate has to say which one, and a rerun next week must use the same
        # rate or the same case gives a different answer for a reason nobody
        # chose. One global `fx` block could not express a card holding three.
        detail[code] = {"rate": str(picked["rate"]),
                        "factor": str(factors[code]),
                        "via": picked.get("via"),
                        "legs": picked.get("legs"),
                        "inverted": picked.get("inverted"),
                        "convention": picked.get("convention"),
                        "as_of": picked.get("as_of"),
                        "evidence_grade": picked.get("evidence_grade"),
                        "as_asked": picked.get("exact"),
                        "source": picked.get("source"),
                        "note": picked.get("note")}
    if missing:
        raise CurrencyMismatch(
            f"the rate card holds prices in {missing} and this case is "
            f"priced in {target}, and reference.fx_rate has no rate for "
            f"{'those pairs' if len(missing) > 1 else 'that pair'}. Refused "
            f"rather than assumed: a missing rate treated as parity would be "
            f"invisible in the result. A steward adds the rate, or the "
            f"prices in {missing} are revoked from the card.")
    return {"to": target, "factors": factors, "detail": detail}


#: The only fields on a prior that are money.
#:
#: A bandwidth is not money and a price year is not money. Multiplying a
#: field because it happens to be numeric is how a unit error gets in, so
#: the set is named rather than inferred.
PRICED_BOUNDS = ("low", "base", "high")


def convert_prior(prior: dict, *, factors: dict) -> dict:
    """Move one rate-card row into the case currency, in place.

    Lifted out of the estimate route so it can be tested by calling it. It
    lived inline, and the tests that guarded it had to scan the route's
    source text for the string `if _fx is not None:` - which made them
    assertions about how the code is written rather than what it does, and
    they broke the moment the card went multi-currency even though every
    behaviour they describe still held.

    A row already in the case currency has a factor of one and records
    nothing, so a single-currency card is untouched.
    """
    factor = factors.get(normalise(prior.get("currency")))
    if factor is None or factor == 1:
        return prior
    for bound in PRICED_BOUNDS:
        if prior.get(bound) is not None:
            prior[bound] = Decimal(str(prior[bound])) * factor
    prior["converted_from"] = prior.get("currency")
    prior["fx_rate"] = str(factor)
    return prior


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


# How an engagement picks the rate it prices at.
#
# `fx_convention` has been on the case since pre-flight and read by no
# calculation - the finding this module was written for. These are the three
# an engagement actually uses, and they are not interchangeable: a budget rate
# is set once and held, so a baseline priced at it stays comparable to a plan
# priced at it, while a spot rate makes the same estate cost a different amount
# on Tuesday.
SPOT = "SPOT"            # the rate on a named day
AVERAGE = "AVERAGE"      # the average across the pricing period
BUDGET = "BUDGET"        # the rate the client set for the year
CONVENTIONS = (SPOT, AVERAGE, BUDGET)


def select_rate(rows, *, frm: str, to: str, convention: str | None,
                as_of: str | None) -> dict | None:
    """The rate this case should price at, and why that one.

    Returns a record, not a number, for the same reason `convert` does: a
    reader has to be able to see which rate was used and whether it was the
    one the engagement asked for.

    Preference order, and each step is a worse answer than the one above:

      1. the convention the case declared, dated on or before the pricing date
      2. that convention at any date - a rate from the wrong month beats no
         rate, and the date is reported so the reader can judge
      3. another convention, named - a spot rate where a budget rate was asked
         for is a different claim about the year, and saying so is the point
      4. None, and the caller refuses

    The direction is not searched here. `convert` already derives an inverse
    when the direct pair is absent, and holding both directions invites them
    to disagree.
    """
    source, target = normalise(frm), normalise(to)
    if source is None or target is None:
        return None
    if source == target:
        return {"rate": Decimal("1"), "convention": convention,
                "as_of": as_of, "exact": True, "inverted": False,
                "note": f"no conversion needed; both sides are {target}"}

    def _pair(row):
        got_from = normalise(row.get("from_currency"))
        got_to = normalise(row.get("to_currency"))
        if (got_from, got_to) == (source, target):
            return False          # direct
        if (got_from, got_to) == (target, source):
            return True           # the caller will invert
        return None

    usable = []
    for row in rows or []:
        try:
            inverted = _pair(row)
        except UnknownCurrency:
            # A row naming a currency this model cannot price is not a reason
            # to fail the estimate; it is a row a steward should fix.
            continue
        if inverted is None:
            continue
        usable.append({**row, "inverted": inverted})

    if not usable:
        return None

    wanted = (convention or "").strip().upper() or None
    on_convention = [r for r in usable
                     if (r.get("convention") or "").upper() == wanted] \
        if wanted else []

    def _dated(candidates):
        """Those dated on or before the pricing date, newest first."""
        if not as_of:
            return sorted(candidates, key=lambda r: str(r.get("as_of") or ""),
                          reverse=True)
        return sorted([r for r in candidates
                       if str(r.get("as_of") or "") <= str(as_of)],
                      key=lambda r: str(r.get("as_of") or ""), reverse=True)

    for candidates, exact, why in (
            (_dated(on_convention), True, None),
            (sorted(on_convention, key=lambda r: str(r.get("as_of") or "")),
             False, "no {c} rate on or before {d}, so the nearest {c} rate is "
                    "used and it is dated after the pricing date"),
            (_dated(usable), False,
             "no {c} rate exists for this pair, so a {g} rate is used - a "
             "different claim about the year than the one this case asked "
             "for"),
            (sorted(usable, key=lambda r: str(r.get("as_of") or "")), False,
             "no {c} rate exists and no rate is dated on or before {d}, so "
             "the nearest available rate is used"),
    ):
        if not candidates:
            continue
        chosen = candidates[0]
        note = (why or "").format(c=wanted or "declared",
                                  d=as_of or "the pricing date",
                                  g=chosen.get("convention") or "undeclared")
        return {"rate": Decimal(str(chosen["rate"])),
                "convention": chosen.get("convention"),
                "as_of": chosen.get("as_of"),
                "source": chosen.get("source"),
                "evidence_grade": chosen.get("evidence_grade"),
                "inverted": chosen["inverted"],
                "exact": exact,
                "note": note or (
                    f"{chosen.get('convention')} rate dated "
                    f"{chosen.get('as_of')}, as the case asked for")}
    return None
