"""How much of the estate is named, and what that is worth.

The footprint is a count per country and site type. That stores "371 branches
in Germany" and a list of 371 addresses identically, and the second is far
better evidence - so this holds the named ones and reports what share of the
estate they cover.

**The list never overrides the total.** The total usually comes from a filing;
the list from a store locator, which is partial by nature, may include closed
sites, and is often paginated behind script a fetch cannot read. So the list is
evidence *for* the count. Where the enumeration exceeds the total, that is a
conflict to surface - either the locator includes sites outside the perimeter,
or the filing is stale - and not a licence to raise the total.

**The residual is inferred and says so.** 47 named sites out of 350 leaves 303
that still need a type to be priced. Applying the enumerated mix to them is
defensible and it is an inference, so that share of the estate carries
PUBLIC_DERIVED rather than the enumerated share's origin. One decision, and
confidence then falls out with no new weighting: a case with 47 of 350 named
reports a weaker origin mix than one with 340 of 350, automatically.

**No fabricated rows.** A residual is a count, not 303 anonymous locations.
Nothing here invents a location record, and a reader can always tell which
sites exist as named rows and which are a tally.

**Duplicates are flagged, not merged.** A locator's "Wuerth Niederlassung
Berlin-Spandau" and a filing appendix's "Berlin Spandau" are one site, and any
key that decides that will be wrong sometimes. Suspicion is recorded for a
person to settle, the way a triangulation conflict is.
"""
import re
import unicodedata
from decimal import Decimal

from sqlalchemy import select

from .. import db

DERIVED_ORIGIN = "PUBLIC_DERIVED"

# The origin ladder lives in refinement.py, which owns the concept: it is the
# module that attributes a movement in confidence to a shift in the origin mix.
#
# Two copies existed here and there, identical - which is how this defect stays
# invisible until one is edited. A second ladder would silently rank the same
# evidence differently in two places, and the one that drifted would be the one
# nobody was reading.
from .refinement import ORIGIN_RANK




def _residual_origin(enumerated_origin: str) -> str:
    """The weaker of PUBLIC_DERIVED and the origin the footprint already had."""
    if ORIGIN_RANK.get(enumerated_origin, 0) <= ORIGIN_RANK[DERIVED_ORIGIN]:
        return enumerated_origin
    return DERIVED_ORIGIN


def _key(row) -> str:
    """A comparison key for duplicate suspicion, deliberately crude.

    Accents folded, legal and branch words dropped, ordering ignored: a locator
    writing "Niederlassung Berlin-Spandau" and an appendix writing "Berlin
    Spandau" reduce to the same token set. Crude enough to be wrong sometimes,
    which is why it flags rather than merges.
    """
    text = " ".join(str(getattr(row, f, None) or "") for f in ("city", "name"))
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.split(r"[^a-z0-9]+", text)
    drop = {"niederlassung", "filiale", "branch", "store", "shop", "gmbh",
            "ag", "kg", "co", "ltd", "plc", "sa", "bv", "nv", "the", "und",
            "and", ""}
    # A set, not a list: "Berlin" appearing in both the city and the name gave
    # "berlin berlin spandau", which failed to match "berlin spandau" - the
    # exact pair this is for.
    return " ".join(sorted(set(w for w in words if w not in drop)))


def suspected_duplicates(rows: list) -> list[dict]:
    """Pairs that look like one site under two names."""
    by_key = {}
    found = []
    for row in rows:
        key = (str(getattr(row, "country", "") or "").upper(), _key(row))
        if not key[1]:
            continue
        if key in by_key:
            found.append({
                "location_id": getattr(row, "location_id", None),
                "duplicate_of": by_key[key],
                "key": key[1],
                "note": ("these reduce to the same city and name once accents, "
                         "legal forms and branch words are dropped. Confirm or "
                         "dismiss - nothing is merged automatically, because "
                         "the key that decided this will be wrong sometimes."),
            })
        else:
            by_key[key] = getattr(row, "location_id", None)
    return found


