"""Seeded topology and architecture simulation (spec 0.3B).

Contract:
  - Output is a function of (model_version, seed, pinned priors) and nothing else.
    No wall-clock, no os.urandom, no dict-ordering dependence.
  - Output lives in outside_in.* only. Nothing here writes a topology graph,
    and nothing here can set a diversity state other than SIMULATED.
  - Re-running with the same seed reproduces a byte-identical payload; the
    output_hash is stored so that is checkable rather than asserted.
"""
import hashlib
import json
import random
from statistics import median

from . import access, serviceability

DIVERSITY_STATE = "SIMULATED"          # 0.3B may never emit any other value


def _rng(seed: int, salt: str) -> random.Random:
    # Derive a per-purpose stream so adding a stage later does not shift
    # earlier draws and silently change historical output.
    h = hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


SAMPLE_NODES, SAMPLE_EDGES = 200, 400

# The largest estate carried whole on a run. Beyond this the list is truncated
# for storage and the count of what was dropped is reported - a JSON column is
# not a site register, and an estate of 40,000 outlets would make every
# simulation row unreadable to protect a list nobody scrolls.
MAX_ESTATE_ROWS = 5000


def one_pass(seed: int, footprint: list[dict], archetypes: dict,
             service_class_by_archetype: dict | None = None,
             backbone: dict | None = None,
             known_locations: list[dict] | None = None,
             service_table: dict | None = None) -> dict:
    """One synthetic estate, as a list of sites.

    The estate is materialised site by site rather than counted: every circuit
    now belongs to a row that says which site it is for, and every site says
    whether it is one somebody named or one this pass generated to make the
    count up. That is what a bottom-up model costs - sites, not tallies - and
    it makes the enumerated share concrete at the row level instead of a ratio.

    **A generated site is never dressed as a known one.** It carries no name,
    no address and no coordinates, and `known` is False. The distinction is
    structural, not a label: there is nowhere on a generated row to put an
    address, so nothing can drift into looking like one.

    `known_locations` are matched to (country, archetype) in the order given
    and consume the count before any are generated, so the named ones are
    always the first sites of their kind and a reader can see them at the top
    of the list.
    """
    rng = _rng(seed, "topology")
    nodes, edges = [], []
    primary = backup = 0
    dual_sites = 0
    products: dict[tuple, int] = {}
    # users_base and bandwidth_mbps_base were seeded on every archetype and read
    # by nothing - two dead reference columns. The footprint already implies a
    # headcount and a bandwidth profile; discarding them meant a 500-branch
    # estate and a 5-DC estate looked identical to the platform cost.
    implied_users = 0
    bandwidth_by_archetype: dict[str, dict] = {}

    # The estate itself. Bounded for storage further down, but built whole so
    # the aggregates are computed from it rather than beside it.
    site_rows: list[dict] = []
    # Sites nothing can serve, and what each cluster actually got.
    unserviceable: list[dict] = []
    service_outcomes: list[dict] = []
    # Sites the dual-access draw selected and serviceability could not give a
    # second path. Reported rather than absorbed: a dual_sites count that
    # silently shrinks reads as a weaker architecture rather than as a
    # constraint on what can be delivered.
    single_by_necessity: list[dict] = []
    # Inter-site transport, counted separately from access so a reader can see
    # which part of the estate a circuit total refers to.
    backbone_circuits = 0
    by_kind: dict[tuple, list] = {}
    for loc in known_locations or []:
        key = (str(loc.get("country") or "").upper(),
               str(loc.get("archetype") or "").upper())
        by_kind.setdefault(key, []).append(loc)

    for entry in sorted(footprint, key=lambda e: (e["country"], e["archetype"])):
        prior = archetypes.get(entry["archetype"], {})
        p_dual = float(prior.get("dual_access_probability", 0.5))
        primary_product = prior.get("primary_product", "DIA")
        backup_product = prior.get("backup_product", "BROADBAND_PON")
        # What is bought, as distinct from how it arrives. The analyst's choice
        # for this case wins over the seeded prior, and the prior's own class
        # is the fallback - derived from its product where an older row has not
        # been migrated.
        #
        # `primary_product` held both facts, so choosing BROADBAND_HFC for a
        # store asserted a delivery technology as well as a service level, and
        # a store served by PON instead came out as a substitution rather than
        # as the same decision met a different way.
        primary_class = (
            (service_class_by_archetype or {}).get(entry["archetype"])
            or prior.get("primary_service_class")
            or access.LEGACY_PRODUCT.get(primary_product, (None,))[0])
        backup_class = (
            prior.get("backup_service_class")
            or access.LEGACY_PRODUCT.get(backup_product, (None,))[0])
        users_base = int(prior.get("users_base") or 0)
        bw_base = int(prior.get("bandwidth_mbps_base") or 0)
        n_sites = int(entry["sites"])
        implied_users += users_base * n_sites
        agg = bandwidth_by_archetype.setdefault(
            entry["archetype"], {"sites": 0, "mbps_per_site": bw_base, "mbps_total": 0})
        agg["sites"] += n_sites
        agg["mbps_total"] += bw_base * n_sites

        kind = (entry["country"], entry["archetype"])
        named_here = list(by_kind.get(kind, ()))

        # What this cluster can actually be given, against what its type asks
        # for. A density band is optional: without one the row is unclustered
        # and priced exactly as before, because silence is not a constraint.
        density = (entry.get("density") or "").upper() or None
        served = serviceability.resolve(
            table=service_table or {}, country=entry["country"],
            density=density, product=primary_product, wanted_mbps=bw_base)
        if served["outcome"] == serviceability.UNSERVICEABLE:
            # Reported, not priced. An estimate that prices a circuit nobody
            # can deliver reads as a number; this reads as a question.
            unserviceable.append({
                "country": entry["country"], "archetype": entry["archetype"],
                "density": density, "sites": int(entry["sites"]),
                "asked_for": served["asked_for"], "reason": served["note"]})
            continue
        primary_product = served["product"]
        bw_base = int(served["bandwidth_mbps"])
        service_outcomes.extend([served] * int(entry["sites"]))

        for i in range(int(entry["sites"])):
            node_id = f"{entry['country']}-{entry['archetype']}-{i:04d}"
            # The named ones first, then generated rows to make the count up.
            # A generated row has no name, address or coordinates: there is
            # nowhere to put one, so it cannot drift into reading as known.
            known = named_here[i] if i < len(named_here) else None
            site_rows.append({
                "site_id": node_id, "country": entry["country"],
                "archetype": entry["archetype"],
                "known": known is not None,
                "name": (known or {}).get("name"),
                "city": (known or {}).get("city"),
                "address": (known or {}).get("address"),
                "latitude": (known or {}).get("latitude"),
                "longitude": (known or {}).get("longitude"),
                "source_url": (known or {}).get("source_url"),
                "as_of": (known or {}).get("as_of"),
                "reliability_grade": (known or {}).get("reliability_grade"),
                "location_id": (known or {}).get("location_id"),
                "users": users_base,
                "bandwidth_mbps": bw_base,
                "density": density,
                "primary_product": primary_product,
                "service_outcome": served["outcome"],
                "asked_for": served["asked_for"],
                "backup_product": None,
            })
            # Only a bounded display sample is materialised. An earlier revision
            # held full node and edge lists per pass, so peak memory was
            # O(ensemble x sites) rather than O(sites).
            if len(nodes) < SAMPLE_NODES:
                nodes.append({"node_id": node_id, "country": entry["country"],
                              "archetype": entry["archetype"], "class": "SITE"})
            if len(edges) < SAMPLE_EDGES:
                edges.append({"from": node_id, "to": f"POP-{entry['country']}",
                              "product": primary_product, "role": "PRIMARY",
                              # On the edge, not only in the aggregate. A
                              # circuit's bandwidth is the second half of what
                              # it costs, and a sample that shows the product
                              # without it shows half the circuit.
                              "bandwidth_mbps": bw_base,
                              "diversity_state": DIVERSITY_STATE})
            primary += 1
            # Keyed with the bandwidth the archetype implies, so the circuit
            # can be priced at the tier it actually needs rather than at
            # whatever rate happened to exist for the product.
            pkey = (entry["country"], primary_product, "PRIMARY", bw_base,
                    primary_class)
            products[pkey] = products.get(pkey, 0) + 1

            # The stochastic draw. Whether a site has a second access path is the
            # one thing this simulation actually decides - the primary count
            # follows deterministically from the supplied footprint. That is why
            # only the backup layer is attributed to SIMULATED downstream.
            if rng.random() < p_dual:
                # The backup is resolved too. It used to go straight from the
                # archetype prior into the circuit count, the edge list and
                # dual_sites - so a rural LARGE_OFFICE was counted dual-access
                # on a DIA backup that the same table says cannot be delivered
                # there. A resilience claim, not a cost error.
                backup_served = serviceability.resolve_backup(
                    table=service_table or {}, country=entry["country"],
                    density=density, product=backup_product,
                    wanted_mbps=bw_base, primary_product=primary_product)
                if not backup_served["resilient"]:
                    # The draw said this site should have a second path and
                    # none can be delivered. Recorded: an estate whose
                    # dual-access count silently shrinks reads as a weaker
                    # architecture rather than a serviceability constraint.
                    single_by_necessity.append({
                        "country": entry["country"],
                        "archetype": entry["archetype"], "density": density,
                        "asked_for": backup_product,
                        "reason": backup_served["note"]})
                else:
                    b_product = backup_served["product"]
                    b_mbps = int(backup_served["bandwidth_mbps"])
                    if len(edges) < SAMPLE_EDGES:
                        edges.append({"from": node_id,
                                      "to": f"POP2-{entry['country']}",
                                      "product": b_product, "role": "BACKUP",
                                      "bandwidth_mbps": b_mbps,
                                      "diversity_state": DIVERSITY_STATE})
                    backup += 1
                    dual_sites += 1
                    site_rows[-1]["backup_product"] = b_product
                    site_rows[-1]["backup_outcome"] = backup_served["outcome"]
                    bkey = (entry["country"], b_product, "BACKUP", b_mbps,
                            backup_class)
                    products[bkey] = products.get(bkey, 0) + 1

    # The backbone becomes priceable circuits.
    #
    # Audit finding C-06. topology.plan() produced the inter-site transport -
    # data centres to regional hubs, hubs to a global core - and one_pass
    # accepted the parameter and never read it. So the backbone was modelled,
    # displayed on the simulation page, and excluded from every cost: on a
    # two-DC EMEA estate that is 504,000 a year absent from the baseline.
    #
    # Keyed by region rather than country, matching the scope_kind=REGION
    # priors seeded for EMEA, AMER and APAC. A backbone link belongs to no
    # single country, and pricing it against one would put a global circuit on
    # whichever market happened to sort first.
    for link in (backbone or {}).get("links") or []:
        count = int(link.get("count") or 0)
        if count <= 0:
            continue
        circuits_here = count * (2 if link.get("dual") else 1)
        mbps = int(link.get("bandwidth_mbps") or 0)
        # role="BACKBONE", not the tier. The products key is
        # (scope, product, role, bandwidth) and role is PRIMARY or BACKUP
        # everywhere else - putting DC_TO_REGION in that slot would hand the
        # estimate a role it has never seen, and the tier is carried on the
        # link record where a reader can find it.
        # A backbone link is Ethernet transport by definition: it carries the
        # WAN between hubs rather than a site's internet access.
        key = (str(link["region"]), str(link["product"]), "BACKBONE", mbps,
               access.ETHERNET)
        products[key] = products.get(key, 0) + circuits_here
        backbone_circuits += circuits_here

    # Counted from the estate, not beside it. These used to be accumulated in
    # parallel with the loop that generated the circuits, so a change to one
    # could silently disagree with the other - and the site list is now the
    # thing the estimate is built on, so it has to be the thing that is
    # counted.
    sites = len(site_rows)
    dropped = sum(int(r["sites"]) for r in unserviceable)
    assert sites + dropped == sum(int(e["sites"]) for e in footprint), (
        "every site in the footprint must be either in the estate or reported "
        "as unserviceable - a site that is neither has been lost silently")
    # Access plus backbone. These were separate concepts and only one was
    # priced, so "circuits" meant access-only in the cost and everything in the
    # topology view.
    circuits = primary + backup + backbone_circuits
    named = sum(1 for r in site_rows if r["known"])
    return {"sites": sites, "circuits": circuits,
            # The estate, bounded. A full list is O(sites) per pass and the
            # ensemble runs many, so only the sample is carried here - the
            # median pass keeps the whole list, which is the one a reader
            # examines and the one the estimate is built from.
            # What the estate's density said about it: which clusters take a
            # different circuit from the one their type asks for, and which can
            # be served by nothing.
            "serviceability": {
                **serviceability.summarise(service_outcomes),
                # How many rows the run actually had to judge against. An empty
                # table and a table that refuses everything produced the same
                # message - "cannot be served at all" - and only one of those is
                # a finding. Reported so the next person does not have to infer
                # which, the way I did.
                "table_rows": len(service_table or {}),
                "table_basis": ("GOVERNED" if service_table else "ABSENT"),
            },
            "unserviceable": unserviceable,
            # The dual-access draw asked for a second path here and none could
            # be delivered. Distinct from a site the draw left single: this one
            # is a serviceability finding about the location.
            "single_by_necessity": single_by_necessity,
            "circuits_backbone": backbone_circuits,
            "site_sample": site_rows[:SAMPLE_NODES],
            # The whole estate, for the one pass that keeps it. Carrying this
            # on every pass would be O(ensemble x sites); carrying it on none
            # would mean the list the estimate is built from is not the list a
            # reader can examine.
            "estate_full": site_rows,
            "sites_named": named,
            "sites_generated": sites - named,
            "circuits_primary": primary, "circuits_backup": backup,
            "dual_sites": dual_sites,
            # Derived from the footprint and the approved archetype priors, so
            # it is reference-backed rather than invented. The estimate uses it
            # as the default headcount when the caller supplies none.
            "implied_users": implied_users,
            "bandwidth_profile": bandwidth_by_archetype,
            "bandwidth_mbps_total": sum(a["mbps_total"]
                                        for a in bandwidth_by_archetype.values()),
            "circuits_per_site": round(circuits / sites, 4) if sites else 0.0,
            # Both dimensions on every row. `product` stays so a snapshot
            # written before 4.169 is still readable, and service_class is what
            # the rate card now keys on.
            # Both dimensions on every row. The service class travels in the
            # key rather than being looked up here: it is chosen per archetype
            # inside the loop, and a lookup at return time would have read a
            # loop variable out of scope - which compiled and would have raised
            # on the first run.
            #
            # `product` stays so a snapshot written before 4.169 is readable,
            # and service_class is what the rate card keys on.
            "products": [{"country": c, "product": p, "role": r,
                          "bandwidth_mbps": bw, "count": n,
                          "service_class": sc,
                          # How it arrives, which serviceability resolved
                          # rather than the analyst choosing.
                          "access_technology": access.LEGACY_PRODUCT.get(
                              p, (None, None))[1]}
                         for (c, p, r, bw, sc), n in sorted(
                             products.items(), key=lambda kv: str(kv[0]))],
            "nodes": nodes, "edges": edges,        # bounded display sample
            "node_count": sites, "edge_count": circuits}


