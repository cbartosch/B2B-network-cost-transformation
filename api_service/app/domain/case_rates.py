"""A client's own rates, which belong to that client and nobody else.

`reference.unit_cost_prior` is the rate card: market prices, keyed by country
and product and shared by every engagement. It has no `case_id`, so there has
never been anywhere to put a price a client actually pays.

That matters more than it sounds. A client's invoices are the best evidence the
model can have - grade A, a transaction rather than a benchmark - and loading
them into the shared card would price every other engagement off one client's
negotiated deal. So the choice was between the best evidence available and not
contaminating the reference set, and the model took the second by having no
third option.

**Two stores, and the boundary between them is the point.**

    reference.unit_cost_prior   market. Published tariffs, cleared benchmarks,
                                anything any engagement may price from.
    outside_in.case_rate        this client's. Invoices, quotes, contracted
                                rates. Priced for this case and no other.

**What may cross, and what may not.** A markup percentage derived from a
client's invoices against a published wholesale tariff is a market
observation - it says something about the retail market, not about the client.
The MRC itself is not: it says what one company negotiated, and a second
company's estimate built on it is a guess dressed as evidence.

So `case_rate` never promotes to `unit_cost_prior`, and `derived_markup()`
exists to carry the one thing that legitimately generalises.
"""
from decimal import Decimal

# Where a case rate came from. Not a formality: an invoice is what the client
# pays today and a quote is what a supplier says they would charge, and a
# baseline built from quotes is a baseline of offers rather than of costs.
INVOICE = "INVOICE"                # a billed line on a real invoice
CONTRACT = "CONTRACT"              # a contracted rate, billed or not
QUOTE = "QUOTE"                    # a supplier's offer
CLIENT_STATED = "CLIENT_STATED"    # the client said so, unevidenced
# RATE_BASES, not BASES: known_facts.py already has a BASES and two constant
# tables of the same name in two modules is how ORIGIN_RANK ended up meaning
# different things in different files.
RATE_BASES = (INVOICE, CONTRACT, QUOTE, CLIENT_STATED)

# The evidence grade each basis can carry. An invoice is the only thing in this
# model that reaches A: it is a transaction that happened, for this client, at
# this price. Everything else is weaker and says so.
GRADE_OF_BASIS = {
    INVOICE: "A",
    CONTRACT: "A",
    QUOTE: "B",
    CLIENT_STATED: "C",
}


class RateRejected(ValueError):
    """A rate that cannot be priced from, or cannot be trusted as claimed."""


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def rate(*, case_id: str, country: str, service_class: str,
         access_technology: str | None, bandwidth_mbps,
         monthly_recurring, currency: str, basis: str,
         term_months=None, source: str | None = None,
         circuit_count=None) -> dict:
    """One client rate, graded by where it came from.

    Refuses rather than accepts-and-flags in three cases, because each would
    put a number in a client's baseline that cannot mean what it appears to:

      - an unknown basis, since the grade follows from it
      - a non-positive charge, which is an absent rate rather than a free one
      - an invoice with no source, since the whole reason an invoice grades A
        is that somebody can go and look at it
    """
    if basis not in RATE_BASES:
        raise RateRejected(
            f"{basis!r} is not one of {list(RATE_BASES)}. The evidence grade "
            f"follows from the basis, so an unknown basis is an ungradeable "
            f"rate.")

    charge = _dec(monthly_recurring)
    if charge is None or charge <= 0:
        raise RateRejected(
            f"{monthly_recurring!r} is not a monthly charge. Zero is an absent "
            f"rate rather than a free circuit, and a baseline that counts it "
            f"as nothing understates by exactly the amount nobody noticed.")

    if basis in (INVOICE, CONTRACT) and not str(source or "").strip():
        raise RateRejected(
            f"a {basis} rate needs its source named. The reason an invoice "
            f"grades A is that somebody can go and look at it, and one nobody "
            f"can find is a client-stated figure with a better label.")

    return {
        "case_id": case_id,
        "country": str(country or "").upper() or None,
        "service_class": service_class,
        "access_technology": access_technology,
        "bandwidth_mbps": None if bandwidth_mbps is None else int(bandwidth_mbps),
        "monthly_recurring": str(charge),
        "currency": str(currency or "").upper() or None,
        "basis": basis,
        "evidence_grade": GRADE_OF_BASIS[basis],
        "term_months": None if term_months is None else int(term_months),
        "circuit_count": None if circuit_count is None else int(circuit_count),
        "source": source,
    }


