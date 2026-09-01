"""The shape of the network the simulation generates.

Until now every site got an access circuit to a notional in-country POP and
nothing else. That is not a WAN: it is a set of unconnected local loops. A real
estate has a core, and the core costs money - so an estimate built on access
circuits alone understates the baseline it is trying to reduce, and no
backbone-consolidation lever has anything to act on.

Three tiers, which is the standard shape and the one an analyst expects:

  ACCESS          every site to its in-country POP. Product and bandwidth come
                  from the archetype, so a branch takes DIA and a store takes
                  broadband. Local, per site.
  DC_TO_REGION    each data centre to its regional hub. High bandwidth, carrier
                  ethernet, dual by default - a DC with one path is a design
                  nobody ships.
  REGION_TO_CORE  each regional hub to the global core. The backbone.

Head offices are access-tier by design. A large office is a big local
connection, not a core node: treating one as a hub would put a backbone circuit
wherever an entity happens to have a headquarters.

**Regions are governed reference data**, not a hardcoded mapping. Which
countries cluster together is a design decision that varies by client - a
European bank's regions are not a logistics group's - and a hardcoded list
would be a modelling assumption nobody could see or change.

**A tier only appears if the estate has the sites for it.** One data centre in
one country produces no regional tier: there is nothing to cluster. Generating
a hub for a single site would invent a backbone the client does not have.
"""
from collections import defaultdict

ACCESS = "ACCESS"
DC_TO_REGION = "DC_TO_REGION"
REGION_TO_CORE = "REGION_TO_CORE"
TIERS = (ACCESS, DC_TO_REGION, REGION_TO_CORE)

# Site types that are core nodes rather than leaves. A data centre is where
# compute lives and is what a backbone exists to connect; everything else -
# including a headquarters - is a leaf with a local circuit.
HUB_ARCHETYPES = ("DC",)


def plan(footprint: list[dict], *, regions: dict, template: dict) -> dict:
    """What backbone this estate implies, before any circuit is generated.

    `regions` maps an ISO country to a region name. `template` carries the
    product and bandwidth for each backbone tier, both governed.

    Returns the hubs, the region each belongs to, and the links between them -
    deterministically, so the same estate always implies the same core.
    """
    by_region = defaultdict(lambda: {"countries": set(), "dc_sites": 0})
    unmapped = set()

    for row in footprint or []:
        country = str(row.get("country") or "").upper()
        archetype = str(row.get("archetype") or "").upper()
        sites = int(row.get("sites") or 0)
        if not country or sites <= 0:
            continue
        region = regions.get(country)
        if region is None:
            # Reported, not guessed. A country with no region cannot be given
            # one silently: the estimate would carry a backbone link to a hub
            # nobody chose.
            unmapped.add(country)
            continue
        by_region[region]["countries"].add(country)
        if archetype in HUB_ARCHETYPES:
            by_region[region]["dc_sites"] += sites

    regions_with_dc = {name: data for name, data in by_region.items()
                       if data["dc_sites"] > 0}

    links = []
    # DC to regional hub. Only where a region has data centres to cluster.
    for name, data in sorted(regions_with_dc.items()):
        links.append({
            "tier": DC_TO_REGION, "region": name,
            "count": data["dc_sites"],
            "product": template["dc_to_region_product"],
            "bandwidth_mbps": template["dc_to_region_mbps"],
            "dual": bool(template.get("dc_dual", True)),
            "note": (f"{data['dc_sites']} data centre(s) in {name} to the "
                     f"{name} hub"),
        })

    # Regional hub to global core. Only with more than one region: a single
    # region has nothing to reach across, and a core link from one hub to
    # itself is not a circuit.
    if len(regions_with_dc) > 1:
        for name in sorted(regions_with_dc):
            links.append({
                "tier": REGION_TO_CORE, "region": name, "count": 1,
                "product": template["region_to_core_product"],
                "bandwidth_mbps": template["region_to_core_mbps"],
                "dual": bool(template.get("core_dual", True)),
                "note": f"{name} hub to the global core",
            })

    return {
        "template_version": template.get("version", "unknown"),
        "regions": {name: sorted(data["countries"])
                    for name, data in sorted(by_region.items())},
        "hub_regions": sorted(regions_with_dc),
        "links": links,
        "unmapped_countries": sorted(unmapped),
        "backbone_circuits": sum(
            link["count"] * (2 if link["dual"] else 1) for link in links),
        "note": _note(regions_with_dc, unmapped, links),
    }


def _note(regions_with_dc, unmapped, links) -> str:
    parts = []
    if not links:
        parts.append(
            "No backbone tier: this estate has no data centres, so there is "
            "nothing to cluster. Access circuits only, which is correct for a "
            "footprint of leaves - not a gap in the model.")
    if len(regions_with_dc) == 1:
        parts.append(
            f"One region with data centres ({next(iter(regions_with_dc))}), so "
            f"there is no global core tier - a hub has nothing to reach across.")
    if unmapped:
        parts.append(
            f"No region is mapped for {', '.join(sorted(unmapped))}, so sites "
            f"there carry access circuits and no backbone. Add the mapping to "
            f"reference.country_region rather than letting the estimate imply "
            f"a core link nobody chose.")
    return " ".join(parts)


def edges(plan_result: dict, *, region_node=lambda r: f"HUB-{r}",
          core_node: str = "CORE") -> list[dict]:
    """The backbone as circuit records, in the shape the access tier uses.

    Same fields as an access edge so the pricing path, the coverage count and
    the sample table treat a core circuit as the circuit it is.
    """
    out = []
    for link in plan_result.get("links") or []:
        region = link["region"]
        source = (f"DC-{region}" if link["tier"] == DC_TO_REGION
                  else region_node(region))
        target = region_node(region) if link["tier"] == DC_TO_REGION else core_node
        for index in range(link["count"]):
            out.append({
                "from": f"{source}-{index:04d}" if link["count"] > 1 else source,
                "to": target, "product": link["product"],
                "role": "PRIMARY", "tier": link["tier"],
                "bandwidth_mbps": link["bandwidth_mbps"],
                "diversity_state": "SIMULATED",
            })
            if link["dual"]:
                out.append({
                    "from": f"{source}-{index:04d}" if link["count"] > 1 else source,
                    "to": f"{target}-B", "product": link["product"],
                    "role": "BACKUP", "tier": link["tier"],
                    "bandwidth_mbps": link["bandwidth_mbps"],
                    "diversity_state": "SIMULATED",
                })
    return out
