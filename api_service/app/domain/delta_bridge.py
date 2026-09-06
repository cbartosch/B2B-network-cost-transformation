"""Why the estimate moved, reconciled to the last penny.

Specification 0.5D and 12.3. Every deterministic run writes an immutable
snapshot; the bridge explains the difference between two of them as eight
driver categories that sum exactly to the total change.

`estimate_snapshot.supersedes_snapshot_id` already carried the lineage, so the
system could say *that* an estimate changed. It could not say *why*, and "the
baseline moved 12%" is not an answer anyone accepts.

Two properties the spec insists on, and they are the whole point:

**The residual must be zero.** A bridge that nearly reconciles is a bridge that
has lost something, and the thing it lost is the part somebody will ask about.
An unattributed movement is reported as a residual rather than folded into the
nearest driver, because folding it makes the arithmetic tidy and the
explanation false.

**FX and scope never hide inside another driver.** The spec is explicit: "FX
never hides inside baseline cost", and a scope change is "never absorbed into
another driver". A country leaving the estate and a country getting cheaper
look identical in a total and are entirely different findings - one is a
smaller job, the other is a better price.
"""
from decimal import Decimal

# The eight categories, in the order §12.3 lists them. Ordered because a bridge
# is read as a waterfall and the reading order is part of the explanation:
# volume before price before timing is how a reader builds up the picture.
VOLUME = "volume_delta"                 # site count, mix, users, bandwidth
BASELINE_COST = "baseline_cost_delta"   # invoices, contracts, corrections
ARCHITECTURE = "architecture_delta"     # eligibility, BOM, licences, ops
UNIT_PRICE = "unit_price_delta"         # benchmark, quote, construction
REALIZATION = "realization_delta"       # ETF, lead time, wave, probability
EXECUTION = "execution_delta"           # installed price, cease date, leakage
FX = "fx_delta"                         # rate set and translation convention
SCOPE = "scope_delta"                   # include/exclude ledger, M&A

DRIVERS = (VOLUME, BASELINE_COST, ARCHITECTURE, UNIT_PRICE, REALIZATION,
           EXECUTION, FX, SCOPE)

# Which stage may move which driver, from §0.5D's evidence rule column. Not
# enforced here - the bridge explains what happened rather than policing it -
# but reported, because a baseline moving at V1 without commercial evidence is
# a finding about the estimate rather than about the client.
EARLIEST_STAGE = {
    VOLUME: "V1", BASELINE_COST: "V2", ARCHITECTURE: "V1", UNIT_PRICE: "V0",
    REALIZATION: "V2", EXECUTION: "V5", FX: "V0", SCOPE: "V0",
}

# The pins §0.5D requires on every snapshot. Compared before the residual test,
# because a movement caused by a different calculation version is not a finding
# about the client and reporting it as one would be worse than not comparing.
REQUIRED_PINS = ("scope_version_id", "base_currency", "fx_rate_set_id",
                 "fx_convention", "discount_rate_set_id",
                 "analysis_horizon_years", "benchmark_snapshot_id",
                 "rule_version", "calculation_version", "scenario_version")


class BridgeIncomplete(ValueError):
    """A bridge that does not reconcile, or cannot be built."""


def _dec(value):
    if value in (None, ""):
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return Decimal(0)


def policy_movement(from_pins: dict, to_pins: dict) -> dict:
    """What changed about the model between two snapshots, before the numbers.

    §0.5D: "Version comparison shows scope, FX and financial-policy movement
    separately before the zero-residual test is applied."

    A total that moved because the calculation version changed is not a finding
    about the client, and a bridge that attributes it to a driver would be
    describing the wrong thing entirely.
    """
    moved, missing = {}, []
    for pin in REQUIRED_PINS:
        before, after = (from_pins or {}).get(pin), (to_pins or {}).get(pin)
        if before is None and after is None:
            missing.append(pin)
            continue
        if before != after:
            moved[pin] = {"from": before, "to": after}
    return {
        "moved": moved,
        "unpinned": missing,
        "comparable": not moved,
        "note": (
            "no financial-policy or scope pin moved, so the difference is "
            "about the estate rather than about the model"
            if not moved else
            f"{sorted(moved)} moved between these snapshots. Movement here is "
            f"about the model, not the client - read it before reading the "
            f"drivers."
            ) + (f" {len(missing)} pin(s) absent from both snapshots: "
                 f"{missing}." if missing else ""),
    }


