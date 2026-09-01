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

DIVERSITY_STATE = "SIMULATED"          # 0.3B may never emit any other value


def _rng(seed: int, salt: str) -> random.Random:
    # Derive a per-purpose stream so adding a stage later does not shift
    # earlier draws and silently change historical output.
    h = hashlib.sha256(f"{seed}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


SAMPLE_NODES, SAMPLE_EDGES = 200, 400


def one_pass(seed: int, footprint: list[dict], archetypes: dict,
             backbone: dict | None = None) -> dict:
    """One synthetic estate. footprint = [{country, archetype, sites}, ...]"""
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

    for entry in sorted(footprint, key=lambda e: (e["country"], e["archetype"])):
        prior = archetypes.get(entry["archetype"], {})
        p_dual = float(prior.get("dual_access_probability", 0.5))
        primary_product = prior.get("primary_product", "DIA")
        backup_product = prior.get("backup_product", "BROADBAND_PON")
        users_base = int(prior.get("users_base") or 0)
        bw_base = int(prior.get("bandwidth_mbps_base") or 0)
        n_sites = int(entry["sites"])
        implied_users += users_base * n_sites
        agg = bandwidth_by_archetype.setdefault(
            entry["archetype"], {"sites": 0, "mbps_per_site": bw_base, "mbps_total": 0})
        agg["sites"] += n_sites
        agg["mbps_total"] += bw_base * n_sites

        for i in range(int(entry["sites"])):
            node_id = f"{entry['country']}-{entry['archetype']}-{i:04d}"
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
            products[(entry["country"], primary_product, "PRIMARY", bw_base)] = \
                products.get((entry["country"], primary_product, "PRIMARY", bw_base), 0) + 1

            # The stochastic draw. Whether a site has a second access path is the
            # one thing this simulation actually decides - the primary count
            # follows deterministically from the supplied footprint. That is why
            # only the backup layer is attributed to SIMULATED downstream.
            if rng.random() < p_dual:
                if len(edges) < SAMPLE_EDGES:
                    edges.append({"from": node_id, "to": f"POP2-{entry['country']}",
                                  "product": backup_product, "role": "BACKUP",
                                  "bandwidth_mbps": bw_base,
                                  "diversity_state": DIVERSITY_STATE})
                backup += 1
                dual_sites += 1
                products[(entry["country"], backup_product, "BACKUP", bw_base)] = \
                    products.get((entry["country"], backup_product, "BACKUP", bw_base), 0) + 1

    sites = sum(int(e["sites"]) for e in footprint)
    circuits = primary + backup
    return {"sites": sites, "circuits": circuits,
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
            "products": [{"country": c, "product": p, "role": r,
                          "bandwidth_mbps": bw, "count": n}
                         for (c, p, r, bw), n in sorted(products.items())],
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
              backbone: dict | None = None) -> dict:
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
                           archetypes, backbone=backbone)

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
        "circuits_per_site_base": median_pass["circuits_per_site"],
        "diversity_state": DIVERSITY_STATE,
        "backbone": backbone or {},
        "sample_topology": {"nodes": median_pass["nodes"], "edges": median_pass["edges"]},
        "node_count": median_pass["node_count"], "edge_count": median_pass["edge_count"],
    }


def run_ensemble(*, seed: int, ensemble_size: int, footprint: list[dict],
                 archetypes: dict, model_version: str,
                 backbone: dict | None = None) -> dict:
    """Convenience wrapper: run every pass, then aggregate. The job runner drives
    the two halves separately so it can checkpoint, cancel and resume."""
    summaries = [summarise_pass(
        one_pass(seed + i, footprint, archetypes, backbone=backbone), i)
                 for i in range(ensemble_size)]
    return aggregate(summaries, seed=seed, ensemble_size=ensemble_size,
                     footprint=footprint, archetypes=archetypes,
                     model_version=model_version, backbone=backbone)


def output_hash(payload: dict) -> str:
    """Stable hash over the payload. sort_keys makes it order-independent."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
