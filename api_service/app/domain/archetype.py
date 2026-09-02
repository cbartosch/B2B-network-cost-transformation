"""What the simulation is told about each site type, and where each part came from.

The simulation used site counts and nothing else. Every product pair,
dual-access probability, bandwidth and users-per-site came from
reference.archetype_prior, so research or an analyst could establish that a
client runs dual MPLS at 60% of branches and the model would still use the
seeded 0.55. Counts were evidence-driven and topology was not, which caps how
much refinement is possible: promoting research could move coverage and could
never make the topology less assumed.

Four layers, weakest first, each overriding the last:

  1 SEEDED_PRIOR      reference.archetype_prior - a global default
  2 INDUSTRY_DEFAULT  reference.archetype_bandwidth for this case's sector
  3 KNOWN_FACT        what the team asserted in the register, case-scoped
  4 PROMOTED_RESEARCH what this case's research established, case-scoped

The order is the confidence model's order, applied to topology: reference is
weaker than an attributed assertion, and an assertion is weaker than public
evidence. It is the same ladder that decides whether a site count lifts a
ceiling, so a client-specific finding about architecture is treated the way a
client-specific finding about counts already was.

**Every dimension reports its layer.** A reader can see which parts of the
topology are evidence and which are still seeded assumptions - the whole value
of establishing one is being able to tell the difference.
"""
from sqlalchemy import select

from .. import db

FIELDS = ("primary_product", "backup_product", "dual_access_probability",
          "users_base", "bandwidth_mbps_base")

# Weakest first. A layer only overrides one below it, never above.
# Named EVIDENCE_LAYERS, not LAYERS. estimate.py has its own LAYERS - L0 to L4
# and OPS, the cost layers - and two unrelated vocabularies under one name is
# how a reader imports the wrong one and a checker cannot tell them apart.
EVIDENCE_LAYERS = ("SEEDED_PRIOR", "INDUSTRY_DEFAULT", "KNOWN_FACT",
                   "PROMOTED_RESEARCH")

# Register classes whose subject may name an archetype. A fact filed under one
# of these, about a site type, is a statement about how that site type is built.
ARCHITECTURE_CLASSES = (
    "Current architecture hypothesis",
    "Current vendor and product signals",
    "Resilience assumptions",
    "Remote-user population",
)


def _coerce(field: str, raw):
    """A stored string into the type the simulation expects, or None."""
    if raw is None:
        return None
    try:
        if field in ("primary_product", "backup_product"):
            text = str(raw).strip().upper()
            return text or None
        if field == "dual_access_probability":
            return min(1.0, max(0.0, float(raw)))
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def resolve(session, *, case_id: str, seeded: dict,
            industry_bandwidth: dict | None = None) -> tuple:
    """(archetypes, basis).

    `seeded` is the global prior as loaded from reference.archetype_prior;
    it is not mutated. `basis` records, per archetype and field, the value used
    and the layer it came from - so a simulation can be read for which of its
    assumptions are still assumptions.
    """
    resolved = {name: dict(fields) for name, fields in (seeded or {}).items()}
    basis = {}

    def _set(archetype, field, value, layer, **extra):
        if archetype not in resolved or value is None:
            return
        resolved[archetype][field] = value
        basis[f"{archetype}.{field}"] = {"value": value, "layer": layer, **extra}

    # 1 - the seeded prior, as the baseline every field starts from
    for archetype, fields in resolved.items():
        for field in FIELDS:
            if field in fields:
                basis[f"{archetype}.{field}"] = {"value": fields[field],
                                                 "layer": "SEEDED_PRIOR"}

    # 2 - the industry bandwidth default for this case's sector
    for archetype, mbps in (industry_bandwidth or {}).items():
        _set(archetype, "bandwidth_mbps_base", _coerce("bandwidth_mbps_base", mbps),
             "INDUSTRY_DEFAULT")

    # 3 and 4 - what this case established. Ordered so research overwrites an
    # assertion about the same dimension rather than racing it.
    rows = session.execute(select(db.evidenced_archetype).where(
        db.evidenced_archetype.c.case_id == case_id)).all()
    for origin in ("KNOWN_FACT", "PROMOTED_RESEARCH"):
        for row in rows:
            if row.origin != origin:
                continue
            _set(row.archetype, row.field, _coerce(row.field, row.value),
                 origin, domain_no=row.domain_no,
                 known_fact_id=row.known_fact_id,
                 grade=row.reliability_grade, recorded_by=row.recorded_by)

    return resolved, {
        "by_field": dict(sorted(basis.items())),
        "layers": list(EVIDENCE_LAYERS),
        "evidenced_fields": sorted(
            k for k, v in basis.items()
            if v["layer"] in ("KNOWN_FACT", "PROMOTED_RESEARCH")),
        "assumed_fields": sorted(
            k for k, v in basis.items()
            if v["layer"] in ("SEEDED_PRIOR", "INDUSTRY_DEFAULT")),
        "note": (
            "A field on SEEDED_PRIOR or INDUSTRY_DEFAULT is an assumption this "
            "case has not tested. Research the relevant domain and promote the "
            "finding, or register what the team knows, to replace it - the "
            "simulation is a sizing instrument either way (0.3B), but an "
            "instrument calibrated to this client sizes it better."),
    }


def from_known_facts(session, *, case_id: str) -> list[dict]:
    """Archetype statements sitting in the known-facts register.

    Read rather than written on registration, so a fact edited on page 2 takes
    effect without a second promotion step - the register is the record and
    this is a view of it.

    A fact qualifies when its class is about architecture and its subject names
    an archetype: "Resilience assumptions / BRANCH / 0.6 dual access share" is
    a statement about how branches are built. Anything else is left alone.
    """
    from . import promotion

    rows = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_id)).all()
    found = []
    for row in rows:
        if row.fact_class not in ARCHITECTURE_CLASSES:
            continue
        subject = str(row.subject or "").strip().upper()
        if subject not in promotion.ARCHETYPES:
            continue
        # The register stores a number in value_base and a product cannot go
        # there, so a product override has to come from the unit wording.
        candidate = {"label": subject, "unit": row.unit,
                     "value": (str(row.value_base)
                               if row.value_base is not None else row.unit)}
        field = promotion.archetype_field(candidate)
        if not field:
            continue
        found.append({
            "archetype": subject, "field": field,
            "value": str(row.value_base) if row.value_base is not None else None,
            "known_fact_id": row.known_fact_id,
            "corroboration_state": row.corroboration_state,
            "asserted_by": row.asserted_by,
        })
    return found
