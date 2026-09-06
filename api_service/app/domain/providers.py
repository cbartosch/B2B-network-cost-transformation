"""Who supplies what, and where.

Specification 0.4: vendor/product signals prepopulate `provider`, `product` and
`current_architecture_hypothesis`, with the control "Treat as hypothesis until
client evidence confirms."

The workbench had no concept of a carrier at all. Research domain 8 gathers
exactly this - "which network and security vendors, carriers and partners the
entity actually uses" - and promotion had nowhere to put the answer, so every
finding about a supplier was displayed once and lost.

**A site has more than one provider, and that is the normal case, not an edge
case.** Two reasons, and they are different:

  Resilience    a second access path from a second carrier is the point of
                having one. A model that allows a site one provider cannot
                express carrier diversity, which is the thing the estimate is
                supposed to be measuring.

  Geography     no carrier serves every country. An international estate is a
                patchwork by construction: an incumbent here, a challenger
                there, a local partner where neither reaches. "One global
                supplier" is a target state that a transformation might reach,
                never an assumption about today.

So the relationship is provider-to-scope-to-role, not provider-to-case. A
single-provider assumption would have been quicker to build and would have made
the diversity work of 4.157 unmeasurable.
"""
from decimal import Decimal

# What a provider does in a given place. Not a hierarchy: an incumbent in one
# country is a challenger in the next, and a reseller of one carrier's fibre
# may be the prime contractor for the whole estate.
INCUMBENT = "INCUMBENT"          # the historic national operator
CHALLENGER = "CHALLENGER"        # a facilities-based competitor
RESELLER = "RESELLER"            # sells another carrier's access
AGGREGATOR = "AGGREGATOR"        # assembles many carriers under one contract
MSP = "MSP"                      # manages, may or may not supply access
VENDOR = "VENDOR"                # equipment or software, not connectivity

PROVIDER_KINDS = (INCUMBENT, CHALLENGER, RESELLER, AGGREGATOR, MSP, VENDOR)

# Why this provider is at this site. The distinction that makes diversity
# measurable: two providers in the same role is redundancy, two in different
# roles is a supply chain.
PRIMARY = "PRIMARY"
BACKUP = "BACKUP"
OVERLAY = "OVERLAY"              # SD-WAN, SSE - rides someone else's access
MANAGEMENT = "MANAGEMENT"        # operates it, supplies nothing
ROLES = (PRIMARY, BACKUP, OVERLAY, MANAGEMENT)

# How sure we are. A public signal is a hypothesis until the client confirms
# it, which is the spec's control and the reason this is not just a field on a
# site record.
HYPOTHESIS = "HYPOTHESIS"        # inferred from a public signal
CLIENT_STATED = "CLIENT_STATED"  # the client said so
EVIDENCED = "EVIDENCED"          # an invoice or contract shows it
STANDINGS = (HYPOTHESIS, CLIENT_STATED, EVIDENCED)


class ProviderInvalid(ValueError):
    """A supply relationship that could not be true."""


def relationship(*, provider: str, kind: str, role: str, country: str,
                 service_class: str | None = None, standing: str = HYPOTHESIS,
                 share=None, source: str | None = None) -> dict:
    """One provider supplying one role in one country.

    `share` is the portion of that country's sites this provider serves, where
    anyone knows it. Optional and often unknown: a press release naming a
    carrier says nothing about how much of the estate it carries, and a default
    of 1.0 would turn a mention into an exclusive.
    """
    if kind not in PROVIDER_KINDS:
        raise ProviderInvalid(f"{kind!r} is not one of {list(PROVIDER_KINDS)}")
    if role not in ROLES:
        raise ProviderInvalid(f"{role!r} is not one of {list(ROLES)}")
    if standing not in STANDINGS:
        raise ProviderInvalid(f"{standing!r} is not one of {list(STANDINGS)}")
    if not str(provider or "").strip():
        raise ProviderInvalid("a supply relationship needs a named provider")

    portion = None if share in (None, "") else Decimal(str(share))
    if portion is not None and not (Decimal(0) < portion <= Decimal(1)):
        raise ProviderInvalid(
            f"a share of {portion} is not a portion of a country's sites. "
            f"Zero means the provider is not there, which is an absent row "
            f"rather than a row saying nothing.")

    if standing == HYPOTHESIS and not source:
        raise ProviderInvalid(
            "a hypothesis needs the signal it came from. An unsourced guess "
            "about who supplies a client is the kind of thing that ends up in "
            "a slide, and the control on this table is that it stays a "
            "hypothesis until the client confirms it.")

    return {"provider": str(provider).strip(), "kind": kind, "role": role,
            "country": str(country or "").upper() or None,
            "service_class": service_class, "standing": standing,
            "share": None if portion is None else str(portion),
            "source": source}


def diversity(relationships: list, *, country: str) -> dict:
    """Whether this country's access is carrier-diverse, and on what evidence.

    Two providers in the same role is redundancy. Two in different roles is a
    supply chain: a carrier and the MSP that manages it are not diversity, and
    counting them as such is the mistake this function exists to prevent.

    Note what it does not claim. Two carriers is carrier diversity and says
    nothing about local-loop, duct or building-entry diversity - a challenger
    reselling the incumbent's fibre is one physical path wearing two names, and
    `kind` is what makes that visible.
    """
    here = [r for r in relationships
            if (r.get("country") or "").upper() == (country or "").upper()]
    access = [r for r in here if r.get("role") in (PRIMARY, BACKUP)]
    names = {r["provider"] for r in access}
    resellers = {r["provider"] for r in access if r.get("kind") == RESELLER}

    diverse = len(names) > 1
    caveats = []
    if diverse and resellers:
        caveats.append(
            f"{sorted(resellers)} resell another carrier's access, so the "
            f"underlying path may be shared - two names is not two ducts")
    if diverse and all(r.get("standing") == HYPOTHESIS for r in access):
        caveats.append(
            "every relationship here is a hypothesis from a public signal; "
            "carrier diversity claimed on that basis is a research finding "
            "rather than a fact about the estate")
    if not diverse and len(here) > 1:
        caveats.append(
            "more than one provider is recorded but only one supplies access; "
            "the others manage or overlay it, which is a supply chain rather "
            "than diversity")

    return {"country": (country or "").upper(),
            "access_providers": sorted(names),
            "carrier_diverse": diverse,
            "standing": (min((r.get("standing") for r in access),
                             key=lambda s: STANDINGS.index(s))
                         if access else None),
            "caveats": caveats,
            "note": (f"{len(names)} access provider(s) recorded"
                     if here else
                     f"no provider is recorded for {country}, which is not "
                     f"the same as a single-carrier estate")}


def coverage(relationships: list, *, countries: list) -> dict:
    """Which in-scope countries have a supplier recorded and which do not.

    An unrecorded country is a gap, not a single-provider assumption. The
    difference matters because one of them belongs in the assumption register
    and the other is a finding about the client.
    """
    known = {(r.get("country") or "").upper() for r in relationships
             if r.get("role") in (PRIMARY, BACKUP)}
    wanted = {(c or "").upper() for c in countries}
    missing = sorted(wanted - known)
    return {
        "countries_with_a_provider": sorted(wanted & known),
        "countries_without": missing,
        "note": (f"{len(missing)} in-scope country/countries have no supplier "
                 f"recorded. That is an open question rather than an estate "
                 f"served by nobody, and it belongs in the assumption register."
                 if missing else
                 "every in-scope country has at least one access provider "
                 "recorded"),
    }
