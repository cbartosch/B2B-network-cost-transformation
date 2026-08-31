"""What changed between two estimates, and why.

The workflow this bundle implements is meant to be an estimate that improves as
evidence arrives: research finds a figure, promotion turns it into evidence,
corroboration lifts an assertion, and confidence rises accordingly. The
mechanism works - confidence derives from priced coverage, the origin mix and
domain completeness, all of which respond to evidence.

What was missing is any way to see it. Every snapshot was an island: no link to
the one it improved on, and no statement of what moved. An analyst re-running
V0 after promoting three sources got a new number with no account of why it
differed from the last one, which is indistinguishable from a number that
changed for no reason.

**Attribution is deterministic and refuses to guess.** Where a driver's origin
improved - ANALYST_ENTERED_SCOPE to EVIDENCED_PUBLIC - that is stated as the
cause because it is one. Where a figure moved and nothing observable explains
it, that is stated too, rather than the nearest plausible reason being offered.
A refinement narrative that always finds a cause is a narrative nobody can
check.

**This does not implement V1.** Every snapshot this build writes is labelled
V0, because a V1 estimate needs governed stage_ceiling_V1_* thresholds and
policy.py holds no defaults by design - inventing them would be the exact
defect that module exists to prevent. Advancing the stage is recorded and does
not yet change a published number, which stage.py already says plainly. What
follows is refinement *within* V0, which is where the evidence actually moves.
"""
from decimal import Decimal, InvalidOperation

# Origin strength, worst first. The ladder the confidence model already prices:
# a typed number caps the baseline, a corroborated assertion does not, and
# public evidence lifts it.
ORIGIN_RANK = {
    "ANALYST_ASSERTED_PRIOR": 1,
    "ANALYST_ENTERED_SCOPE": 2,
    "SIMULATED": 2,
    "PUBLIC_SPEND_ANCHOR": 3,
    "PUBLIC_DERIVED": 4,
    "EVIDENCED_PUBLIC": 5,
    "PUBLIC_OBSERVED": 5,
    "CLIENT_CONFIRMED": 6,
}


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _pct_change(old, new):
    o, n = _dec(old), _dec(new)
    if o is None or n is None or o == 0:
        return None
    return float((n - o) / abs(o))


def compare(earlier: dict, later: dict) -> dict:
    """Two snapshot rows into a statement of what moved and what caused it."""
    moved, causes, unexplained = [], [], []

    def _note(label, old, new, *, kind="figure"):
        if old is None and new is None:
            return
        if str(old) != str(new):
            moved.append({"field": label, "from": old, "to": new,
                          "change_pct": _pct_change(old, new), "kind": kind})

    e_conf = earlier.get("confidence") or {}
    l_conf = later.get("confidence") or {}
    _note("confidence.score", e_conf.get("score"), l_conf.get("score"),
          kind="confidence")
    _note("confidence.band", e_conf.get("band"), l_conf.get("band"),
          kind="confidence")

    e_cov = earlier.get("coverage") or {}
    l_cov = later.get("coverage") or {}
    for field in ("effective_coverage_pct", "priced_circuits", "total_circuits",
                  "status"):
        _note(f"coverage.{field}", e_cov.get(field), l_cov.get(field),
              kind="coverage")

    _note("asserted_share", earlier.get("asserted_share"),
          later.get("asserted_share"), kind="evidence")
    _note("simulated_share", earlier.get("simulated_share"),
          later.get("simulated_share"), kind="evidence")

    e_tco = (earlier.get("current_tco") or {}).get("base")
    l_tco = (later.get("current_tco") or {}).get("base")
    _note("current_tco.base", e_tco, l_tco)

    for code in sorted(set(earlier.get("scenarios") or {})
                       | set(later.get("scenarios") or {})):
        e_s = ((earlier.get("scenarios") or {}).get(code) or {})
        l_s = ((later.get("scenarios") or {}).get(code) or {})
        _note(f"scenario {code} savings (base)",
              (e_s.get("gross_run_rate_savings") or {}).get("base"),
              (l_s.get("gross_run_rate_savings") or {}).get("base"))

    # --- attribution ------------------------------------------------------
    e_origins = _origin_shares(earlier)
    l_origins = _origin_shares(later)
    for origin in sorted(set(e_origins) | set(l_origins)):
        before, after = e_origins.get(origin, 0.0), l_origins.get(origin, 0.0)
        if abs(after - before) < 0.005:
            continue
        rank = ORIGIN_RANK.get(origin, 0)
        direction = "rose" if after > before else "fell"
        causes.append({
            "kind": "origin_shift", "origin": origin, "rank": rank,
            "from": round(before, 3), "to": round(after, 3),
            "statement": (
                f"the share of value carried by {origin} {direction} from "
                f"{before:.0%} to {after:.0%}"),
            "improves": (after > before) == (rank >= 4),
        })

    e_method = (earlier.get("pins") or {}).get("estimate_method", "BUILD_UP")
    l_method = (later.get("pins") or {}).get("estimate_method", "BUILD_UP")
    if e_method != l_method:
        causes.append({
            "kind": "method_change", "from": e_method, "to": l_method,
            "statement": (
                f"the estimation method changed from {e_method} to {l_method}, "
                f"so the two figures answer different questions and should not "
                f"be read as one improving on the other"),
            "improves": None})

    e_ver = (earlier.get("pins") or {}).get("calculation_version")
    l_ver = (later.get("pins") or {}).get("calculation_version")
    if e_ver != l_ver:
        causes.append({
            "kind": "calculation_change", "from": e_ver, "to": l_ver,
            "statement": (
                f"the calculation version changed from {e_ver} to {l_ver}, so "
                f"part of the movement is the model rather than the evidence"),
            "improves": None})

    # A figure that moved with nothing observable behind it. Reported rather
    # than attributed to the nearest plausible cause.
    if any(m["kind"] == "figure" for m in moved) and not causes:
        unexplained.append(
            "figures moved and no change of origin mix, method or calculation "
            "version explains it. Most likely a different simulation seed, a "
            "reseeded price prior or an edited footprint - none of which is "
            "recorded on the snapshot, so it is not asserted here.")

    improving = [c for c in causes if c.get("improves") is True]
    return {
        "from_snapshot": earlier.get("estimate_snapshot_id"),
        "to_snapshot": later.get("estimate_snapshot_id"),
        "from_created": str(earlier.get("created_at") or ""),
        "to_created": str(later.get("created_at") or ""),
        "moved": moved,
        "causes": causes,
        "unexplained": unexplained,
        "is_refinement": bool(improving) and not any(
            c["kind"] in ("method_change",) for c in causes),
        "summary": _summarise(moved, causes, unexplained),
    }


