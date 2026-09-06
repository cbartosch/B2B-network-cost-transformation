"""What a site needs, against what can be delivered where it is.

The archetype says a branch wants DIA at 100 Mbps. It does not say whether
anyone can deliver that at the site's address, and for a large retail estate
that is the single biggest cost differentiator: a discounter in Munich has
fibre or DOCSIS, the same format in the Eifel may have only DSL or need fixed
wireless. Same archetype, same country, same format - a different circuit.

Domain 18 researches exactly this and its result reached nothing, so a
4,000-store estate was priced as though every store could take the same
product.

Three outcomes, and the third is the one that matters:

  DELIVERED     the product the archetype asked for is available at the
                bandwidth it asked for.
  SUBSTITUTED   it is not, and something else is - a rural store takes
                BROADBAND_HFC where an urban one takes DIA. Recorded with what
                was asked for, so a reader can see the estate is not uniform.
  UNSERVICEABLE nothing the archetype can use is available. The site is
                reported, not priced. An estimate that prices a circuit nobody
                can deliver is worse than one that says it cannot be delivered,
                because the first reads as a number and the second reads as a
                question.

**Density is a proxy, not the answer.** It is used because a postcode gives it
without a survey, and serviceability itself needs a regulator lookup per area.
A researched fact about a specific area replaces it, the same way a promoted
archetype field replaces a seeded prior.
"""
from sqlalchemy import select

from .. import db
from . import access

DELIVERED = "DELIVERED"
SUBSTITUTED = "SUBSTITUTED"
UNSERVICEABLE = "UNSERVICEABLE"

# Preference order when the asked-for product cannot be delivered. Dedicated
# access first, then shared, then mobile - which is the order of how much a
# circuit can be relied on, not how much it costs. A cheaper substitute that
# cannot carry the traffic is not a substitute.
FALLBACK_ORDER = ("DIA", "ETHERNET", "MPLS", "BROADBAND_HFC",
                  "BROADBAND_PON", "MOBILE_5G")


def load(session, countries: list[str] | None = None) -> dict:
    """Governed serviceability, keyed (country, density_band, product)."""
    query = select(db.serviceability)
    if countries:
        query = query.where(db.serviceability.c.country.in_(
            [c.upper() for c in countries]))
    return {(r.country, r.density_band, r.product): r
            for r in session.execute(query).all()}


def _by_access(*, table: dict, country: str, density: str,
               service_class: str, wanted_mbps: int, asked_for: str) -> dict:
    """The first bearer that reaches this site and can carry this service.

    Walks access.SERVICE_ACCESS in preference order. An entry absent from the
    table is unknown rather than unavailable - the same rule the product-keyed
    resolver used, and for the same reason: an empty table must not read as an
    estate nobody can serve.
    """
    carriers = access.carriers_for(service_class)
    known = [t for t in carriers if (country, density, t) in table]
    if not known:
        # Nothing recorded about any bearer this service could use. Silence,
        # not a constraint.
        return {"product": asked_for, "bandwidth_mbps": wanted_mbps,
                "outcome": DELIVERED, "asked_for": asked_for,
                "access_technology": None,
                "note": (f"no bearer for a {service_class} is recorded in "
                         f"{density} {country}, so nothing is known rather "
                         f"than nothing deliverable")}

    for technology in known:
        row = table[(country, density, technology)]
        if not getattr(row, "available", False):
            continue
        capacity = getattr(row, "max_bandwidth_mbps", None)
        if capacity is None or int(capacity) >= int(wanted_mbps or 0):
            return {"product": asked_for, "access_technology": technology,
                    "bandwidth_mbps": wanted_mbps, "outcome": DELIVERED,
                    "asked_for": asked_for, "note": None}
        # Reaches the site but not at this size. Reported as a substitution
        # rather than a refusal, because a smaller circuit is a real option and
        # a silent downgrade is not.
        return {"product": asked_for, "access_technology": technology,
                "bandwidth_mbps": int(capacity), "outcome": SUBSTITUTED,
                "asked_for": asked_for,
                "note": (f"{technology} reaches {density} {country} at "
                         f"{capacity} Mbps, below the {wanted_mbps} Mbps this "
                         f"site asked for")}

    return {"product": None, "access_technology": None,
            "bandwidth_mbps": None, "outcome": UNSERVICEABLE,
            "asked_for": asked_for,
            "note": (f"no bearer that can carry a {service_class} is "
                     f"available in {density} {country} - "
                     f"{', '.join(known)} are recorded and none is "
                     f"deliverable")}