def bridge(*, from_total, to_total, attributions: list,
           from_pins: dict | None = None, to_pins: dict | None = None,
           tolerance="0.01") -> dict:
    """The eight drivers between two totals, and whether they add up.

    `attributions` is [{"driver": ..., "value": ..., "because": ...}, ...].
    Every entry names one of the eight categories; an unknown one is refused
    rather than bucketed, because a ninth category invented at write time is
    how FX ends up inside baseline cost.

    The residual is reported, never distributed. A bridge that nearly
    reconciles has lost something, and the thing it lost is the part somebody
    will ask about.
    """
    unknown = sorted({a.get("driver") for a in attributions
                      if a.get("driver") not in DRIVERS})
    if unknown:
        raise BridgeIncomplete(
            f"{unknown} are not delta drivers. The eight in §12.3 are "
            f"{list(DRIVERS)}, and a ninth invented at write time is how FX "
            f"ends up inside baseline cost.")

    by_driver = {d: Decimal(0) for d in DRIVERS}
    for entry in attributions:
        by_driver[entry["driver"]] += _dec(entry.get("value"))

    total_change = _dec(to_total) - _dec(from_total)
    attributed = sum(by_driver.values(), Decimal(0))
    residual = total_change - attributed
    reconciles = abs(residual) <= _dec(tolerance)

    return {
        "from_total": str(_dec(from_total)),
        "to_total": str(_dec(to_total)),
        "total_change": str(total_change),
        # In §12.3 order, because a bridge is read as a waterfall.
        "drivers": [{"driver": d, "value": str(by_driver[d]),
                     "earliest_stage": EARLIEST_STAGE[d],
                     "because": [a.get("because") for a in attributions
                                 if a.get("driver") == d and a.get("because")]}
                    for d in DRIVERS],
        "attributed": str(attributed),
        "residual": str(residual),
        "reconciles": reconciles,
        "policy": policy_movement(from_pins or {}, to_pins or {}),
        "note": (
            "the drivers account for the whole movement"
            if reconciles else
            f"{residual} of the {total_change} change is unattributed. It is "
            f"reported rather than folded into the nearest driver: folding it "
            f"makes the arithmetic tidy and the explanation false."),
    }


def check_lever_mapping(levers: list, mapping: dict) -> dict:
    """§12.3: every lever maps to exactly one driver, or the test fails.

    Unmapped and multiply-mapped are different faults and are reported apart.
    An unmapped lever's saving lands nowhere and shows up as residual; a
    doubly-mapped one lands twice and makes the bridge reconcile while
    double-counting, which is worse because it looks correct.
    """
    unmapped, multiple = [], []
    for lever in levers:
        lever_id = lever.get("lever_id") if isinstance(lever, dict) else lever
        targets = mapping.get(lever_id)
        if not targets:
            unmapped.append(lever_id)
        elif isinstance(targets, (list, tuple, set)) and len(targets) > 1:
            multiple.append({"lever_id": lever_id, "drivers": sorted(targets)})
    return {
        "unmapped": unmapped,
        "mapped_more_than_once": multiple,
        "passes": not unmapped and not multiple,
        "note": (
            "every lever maps to exactly one driver"
            if not unmapped and not multiple else
            f"{len(unmapped)} lever(s) map to no driver and their saving lands "
            f"nowhere; {len(multiple)} map to more than one and land twice - "
            f"which makes the bridge reconcile while double-counting, and that "
            f"is the worse fault because it looks correct."),
    }