def _origin_shares(snapshot: dict) -> dict:
    breakdown = ((snapshot.get("pins") or {}).get("origin_breakdown")
                 or (snapshot.get("coverage") or {}).get("origin_breakdown")
                 or {})
    out = {}
    for origin, payload in breakdown.items():
        share = _dec((payload or {}).get("share"))
        if share is not None:
            out[origin] = float(share)
    return out


def _summarise(moved, causes, unexplained) -> str:
    if not moved:
        return ("Nothing moved. The inputs that reached the calculation are "
                "identical, whatever else changed on the case.")
    conf = next((m for m in moved if m["field"] == "confidence.score"), None)
    parts = []
    improving = [c for c in causes if c.get("improves") is True]
    if conf:
        direction = ("rose" if (_dec(conf["to"]) or 0) > (_dec(conf["from"]) or 0)
                     else "fell")
        head = f"Confidence {direction} from {conf['from']} to {conf['to']}"
        if improving:
            head += " because " + "; ".join(c["statement"] for c in improving)
        parts.append(head)
    elif improving:
        parts.append("The evidence improved: "
                     + "; ".join(c["statement"] for c in improving))
    other = [c for c in causes if c.get("improves") is not True]
    if other:
        parts.append("Also: " + "; ".join(c["statement"] for c in other))
    if unexplained:
        parts.append("Some movement is unexplained: " + unexplained[0])
    return ". ".join(p.rstrip(".") for p in parts) + "."


def progression(snapshots: list[dict]) -> dict:
    """The whole chain, oldest first, with each step compared to the last."""
    ordered = sorted(snapshots, key=lambda s: str(s.get("created_at") or ""))
    steps = [compare(ordered[i - 1], ordered[i]) for i in range(1, len(ordered))]
    return {
        "snapshots": [{"estimate_snapshot_id": s.get("estimate_snapshot_id"),
                       "created_at": str(s.get("created_at") or ""),
                       "version_label": s.get("version_label"),
                       "method": (s.get("pins") or {}).get("estimate_method",
                                                           "BUILD_UP"),
                       "confidence": (s.get("confidence") or {}).get("score"),
                       "band": (s.get("confidence") or {}).get("band"),
                       "coverage": (s.get("coverage") or {}).get(
                           "effective_coverage_pct"),
                       "v0_status": s.get("v0_status")}
                      for s in ordered],
        "steps": steps,
        "refinements": sum(1 for s in steps if s["is_refinement"]),
        "note": (
            "Every snapshot here is labelled V0. A V1 estimate needs governed "
            "stage_ceiling_V1_* thresholds, which nobody has approved - so "
            "advancing the stage is recorded and does not yet change a "
            "published number. This is refinement within V0, which is where "
            "the evidence moves."),
    }
