"""Triangulation: several sources' figures into one band, deterministically.

The agent's job is to find what each source says. This module's job is to turn
three disagreeing figures into something the estimate can use, and to say how
much they disagreed. The split matters for the same reason it matters
everywhere else here: a model that averages three numbers leaves nobody able
to check which three, or how, or whether it would do the same again.

The case that motivated it: HypoVereinsbank's German branch count is stated as
341 in one restructuring record, around 400 in a contemporaneous newspaper
projection, and 371 in a later NGO profile. A schema with one `value` field
forced the agent to pick one and throw the other two away. The useful answer
is 341 / 371 / 400 across 2021-2023 with a 17 percent spread and a note that
the estate was shrinking throughout - which is a better input to a cost model
than any single figure, and is also the honest one.

**Nothing here picks a winner.** Where the spread is material the quantity is
flagged and a conflict group is recorded, so the disagreement survives into
review instead of being resolved by whichever candidate happened to be listed
first. Spec 0.3B's rule for competing evidence, applied to quantities.

**Base is the median, not the newest and not the mean.** The median is robust
to one bad candidate in a way the mean is not, and three observations do not
support anything more sophisticated. Where the newest candidate sits far from
the median that is reported as a separate flag rather than silently preferred:
a shrinking estate and a wrong outlier look identical from inside the
arithmetic, and only a human can tell them apart.
"""
import statistics
import uuid
from decimal import Decimal

from .money import D

# Flags are advisory, and every one of them is a reason a person might want to
# look. None of them changes a number.
SINGLE_SOURCE = "SINGLE_SOURCE"
MATERIAL_SPREAD = "MATERIAL_SPREAD"
STALE = "STALE"
NEWEST_DIVERGES = "NEWEST_DIVERGES"
UNIT_MISMATCH = "UNIT_MISMATCH"
UNDATED = "UNDATED"


NUMERIC = __import__("re").compile(
    r"^\s*[^\d\-+]{0,3}\s*([-+]?[\d][\d,\u00a0 ]*(?:\.\d+)?)\s*"
    r"(?:mbps|gbps|m|k|bn|million|thousand|billion)?\s*$", __import__("re").I)
_SCALE = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000,
          "bn": 1_000_000_000, "billion": 1_000_000_000}