def resolve(*, table: dict, country: str, density: str | None,
            product: str, wanted_mbps: int,
            # The structured speed pair, where the caller has one.
            #
            # Deliverability is judged on the *bearer*, not on what was
            # committed across it. An IPVPN at 100/30 needs a 100 Mbps circuit
            # installed; asking whether 30 Mbps is available would call it
            # serviceable wherever 30 is deliverable, which is not what has to
            # be built. The opposite rate to the one the price is keyed on, and
            # the reason the pair carries both.
            speed: dict | None = None,
            # The service class, where the caller has one. When supplied the
            # question changes: not "is this product sold here" but "does a
            # bearer reach this site that can carry this service".
            #
            # A carrier sells MPLS wherever it can reach, so the old question
            # answered itself. An IPVPN in a rural town is deliverable if VDSL
            # reaches it - true, and the product-keyed table could not say so.
            service_class: str | None = None) -> dict:
    """What this site actually gets, and why.

    With no density band the site is unclustered, and nothing is known about
    what can be delivered there - so it gets what it asked for, exactly as the
    model behaved before serviceability existed. Silence is not a constraint.
    """
    # Sized on the bearer. See the note on the parameter.
    if speed is not None:
        wanted_mbps = access.sizing_rate(speed)

    # Resolved on the bearer too, where the caller knows the service class.
    if service_class is not None and density:
        return _by_access(table=table, country=country, density=density,
                          service_class=service_class,
                          wanted_mbps=wanted_mbps, asked_for=product)
    if not density:
        return {"product": product, "bandwidth_mbps": wanted_mbps,
                "outcome": DELIVERED, "asked_for": product,
                "note": "no density band on this row, so nothing is known "
                        "about what can be delivered - priced as asked."}

    key = (country.upper(), density.upper())

    # Nothing known about this country and band at all. Same rule as a missing
    # density band: silence is not a constraint.
    #
    # This reported "10 sites in URBAN DE cannot be served at all" - impossible,
    # since every product is deliverable there in the seed - because an empty
    # table made every lookup miss and the fallback loop then found nothing
    # available. Absence of data was being read as evidence of absence, which is
    # the error this module exists to avoid making in the other direction.
    if not any(k[0] == key[0] and k[1] == key[1] for k in table):
        return {"product": product, "bandwidth_mbps": wanted_mbps,
                "outcome": DELIVERED, "asked_for": product,
                "note": (f"no serviceability recorded for {density} "
                         f"{country}, so nothing is known about what can be "
                         f"delivered - priced as asked. Seed or retune "
                         f"reference.serviceability to constrain it.")}

    asked = table.get((*key, product))

    if asked is not None and asked.available:
        cap = asked.max_bandwidth_mbps
        if cap is None or cap >= wanted_mbps:
            return {"product": product, "bandwidth_mbps": wanted_mbps,
                    "outcome": DELIVERED, "asked_for": product, "note": None}
        # Available but not at the tier asked for. The circuit is real and the
        # bandwidth is not, which is a substitution of tier rather than of
        # product - and pricing it at the tier nobody can deliver would be the
        # same error as pricing an unavailable product.
        return {"product": product, "bandwidth_mbps": cap,
                "outcome": SUBSTITUTED, "asked_for": product,
                "note": (f"{product} is available in {density} {country} but "
                         f"only to {cap} Mbps, not the {wanted_mbps} Mbps this "
                         f"site type asks for.")}

    for candidate in FALLBACK_ORDER:
        if candidate == product:
            continue
        row = table.get((*key, candidate))
        if row is not None and row.available:
            cap = row.max_bandwidth_mbps or wanted_mbps
            return {"product": candidate, "bandwidth_mbps": min(cap, wanted_mbps),
                    "outcome": SUBSTITUTED, "asked_for": product,
                    "note": (f"{product} cannot be delivered in {density} "
                             f"{country}; {candidate} can, to "
                             f"{min(cap, wanted_mbps)} Mbps.")}

    return {"product": None, "bandwidth_mbps": None,
            "outcome": UNSERVICEABLE, "asked_for": product,
            "note": (f"nothing this site type can use is deliverable in "
                     f"{density} {country}. Reported rather than priced: an "
                     f"estimate that prices a circuit nobody can deliver reads "
                     f"as a number, and this is a question.")}