def as_prior(case_rate: dict) -> dict:
    """A case rate in the shape `match_prior` reads.

    A single figure, not a band: an invoice is what was charged, and inventing
    a low and a high around it would manufacture uncertainty the evidence does
    not have. The band comes back at the estate level, from the spread of the
    rates themselves.
    """
    charge = _dec(case_rate.get("monthly_recurring"))
    annual = None if charge is None else charge * 12
    return {
        "low": str(annual), "base": str(annual), "high": str(annual),
        "scope": case_rate.get("country"),
        "service_class": case_rate.get("service_class"),
        "access_technology": case_rate.get("access_technology"),
        "bandwidth_mbps": case_rate.get("bandwidth_mbps"),
        "currency": case_rate.get("currency"),
        "evidence_grade": case_rate.get("evidence_grade"),
        "price_basis": f"CASE_{case_rate.get('basis')}",
        "term_months": case_rate.get("term_months"),
        # No expiry. A client's invoiced rate for this engagement does not go
        # stale the way a market benchmark does - it is what they paid, and if
        # the contract changes that is a new rate rather than an expired one.
        "expires": None,
    }


def index(case_rates: list) -> dict:
    """Case rates keyed the way `match_prior` looks them up.

    Where more than one rate shares a key, the **median** is taken rather than
    the mean: a retail estate has hundreds of circuits at one tier and one
    mispriced line should not move the rate the whole tier prices at.

    The count is carried so a reader can tell a rate from one circuit from a
    rate from four hundred.
    """
    grouped = {}
    for entry in case_rates:
        key = (entry.get("country"), entry.get("service_class"),
               entry.get("access_technology"), entry.get("bandwidth_mbps"))
        grouped.setdefault(key, []).append(entry)

    out = {}
    for key, entries in grouped.items():
        charges = sorted(_dec(e["monthly_recurring"]) for e in entries)
        middle = len(charges) // 2
        median = (charges[middle] if len(charges) % 2
                  else (charges[middle - 1] + charges[middle]) / 2)
        best = min(entries, key=lambda e: "ABCDEF".index(e["evidence_grade"]))
        prior = as_prior({**best, "monthly_recurring": str(median)})
        prior["observed_circuits"] = sum(e.get("circuit_count") or 1
                                         for e in entries)
        prior["rate_count"] = len(entries)
        out[key] = prior
    return out


def derived_markup(*, client_rate, wholesale_rate) -> dict:
    """The markup a client pays over a published wholesale tariff.

    The one thing that legitimately crosses from a client's data into the
    shared reference set. A markup says something about the retail market; the
    MRC underneath it says what one company negotiated, and a second company's
    estimate built on that is a guess dressed as evidence.

    Reported as a record rather than a number, so the crossing is visible
    wherever it is used.
    """
    client = _dec(client_rate)
    wholesale = _dec(wholesale_rate)
    if client is None or wholesale is None or wholesale <= 0:
        raise RateRejected(
            "a markup needs a client rate and a positive wholesale rate; "
            "without the second there is nothing to be a markup over")
    if client < wholesale:
        # Real, and worth saying rather than refusing: a large customer can
        # buy below a published tariff, and a negative markup is a finding
        # about their buying power.
        note = ("this client pays below the published wholesale tariff, which "
                "is a finding about their buying power rather than an error")
    else:
        note = "markup over the published wholesale tariff"
    return {
        "markup_share": str(((client - wholesale) / wholesale)
                            .quantize(Decimal("0.0001"))),
        "client_rate": str(client),
        "wholesale_rate": str(wholesale),
        "crosses_to_reference": True,
        "note": note + ". The markup generalises; the client's own charge does "
                       "not and stays on the case.",
    }


def leakage(case_rates: list, *, stated_total) -> dict:
    """What the client's own rates sum to, against what they said they spend.

    The self-check a case rate makes possible and a market rate never could.
    If the invoiced lines total less than the stated spend, the difference is
    either scope the model has not seen or spend outside the perimeter - and
    either way it is a question rather than a rounding.
    """
    total = sum((_dec(e["monthly_recurring"]) or Decimal(0)
                 for e in case_rates), Decimal(0)) * 12
    stated = _dec(stated_total)
    if stated is None or stated <= 0:
        return {"rate_total_annual": str(total), "stated_total": None,
                "note": ("no stated spend to reconcile against, so the rates "
                         "are what they are")}
    gap = stated - total
    return {
        "rate_total_annual": str(total),
        "stated_total": str(stated),
        "unexplained": str(gap),
        "unexplained_share": str((gap / stated).quantize(Decimal("0.001"))),
        "reconciles": abs(gap) <= stated * Decimal("0.01"),
        "note": (
            "the client's own rates account for their stated spend"
            if abs(gap) <= stated * Decimal("0.01") else
            f"{gap} of {stated} is not covered by the rates supplied. That is "
            f"scope the model has not seen or spend outside the perimeter, and "
            f"either way it is a question rather than a rounding."),
    }