def parse_value(raw):
    """A source's wording into a number, or None if it is not one.

    The schema used to demand a Decimal, so a domain whose honest answer is
    "2 halls, 2.75 MW" or "T-Systems (Deutsche Telekom)" failed validation
    three times and wrote no disposition - the agent was punished for
    reporting what the source said. Prose is a real finding; it is simply not
    a quantity, and deciding which is which is arithmetic, not a reason to
    reject a reply.

    Deliberately narrow. "1,250" and "2.75" and "3 million" parse; "2 halls,
    2.75 MW" does not, because picking one of two numbers out of it would be
    inventing which one was meant.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return D(raw)
    match = NUMERIC.match(str(raw))
    if not match:
        return None
    digits = match.group(1).replace(",", "").replace("\u00a0", "").replace(" ", "")
    try:
        value = D(digits)
    except (ArithmeticError, ValueError):
        return None
    suffix = str(raw).strip().lower().split()[-1] if str(raw).strip() else ""
    for token, factor in _SCALE.items():
        if suffix == token:
            return value * D(factor)
    return value


def _plain(value):
    """A Decimal as a readable string, or None.

    money.as_str would render a site count as "341.00", which is money
    formatting applied to a thing that is not money. A band here holds counts,
    bandwidths and amounts, so the trailing zeros are dropped and whatever the
    number actually is survives.
    """
    if value is None:
        return None
    text = format(Decimal(str(value)).normalize(), "f")
    return text


def _year(as_of) -> int | None:
    """Leading four digits of whatever the source said. Deliberately crude:
    a source that writes "FY2024" or "31 Dec 2024" or "2024-12-31" means the
    same year, and a parser that rejects two of those forms loses candidates
    for no benefit."""
    text = str(as_of or "").strip()
    for i in range(len(text) - 3):
        chunk = text[i:i + 4]
        if chunk.isdigit() and 1900 < int(chunk) < 2200:
            return int(chunk)
    return None


def triangulate_one(candidates: list[dict], *, policy, price_year: int) -> dict:
    """One quantity's candidates into a band with flags.

    Returns a dict carrying low/base/high, the candidates that produced them,
    the spread, the vintage range and the flags. Never raises on odd input:
    a candidate that cannot be compared is set aside and reported, because
    dropping it silently is how a two-source band becomes a one-source band
    that still looks corroborated.
    """
    usable, set_aside, flags = [], [], []

    units = {(c.get("unit") or "").strip().lower() for c in candidates if c.get("unit")}
    if len(units) > 1:
        # Different units are not a disagreement about a number, they are a
        # disagreement about what is being counted. Banding across them would
        # produce a figure describing nothing.
        flags.append(UNIT_MISMATCH)

    for c in candidates:
        value = parse_value(c.get("value"))
        if value is None:
            set_aside.append({
                **c, "set_aside_reason":
                    f"{c.get('value')!r} is a finding but not a single number, "
                    f"so it cannot be banded with the others"})
            continue
        if units and len(units) > 1 and (c.get("unit") or "").strip().lower() != \
                sorted(units)[0]:
            set_aside.append({**c, "set_aside_reason": "unit differs from the majority"})
            continue
        usable.append({**c, "_value": value, "_year": _year(c.get("as_of"))})

    if not usable:
        return {"low": None, "base": None, "high": None, "candidates": candidates,
                "set_aside": set_aside, "flags": flags + ["NO_USABLE_CANDIDATE"],
                "candidate_count": 0}

    values = sorted(u["_value"] for u in usable)
    low, high = values[0], values[-1]
    base = D(statistics.median(values))

    years = [u["_year"] for u in usable if u["_year"]]
    newest_year = max(years) if years else None
    oldest_year = min(years) if years else None
    if not years:
        flags.append(UNDATED)

    if len(usable) == 1:
        flags.append(SINGLE_SOURCE)

    spread = (high - low) / low if low and low > 0 else D(0)
    if spread >= D(policy.material_spread_share):
        flags.append(MATERIAL_SPREAD)

    if newest_year and (price_year - newest_year) > policy.stale_after_years:
        flags.append(STALE)

    # A newest candidate far from the median is either a trend or an outlier,
    # and the arithmetic cannot tell which.
    newest = None
    if newest_year:
        newest_vals = [u["_value"] for u in usable if u["_year"] == newest_year]
        newest = D(statistics.median(sorted(newest_vals)))
        if base and base > 0:
            drift = abs(newest - base) / base
            if drift >= D(policy.material_spread_share):
                flags.append(NEWEST_DIVERGES)

    # Strings, not Decimals. This dict is stored in a JSON column and returned
    # over HTTP, and json.dumps cannot serialise a Decimal - so every domain
    # that produced a band died with "Object of type Decimal is not JSON
    # serializable" after the research itself had succeeded. The rest of this
    # codebase already stores money and quantities as strings for the same
    # reason; the band was the one place that did not.
    #
    # Consumers parse when they need arithmetic: promotion does int(), the
    # refinement comparison uses its own Decimal coercion, and a string
    # displays unchanged.
    return {
        "low": _plain(low), "base": _plain(base), "high": _plain(high),
        "newest_value": _plain(newest),
        "newest_year": newest_year,
        "oldest_year": oldest_year,
        "spread_share": round(float(spread), 4),
        "candidate_count": len(usable),
        "candidates": [{k: v for k, v in u.items() if not k.startswith("_")}
                       for u in usable],
        "set_aside": set_aside,
        "flags": flags,
        "conflict_group_id": (str(uuid.uuid4()) if MATERIAL_SPREAD in flags
                              or UNIT_MISMATCH in flags else None),
        "review_required": bool(
            {MATERIAL_SPREAD, UNIT_MISMATCH, NEWEST_DIVERGES} & set(flags)),
        "basis": ("median of {n} source(s); low and high are the observed "
                  "extremes, not a confidence interval"
                  .format(n=len(usable))),
    }


def triangulate(quantities: list[dict], *, policy, price_year: int) -> list[dict]:
    """Group an agent's quantities and band each group.

    Grouped on (label, country, unit) - the key the estimate consumes. Two
    agents' findings about the same thing therefore merge, which is the point:
    corroboration across sources is what makes a band mean anything.

    A quantity the agent returned as a single figure with no candidates is
    treated as its own one-candidate group, so it flows through the same path
    and carries SINGLE_SOURCE rather than looking better-evidenced than it is.
    """
    groups: dict[tuple, list] = {}
    for q in quantities or []:
        key = ((q.get("label") or "").strip().upper(),
               (q.get("country") or "").strip().upper() or None,
               (q.get("unit") or "").strip().lower() or None)
        cands = list(q.get("candidates") or [])
        if not cands:
            cands = [{"value": q.get("value"), "unit": q.get("unit"),
                      "as_of": q.get("as_of"), "publisher": None,
                      "source_url": None,
                      "note": "the agent returned a single figure with no "
                              "competing sources"}]
        groups.setdefault(key, []).extend(cands)

    out = []
    for (label, country, unit), cands in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        banded = triangulate_one(cands, policy=policy, price_year=price_year)
        out.append({"label": label, "country": country, "unit": unit,
                    **banded})
    return out


def review_queue(triangulated: list[dict]) -> list[dict]:
    """The quantities a person should look at, and why.

    Separated out so the disagreement is something the interface can show,
    rather than a flag buried in an evidence blob. A conflict nobody is shown
    has been retained in the same sense a letter in a drawer has been
    answered.
    """
    return [{
        "label": t["label"], "country": t.get("country"),
        "conflict_group_id": t.get("conflict_group_id"),
        "flags": t["flags"],
        "band": {"low": str(t["low"]), "base": str(t["base"]),
                 "high": str(t["high"])} if t.get("base") is not None else None,
        "spread_share": t.get("spread_share"),
        "vintages": [c.get("as_of") for c in t.get("candidates") or []],
        "candidates": t.get("candidates"),
        "why": _why(t),
    } for t in triangulated if t.get("review_required")]


def _why(t: dict) -> str:
    reasons = []
    if MATERIAL_SPREAD in t["flags"]:
        reasons.append(
            f"sources disagree by {t['spread_share']:.0%} ({t['low']} to "
            f"{t['high']}), which is beyond the governed threshold - the "
            f"disagreement is the finding and is not resolved here")
    if NEWEST_DIVERGES in t["flags"]:
        reasons.append(
            f"the most recent source ({t.get('newest_year')}) states "
            f"{t.get('newest_value')} against a median of {t['base']}. That is "
            f"either a trend or an outlier and the arithmetic cannot tell "
            f"which")
    if UNIT_MISMATCH in t["flags"]:
        reasons.append("candidates use different units, so they are counting "
                       "different things")
    return "; ".join(reasons)