def resolve_backup(*, table: dict, country: str, density: str | None,
                   product: str, wanted_mbps: int,
                   primary_product: str | None,
                   # Who supplies each path, where the case records it. A
                   # stronger test than the product: two different products
                   # from one carrier still share a duct, and a challenger
                   # reselling the incumbent's fibre is one physical path
                   # wearing two names.
                   #
                   # Each is a list, because a country has more than one
                   # provider and the model cannot know which one serves a
                   # given site - so it asks whether diversity is *possible*
                   # here, not which carrier this site got.
                   primary_providers: list | None = None,
                   backup_providers: list | None = None,
                   speed: dict | None = None) -> dict:
    """What a site's second access path actually gets, if anything.

    The backup went straight from the archetype prior into the circuit count,
    the edge list and `dual_sites` without ever being resolved - so a rural
    LARGE_OFFICE was counted dual-access on a DIA backup that the same
    serviceability table says cannot be delivered there. That is a resilience
    claim, not a cost error, and an audit is right to treat it as the more
    serious of the two.

    Two rules the primary does not need:

    **A backup on the same product as the primary is not a second path.** Two
    DIA circuits from the same carrier over the same duct fail together. The
    simulation cannot know the duct, but it can know the product, and calling
    two identical services diverse is the assumption that makes a resilience
    number worthless. Where the substitution lands back on the primary's
    product, the site is single-access.

    **An unserviceable backup does not become a cheaper backup.** If nothing
    else can be delivered, the site has one path - reported, not silently
    priced as two.

    **And a second product from the same carrier is not a second carrier.**
    The product rule above is a proxy for the thing that matters, and a proxy
    the moment a case records who actually supplies it. Where the only recorded
    providers are the same on both paths, the site is not carrier-diverse
    however different the two products look - which is the claim a client
    tests hardest.
    """
    # Sized on the bearer. See the note on the parameter.
    if speed is not None:
        wanted_mbps = access.sizing_rate(speed)
    served = resolve(table=table, country=country, density=density,
                     product=product, wanted_mbps=wanted_mbps)
    if served["outcome"] == UNSERVICEABLE:
        return {**served, "resilient": False,
                "note": (f"no second access path is deliverable in "
                         f"{density} {country}, so this site has one path "
                         f"however the archetype's dual-access draw fell.")}

    if primary_product and served["product"] == primary_product:
        # A substitution that lands on the primary's own product.
        return {**served, "outcome": UNSERVICEABLE, "product": None,
                "bandwidth_mbps": None, "resilient": False,
                "note": (f"the only backup deliverable in {density} {country} "
                         f"is {primary_product}, which is what the primary "
                         f"already uses. Two of the same service is not a "
                         f"second path - counting it as diversity is the "
                         f"assumption that makes a resilience number "
                         f"worthless.")}

    # Carrier diversity, where the case knows who supplies what. Absent
    # provider records this is silent rather than negative: the estate is not
    # single-carrier because nobody wrote the carriers down.
    if primary_providers and backup_providers:
        shared = set(primary_providers) & set(backup_providers)
        if shared and not (set(backup_providers) - shared):
            return {**served, "resilient": False,
                    "carrier_diverse": False,
                    "note": (f"the only provider recorded for a second path in "
                             f"{country} is {sorted(shared)}, which also "
                             f"supplies the primary. A second product from one "
                             f"carrier is not a second carrier - it is the "
                             f"same duct with a different service on it.")}
        return {**served, "resilient": True, "carrier_diverse": True,
                "note": (f"second path from "
                         f"{sorted(set(backup_providers) - shared)}, distinct "
                         f"from the primary's supplier")}

    return {**served, "resilient": True, "carrier_diverse": None}


def summarise(outcomes: list[dict]) -> dict:
    """What the estate's serviceability did to it, for a reader.

    A count per outcome plus the substitutions actually made, because "412
    sites took a different product from the one their type asks for" is the
    finding, and a percentage is not.
    """
    counts = {DELIVERED: 0, SUBSTITUTED: 0, UNSERVICEABLE: 0}
    swaps: dict[tuple, int] = {}
    for entry in outcomes:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        if entry["outcome"] == SUBSTITUTED:
            key = (entry.get("asked_for"), entry.get("product"),
                   entry.get("bandwidth_mbps"))
            swaps[key] = swaps.get(key, 0) + 1
    total = sum(counts.values())
    return {
        "counts": counts,
        "substitutions": [
            {"asked_for": a, "delivered": d, "bandwidth_mbps": m, "sites": n}
            for (a, d, m), n in sorted(swaps.items(), key=lambda kv: -kv[1])],
        "unserviceable": counts[UNSERVICEABLE],
        "note": (
            f"{counts[SUBSTITUTED]} of {total} site(s) take a different product "
            f"or tier from the one their type asks for, and "
            f"{counts[UNSERVICEABLE]} can be served by nothing at all. A "
            f"uniform estate is an assumption; this is what the density bands "
            f"say about it."
            if total else "No sites to check."),
    }