def enumeration(session, *, case_id: str, footprint: list[dict]) -> dict:
    """What share of each country's estate is named, and the residual mix.

    `footprint` is the resolved count per (country, archetype). The result is
    keyed by country because that is what a priced component carries - a
    product row knows its country and not its archetype - and because a
    per-country ratio is the one worth reading: "Germany 95% named, US 4%"
    says both how solid the estimate is and where to look next.
    """
    rows = session.execute(select(db.location).where(
        db.location.c.case_id == case_id,
        db.location.c.suspected_duplicate_of.is_(None))).all()

    totals, named = {}, {}
    for row in footprint or []:
        country = str(row.get("country") or "").upper()
        if not country:
            continue
        totals[country] = totals.get(country, 0) + int(row.get("sites") or 0)
    for row in rows:
        country = str(row.country or "").upper()
        named.setdefault(country, []).append(row)

    by_country, conflicts = {}, []
    for country in sorted(set(totals) | set(named)):
        total = totals.get(country, 0)
        listed = named.get(country, [])
        count = len(listed)

        if total and count > total:
            # Reported, never resolved by raising the total. The list may
            # include sites outside the perimeter, or the filing may be stale,
            # and only a person can say which.
            conflicts.append({
                "country": country, "enumerated": count, "total": total,
                "note": (f"{count} named location(s) in {country} against a "
                         f"registered total of {total}. The list does not "
                         f"raise the total: either it includes sites outside "
                         f"the perimeter, or the total is stale. Resolve it on "
                         f"page 2 or by removing the out-of-perimeter rows."),
            })

        ratio = (Decimal(min(count, total)) / Decimal(total)) if total else Decimal(0)
        mix = {}
        for row in listed:
            archetype = str(row.archetype or "").upper()
            if archetype:
                mix[archetype] = mix.get(archetype, 0) + 1
        by_country[country] = {
            "total": total,
            "enumerated": count,
            "enumerated_share": str(ratio.quantize(Decimal("0.001"))),
            "residual": max(0, total - count),
            # The mix the residual inherits, as observed shares. Empty where
            # nothing is named: the footprint row's own archetype then stands,
            # which is exactly how the estimate behaves today.
            "enumerated_mix": {k: v for k, v in sorted(mix.items())},
            "grades": sorted({str(r.reliability_grade) for r in listed
                              if r.reliability_grade}),
        }

    overall_total = sum(v["total"] for v in by_country.values())
    overall_named = sum(min(v["enumerated"], v["total"]) if v["total"]
                        else 0 for v in by_country.values())
    return {
        "by_country": by_country,
        # The share of the whole estate that exists as a named row. Reported
        # rather than weighted: it reaches confidence through the origin mix,
        # because the residual carries PUBLIC_DERIVED.
        "enumerated_share": str(
            (Decimal(overall_named) / Decimal(overall_total)).quantize(
                Decimal("0.001")) if overall_total else Decimal(0)),
        "enumerated": overall_named,
        "total": overall_total,
        "conflicts": conflicts,
        "duplicates": suspected_duplicates(rows),
        "note": (
            f"{overall_named} of {overall_total} site(s) exist as a named "
            f"location. The rest are a tally: real, counted, and not "
            f"individually known. The unnamed share is priced by applying the "
            f"named mix to it, which is an inference - so it carries "
            f"{DERIVED_ORIGIN} and lowers the origin mix accordingly."
            if overall_total else
            "No footprint yet, so there is nothing to enumerate against."),
    }


def origin_split(enumeration_result: dict, country: str,
                 enumerated_origin: str) -> list[tuple]:
    """[(origin, share)] for one country's site-driven value.

    The estimate carries one origin per driver, so a footprint that is part
    named and part tallied cannot be described by a single label. This returns
    the split, and the caller apportions each site-driven component's value
    across it - deterministically, by exact share, never by sampling.
    """
    entry = (enumeration_result.get("by_country") or {}).get(country.upper())
    if not entry or not entry["total"]:
        return [(enumerated_origin, Decimal(1))]
    share = Decimal(entry["enumerated_share"])
    if share <= 0:
        # Nothing named here, so there is no observed mix to infer from and
        # nothing to downgrade or upgrade: the country is priced exactly as it
        # is today. Returning PUBLIC_DERIVED would have improved the origin of
        # a typed footprint for having no locations at all.
        return [(enumerated_origin, Decimal(1))]
    if share >= 1:
        return [(enumerated_origin, Decimal(1))]
    return [(enumerated_origin, share),
            (_residual_origin(enumerated_origin), Decimal(1) - share)]
