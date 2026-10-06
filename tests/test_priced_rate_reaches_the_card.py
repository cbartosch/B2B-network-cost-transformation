"""The priced rate a site is costed at, and the seam that stopped reaching it.

committed_fraction is seeded per archetype with values that differ - BRANCH
0.50, DC 0.30, CAMPUS 0.95 - and simulation.py asks the prior for it:

    committed_fraction=(_for(committed_fraction_by_archetype, entry)
                        or prior.get("committed_fraction"))

The loader in api.py did not put committed_fraction in the dict, so that second
branch was always None, access.pair_for took its `if committed_fraction in
(None, "")` path, and priced_rate keyed the rate card on the bearer. A DC was
priced at its full 1000 Mbps rather than the 300 it commits.

simulation.py's own comment already recorded the cost of that: "Pricing on the
bearer overstated an IPVPN by 980 against 420 a month on the GB card." The fix
was written - pair_for takes the fraction, the precedence is right - and never
received the number.

Nothing in the suite noticed. A change that moves a priced rate by up to 3.3x
broke no test, because nothing pinned the priced rate at all. The test that
eventually caught it, test_integrity's unread-column scan, detects the shape of
the mistake and not its effect: it would pass just as happily if the column
were loaded and then multiplied by two.

So this file pins the effect. One test on the arithmetic, one on the seam, and
one on the number an archetype is actually costed at.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app import db
from app.domain import access
from app.seed import ARCHETYPES

API_PY = pathlib.Path(db.__file__).with_name("routers") / "api.py"
SIMULATION_PY = pathlib.Path(db.__file__).with_name("domain") / "simulation.py"

# An archetype whose committed fraction is far from 1.0, so a regression to
# bearer pricing is unmistakable rather than a rounding argument.
DC = next(r for r in ARCHETYPES if r[0] == "DC")
DC_COMMITTED_FRACTION = DC[6]


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_a_committed_service_is_priced_on_what_it_commits():
    """The defect, at the level it was wrong: 1000 vs 300 on one bearer."""
    bearer = 1000

    on_bearer = access.pair_for(service_class="ETHERNET", bearer_mbps=bearer,
                                committed_fraction=None)
    on_committed = access.pair_for(service_class="ETHERNET", bearer_mbps=bearer,
                                   committed_fraction=DC_COMMITTED_FRACTION)

    assert access.priced_rate(on_bearer) == bearer
    assert access.priced_rate(on_committed) == 300
    assert access.priced_rate(on_committed) < access.priced_rate(on_bearer), (
        "a committed service priced at its bearer is the overstatement "
        "simulation.py measured at 980 against 420 a month")


def test_the_bearer_is_still_what_had_to_be_installed():
    """Both figures matter and they are not interchangeable. Sizing asks what
    must be delivered; pricing asks what was committed across it."""
    pair = access.pair_for(service_class="ETHERNET", bearer_mbps=1000,
                           committed_fraction=DC_COMMITTED_FRACTION)

    assert access.sizing_rate(pair) == 1000
    assert access.priced_rate(pair) == 300


@pytest.mark.parametrize("archetype,fraction", [
    (r[0], r[6]) for r in ARCHETYPES
    if access.LEGACY_PRODUCT.get(r[4], (None,))[0] in ("IPVPN", "ETHERNET")
])
def test_every_committed_archetype_prices_below_its_bearer(archetype, fraction):
    """Across the seeded set, not one worked example. An archetype whose
    fraction stopped being applied would price at the bearer again."""
    service_class = access.LEGACY_PRODUCT[
        next(r[4] for r in ARCHETYPES if r[0] == archetype)][0]
    pair = access.pair_for(service_class=service_class, bearer_mbps=1000,
                           committed_fraction=fraction)

    expected = int(1000 * float(fraction))
    assert access.priced_rate(pair) == expected
    if float(fraction) < 1.0:
        assert access.priced_rate(pair) < 1000


# ── the seam that broke ─────────────────────────────────────────────────────

def _prior_keys_simulation_reads() -> set[str]:
    return set(re.findall(r'prior\.get\("([a-z_]+)"',
                          SIMULATION_PY.read_text(encoding="utf-8")))


def _prior_keys_the_loader_supplies() -> set[str]:
    """The keys of the `arch` dict api.py builds from archetype_prior.

    Bounded by the comprehension's own `for r in s.execute(...)` clause rather
    than by a character count, so nearby code cannot drift into the window.
    """
    source = API_PY.read_text(encoding="utf-8")
    start = source.index("arch = {r.archetype:")
    end = source.index("for r in s.execute(select(db.archetype_prior))", start)
    return set(re.findall(r'"([a-z_]+)":', source[start:end]))


def test_the_loader_supplies_every_prior_key_the_simulation_reads():
    """The general form of the defect.

    simulation.py reads the prior by key. A key the loader omits is not an
    error - `.get` returns None and the caller falls through to a default - so
    the omission is silent and the default looks like a decision. That is
    exactly how committed_fraction was lost.
    """
    read = _prior_keys_simulation_reads()
    supplied = _prior_keys_the_loader_supplies()

    missing = sorted(read - supplied)
    assert not missing, (
        f"simulation.py reads these from the prior and api.py never loads "
        f"them, so each silently falls back to a default: {missing}")


def test_the_seam_check_has_something_to_check():
    """Guards the test above from passing because a regex stopped matching."""
    read = _prior_keys_simulation_reads()
    supplied = _prior_keys_the_loader_supplies()

    assert len(read) >= 6, f"only {len(read)} prior.get keys found in simulation.py"
    assert len(supplied) >= 6, f"only {len(supplied)} keys found in the loader"
    assert "committed_fraction" in read, "the key this file exists for"


def test_every_archetype_prior_column_the_model_declares_is_loaded():
    """The column side of the same seam.

    A column can be seeded, declared on the table, and still never reach the
    simulation. Three were: committed_fraction and the two service classes.
    """
    declared = {c.name for c in db.archetype_prior.columns} - {"archetype"}
    supplied = _prior_keys_the_loader_supplies()

    assert not declared - supplied, (
        f"seeded columns the loader drops: {sorted(declared - supplied)}")


# ── what an archetype is actually costed at ─────────────────────────────────

def test_a_dc_is_costed_on_its_committed_rate_not_its_bearer():
    """The end of the chain, stated as a number.

    seed -> loader -> simulation -> access.pair_for -> priced_rate. Every link
    was correct except the second, and the result was a DC priced at 1000.
    """
    prior = {"committed_fraction": DC_COMMITTED_FRACTION}

    # Exactly the expression simulation.py evaluates, with no case override.
    committed = None or prior.get("committed_fraction")
    pair = access.pair_for(service_class="ETHERNET", bearer_mbps=1000,
                           committed_fraction=committed)

    assert access.priced_rate(pair) == 300, (
        "a DC commits 30% of its bearer; pricing it at 1000 overstates the "
        "rate the card is keyed on by 3.3x")


def test_a_case_override_still_beats_the_seeded_default():
    """The precedence simulation.py documents: "a seeded number is a starting
    position, not a decision". Loading the default must not outrank a case."""
    prior = {"committed_fraction": DC_COMMITTED_FRACTION}
    case_choice = "0.80"

    committed = case_choice or prior.get("committed_fraction")
    pair = access.pair_for(service_class="ETHERNET", bearer_mbps=1000,
                           committed_fraction=committed)

    assert access.priced_rate(pair) == 800


def test_a_best_effort_service_is_not_given_a_committed_rate():
    """Only IPVPN and ETHERNET commit. A best-effort circuit has a bearer and
    no guarantee, and inventing one would price a promise nobody made."""
    pair = access.pair_for(service_class="BEST_EFFORT", bearer_mbps=1000,
                           committed_fraction="0.30")

    assert access.priced_rate(pair) != 300