# Nodes and edges are only needed for the display sample, and carrying them for
# every pass would make a checkpoint enormous. A summary is checkpointed instead
# and the sample is regenerated at aggregation time by re-running the one pass
# it came from - which is free, because the pass is a pure function of its seed.
_SAMPLE_KEYS = ("nodes", "edges")


def summarise_pass(result: dict, index: int) -> dict:
    out = {k: v for k, v in result.items() if k not in _SAMPLE_KEYS}
    out["index"] = index
    return out


def aggregate(summaries: list[dict], *, seed: int, ensemble_size: int,
              footprint: list[dict], archetypes: dict, model_version: str,
              backbone: dict | None = None,
              known_locations: list[dict] | None = None,
              service_table: dict | None = None) -> dict:
    """Build the ensemble payload from per-pass summaries.

    Deliberately a pure function of the summaries, so a run assembled from a
    checkpoint after a cancellation produces byte-identical output to one that
    ran straight through.
    """
    if not summaries:
        raise ValueError(
            "cannot aggregate an empty ensemble: no passes have completed. A "
            "cancelled run with no checkpoint has nothing to assemble - resume "
            "it, or start a new run.")
    passes = sorted(summaries, key=lambda p: p["index"])
    circuits = sorted(p["circuits"] for p in passes)
    dual = sorted(p["dual_sites"] for p in passes)
    primaries = sorted(p["circuits_primary"] for p in passes)
    backups = sorted(p["circuits_backup"] for p in passes)
    median_summary = sorted(passes, key=lambda p: (p["circuits"], p["dual_sites"],
                                                   p["index"]))[len(passes) // 2]
    # Re-run the one pass the sample comes from. Same seed, same output.
    median_pass = one_pass(seed + median_summary["index"], footprint,
                           archetypes, backbone=backbone,
                           known_locations=known_locations,
                           service_table=service_table)

    def pct(values, q):
        if not values:
            return 0
        idx = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
        return values[idx]

    return {
        "model_version": model_version,
        "seed": seed,
        "ensemble_size": ensemble_size,
        "sites": median_pass["sites"],
        # The estate the estimate is built on, whole. Every circuit priced
        # downstream belongs to a row here, and every row says whether it is a
        # site somebody named or one this pass generated to make the count up.
        "serviceability": median_pass["serviceability"],
        "unserviceable": median_pass["unserviceable"],
        "single_by_necessity": median_pass["single_by_necessity"],
        "estate": median_pass["estate_full"][:MAX_ESTATE_ROWS],
        "estate_truncated": max(
            0, len(median_pass["estate_full"]) - MAX_ESTATE_ROWS),
        "sites_named": median_pass["sites_named"],
        "sites_generated": median_pass["sites_generated"],
        "circuits": {"low": pct(circuits, 0.10),
                     "base": int(median(circuits)),
                     "high": pct(circuits, 0.90)},
        "circuits_primary": {"low": pct(primaries, 0.10),
                             "base": int(median(primaries)),
                             "high": pct(primaries, 0.90)},
        "circuits_backup": {"low": pct(backups, 0.10),
                            "base": int(median(backups)),
                            "high": pct(backups, 0.90)},
        "products": median_pass["products"],
        "dual_access_sites": {"low": pct(dual, 0.10),
                              "base": int(median(dual)),
                              "high": pct(dual, 0.90)},
        # Deterministic from the backbone plan, so the median pass carries it
        # exactly. Reported separately from access because a reader comparing
        # circuit counts needs to know which part of the estate they refer to.
        "circuits_backbone": median_pass["circuits_backbone"],
        "circuits_per_site_base": median_pass["circuits_per_site"],
        # Deterministic from the footprint and the archetype priors, so the
        # median pass carries them exactly - there is nothing stochastic to
        # take a percentile over. Every pass computes the same value.
        #
        # Audit finding C-05: one_pass computed these and aggregate dropped
        # them, so the stored output never held them. The estimate reads
        # implied_users as its fallback headcount when the analyst supplies
        # none, and it was always absent - so the derived branch was
        # unreachable and the route refused every time, telling an analyst
        # there was nothing to derive from while the simulation had derived it.
        "implied_users": median_pass["implied_users"],
        "bandwidth_profile": median_pass["bandwidth_profile"],
        "bandwidth_mbps_total": median_pass["bandwidth_mbps_total"],
        "diversity_state": DIVERSITY_STATE,
        "backbone": backbone or {},
        "sample_topology": {"nodes": median_pass["nodes"], "edges": median_pass["edges"]},
        "node_count": median_pass["node_count"], "edge_count": median_pass["edge_count"],
    }


def run_ensemble(
             service_class_by_archetype: dict | None = None,*, seed: int, ensemble_size: int, footprint: list[dict],
                 archetypes: dict, model_version: str,
                 backbone: dict | None = None,
              known_locations: list[dict] | None = None,
              service_table: dict | None = None) -> dict:
    """Convenience wrapper: run every pass, then aggregate. The job runner drives
    the two halves separately so it can checkpoint, cancel and resume."""
    summaries = [summarise_pass(
        one_pass(seed + i, footprint, archetypes, backbone=backbone,
                 known_locations=known_locations,
                 service_table=service_table), i)
                 for i in range(ensemble_size)]
    return aggregate(summaries, seed=seed, ensemble_size=ensemble_size,
                     footprint=footprint, archetypes=archetypes,
                     model_version=model_version, backbone=backbone,
                     known_locations=known_locations,
                     service_table=service_table)


def output_hash(payload: dict) -> str:
    """Stable hash over the payload. sort_keys makes it order-independent."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
