"""Does every governed lever have something to act on?

A lever with no cost pool contributes nothing, and contributing nothing looks
exactly like working. This repository shipped three features in that state:
the industry benchmark applied to archetypes no estate contained, two OPS
levers acting on a layer nothing built, and an archetype resolver silently
discarding every pair it was given.

`tools/check_lever_reach.py` found a fourth on its first run:
`LEV-MPLS-001`, the 25% MPLS substitution lever at the centre of the whole
transformation thesis, was scoped to service class IPVPN - and 89 MPLS rates
sat on the card while no archetype in the vocabulary could buy one. Every
primary and backup product was DIA, Ethernet, broadband or 5G.

It was seeded, displayed, audited twice and dead on every case ever run.
"""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_lever_is_dead():
    """The check, run as a test so it cannot be forgotten.

    Exit 1 means a lever acts on a layer no priced estate builds, or on a
    service class no estate shape produces.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_lever_reach.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=180)
    assert result.returncode == 0, result.stdout[-1500:]


def test_the_mpls_lever_has_an_estate_that_buys_mpls():
    """The specific defect the check found. A transformation case starts from
    a mixed estate - some sites on internet, some still on private WAN - and
    the second kind is what the MPLS lever removes."""
    from app.domain import access
    from app.seed import ARCHETYPES

    buys_ipvpn = [
        row[0] for row in ARCHETYPES
        if access.LEGACY_PRODUCT.get(row[4], (None,))[0] == "IPVPN"
        or access.LEGACY_PRODUCT.get(row[5], (None,))[0] == "IPVPN"]
    assert buys_ipvpn, (
        "no archetype can buy a private-WAN circuit, so LEV-MPLS-001 has "
        "nothing to act on in any estate")


def test_that_archetype_appears_in_a_real_estate():
    """Reachable in the vocabulary is not the same as present in an estate.
    A site type no shape contains is the inert-benchmark defect one level
    down."""
    from collections import defaultdict

    from app.seed import DENSITY_MIX

    mix = defaultdict(set)
    for industry, archetype, _band, _share in DENSITY_MIX:
        mix[industry].add(archetype)
    holding = [i for i, arch in mix.items() if "LEGACY_WAN_SITE" in arch]
    assert holding, "LEGACY_WAN_SITE is in no industry's estate"


def test_the_new_levers_each_have_a_baseline():
    """Baselines before levers. Phase 1 seeded POP_COLOCATION on L1 before
    Phase 2 added the lever that acts on it, deliberately in that order."""
    from app.seed import LEVERS, PLATFORM

    priced_platform_layers = {row[1] for row in PLATFORM}
    for row in LEVERS:
        lever_id, layers = row[0], set(row[3] or [])
        platform_layers = layers - {"L0", "OPS"}
        if platform_layers:
            assert platform_layers & priced_platform_layers, (
                f"{lever_id} acts on {sorted(platform_layers)} and no "
                f"platform unit cost exists for any of them")


def test_the_backbone_lever_scopes_by_role():
    """A backbone link is Ethernet like every other circuit and differs only
    in what it is for, so it could not scope itself until applies_to_roles
    existed."""
    from app.seed import LEVERS

    backbone = next(r for r in LEVERS if r[0] == "LEV-BACKBONE-001")
    assert backbone[12] == ["BACKBONE"]
