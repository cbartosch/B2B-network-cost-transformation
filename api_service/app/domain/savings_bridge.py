"""The savings waterfall: baseline, each lever in turn, target.

Distinct from `delta_bridge`, which reconciles two VERSIONS of an estimate
across the eight delta drivers - why did the number change between runs. This
is why the number should change if the programme happens.

Three things it exists to make visible, none of which the scenario output
shows on its own.

**Order.** Levers compound: each acts on what the ones before it left behind.
Presented as a flat list they read as additive, and a reader adds them up.
Repricing a circuit and then deleting it is the classic double-count, and it
is invisible in a list.

**Basis.** A step is a governed lever, an analyst's estimate, or a lever that
found nothing to act on. Those look identical in a total and mean entirely
different things: the third is not a zero, it is a hole.

**What was not counted.** A lever that could not apply, and a cost pool with
no baseline at all, both contribute nothing - and a bridge that silently omits
them presents a smaller opportunity as a complete one.
"""
from decimal import Decimal as D


# What a step's number rests on.
GOVERNED = "GOVERNED_LEVER"          # a seeded lever, applied to a real baseline
NO_BASELINE = "NO_BASELINE"          # the lever exists; the cost pool does not
NOT_APPLICABLE = "NOT_APPLICABLE"    # the baseline exists; nothing matched
ESTIMATE = "ANALYST_ESTIMATE"        # entered by hand, no lever behind it
# Not taken because a better lever already removed the same cost. Distinct
# from NOT_APPLICABLE: the opportunity exists and has been counted once.
EXCLUDED = "EXCLUDED_BY_EARLIER_LEVER"


def waterfall(scenarios: dict, *, current_total, order=("A", "B", "C", "D"),
              extra_steps=None, coverage=None) -> dict:
    """Baseline to target, one step per lever, in the order they compound.

    `scenarios` is the mapping `estimate.scenarios()` returns. `extra_steps`
    are hand-entered steps for cost pools the model has no lever for - they
    are carried, marked ANALYST_ESTIMATE, and never mixed into the governed
    total.

    The residual is reported rather than distributed. A waterfall that nearly
    reconciles has lost something, and the thing it lost is what somebody
    will ask about.
    """
    baseline = D(str(current_total))
    running = baseline
    steps, skipped = [], []

    # Levers already booked, so an exclusive peer in a LATER scenario is not
    # booked again.
    #
    # `scenarios()` computes each scenario independently from the full
    # baseline - A is 14.6% of the whole, B is 25% of the whole - and it
    # resolves exclusivity WITHIN a scenario only, because that is all it can
    # see. Repricing sits in A and MPLS substitution in B, so the two never
    # meet there.
    #
    # This walked them in order and subtracted both, which is exactly the
    # double count the exclusivity work was for: repricing a circuit you then
    # delete never happens. The waterfall is the only place that sees all
    # four scenarios at once, so it is the only place this can be caught.
    booked, excluded_by = set(), {}
    for code in order:
        scenario = scenarios.get(code) or {}
        for lever in (scenario.get("levers") or []):
            value = D(str(lever.get("saving_base") or lever.get("value") or 0))
            if value <= 0:
                continue
            lever_id = lever.get("lever_id")
            clash = set(lever.get("excludes") or []) & booked
            if clash:
                # Not silently dropped. A lever the programme cannot take
                # BECAUSE it took a better one is a different finding from a
                # lever that found nothing, and a reader needs to see that
                # the opportunity was counted once rather than missed.
                excluded_by[lever_id] = sorted(clash)[0]
                skipped.append({
                    "step": lever.get("family") or lever_id,
                    "lever_id": lever_id,
                    "scenario": code,
                    "saving": "0",
                    "basis": EXCLUDED,
                    "reason": (
                        f"excluded by {sorted(clash)[0]}, already booked in "
                        f"an earlier scenario - you either renegotiate a "
                        f"circuit or you replace it, and booking both counts "
                        f"the same saving twice"),
                })
                continue
            booked.add(lever_id)
            steps.append({
                "step": lever.get("family") or lever.get("lever_id"),
                "lever_id": lever.get("lever_id"),
                "scenario": code,
                "saving": str(value),
                "from": str(running),
                "to": str(running - value),
                "basis": GOVERNED,
                "layers": lever.get("cost_layers") or [],
            })
            running -= value
        # A lever that could not apply is a hole, not a zero. Carried so the
        # bridge shows the opportunity that was NOT counted, with the reason
        # the scenario gave.
        for miss in (scenario.get("levers_not_applicable") or []):
            reason = str(miss.get("reason") or "")
            skipped.append({
                "step": miss.get("family") or miss.get("lever_id"),
                "lever_id": miss.get("lever_id"),
                "scenario": code,
                "saving": "0",
                # "no baseline for this layer" and "nothing in this estate
                # matched" are different findings and only the first is a
                # gap in the model.
                "basis": NO_BASELINE if "no baseline" in reason.lower()
                         else NOT_APPLICABLE,
                "reason": reason,
            })

    for extra in (extra_steps or []):
        value = D(str(extra.get("saving") or 0))
        steps.append({
            "step": extra.get("step"),
            "lever_id": None,
            "scenario": extra.get("scenario"),
            "saving": str(value),
            "from": str(running),
            "to": str(running - value),
            "basis": ESTIMATE,
            "layers": extra.get("layers") or [],
            # An estimate without a stated reason is a number somebody will
            # be asked to defend and cannot.
            "because": extra.get("because"),
        })
        running -= value

    governed = sum((D(s["saving"]) for s in steps if s["basis"] == GOVERNED),
                   D(0))
    estimated = sum((D(s["saving"]) for s in steps if s["basis"] == ESTIMATE),
                    D(0))
    return {
        "baseline": str(baseline),
        "steps": steps,
        # Never folded into the total. A reader has to be able to see the
        # opportunity the model could not size.
        "not_counted": skipped,
        "target": str(running),
        "total_saving": str(governed + estimated),
        "governed_saving": str(governed),
        "estimated_saving": str(estimated),
        "saving_pct": (f"{(governed + estimated) / baseline:.3f}"
                       if baseline else "0.000"),
        # The share of the answer that rests on a governed lever rather than
        # on somebody's judgement. A bridge that is mostly estimate is a
        # hypothesis with a chart.
        "governed_share": (f"{governed / (governed + estimated):.3f}"
                           if (governed + estimated) else "0.000"),
        # The coverage the baseline was priced at.
        #
        # PARTIAL is the ordinary state of an outside-in estimate - 40-70% of
        # scope, or an unsizable pair, or an uncovered material country, or a
        # cost layer in scope with nothing priced in it - and no consumer
        # distinguished it from COMPLETE. The savings page, the recommendation
        # and the questionnaire all treated a 45%-covered estimate with an
        # uncovered material country exactly as they treated a clean one.
        #
        # Carried here because this is where the saving gets discussed. A
        # percentage of a baseline is only as good as the baseline, and the
        # bridge is the one output that shows both.
        "coverage": _coverage_note(coverage),
        "note": _note(steps, skipped, governed, estimated),
    }


def _note(steps, skipped, governed, estimated) -> str:
    """What a reader has to be told before using the number."""
    parts = [
        f"{len(steps)} step(s) in the order they compound - each acts on what "
        f"the ones before it left, so they do not add up to the sum of their "
        f"percentages."]
    if estimated:
        parts.append(
            f"{estimated} of the saving is an analyst estimate with no lever "
            f"behind it and is shown separately for that reason.")
    holes = [s for s in skipped if s["basis"] == NO_BASELINE]
    if holes:
        parts.append(
            f"{len(holes)} lever(s) found no cost pool to act on: "
            f"{', '.join(str(h['step']) for h in holes)}. That is an "
            f"opportunity this estimate could not size, not one worth zero.")
    excluded = [s for s in skipped if s["basis"] == EXCLUDED]
    if excluded:
        parts.append(
            f"{len(excluded)} lever(s) were not booked because a better one "
            f"already removed the same cost: "
            f"{', '.join(str(e['step']) for e in excluded)}. Counted once, "
            f"not missed.")
    misses = [s for s in skipped if s["basis"] == NOT_APPLICABLE]
    if misses:
        parts.append(
            f"{len(misses)} lever(s) had a baseline and matched nothing in "
            f"this estate.")
    return " ".join(parts)


def reconciles(bridge: dict, tolerance="0.01") -> bool:
    """Does baseline minus every step equal the target?

    Checked rather than assumed. The steps are computed by subtraction so
    this should hold by construction - which is exactly the kind of invariant
    that stops holding when somebody inserts a step later.
    """
    walked = D(bridge["baseline"]) - sum(
        (D(s["saving"]) for s in bridge["steps"]), D(0))
    return abs(walked - D(bridge["target"])) <= D(str(tolerance))


def _coverage_note(coverage) -> dict | None:
    """What the baseline's coverage means for the saving above it.

    Returns None where no coverage was supplied rather than inventing a
    reassuring default: a bridge that does not know its own coverage must not
    read as one priced on all of its scope.
    """
    if not coverage:
        return None
    status = str(coverage.get("status") or "").upper()
    effective = coverage.get("effective_coverage_pct")
    qualifications = []
    if coverage.get("unsizable_pairs"):
        qualifications.append(
            f"{len(coverage['unsizable_pairs'])} product/bandwidth pair(s) "
            f"cannot be sized at any approved rate")
    if coverage.get("material_country_breaches"):
        qualifications.append(
            f"material country(ies) not covered: "
            f"{', '.join(coverage['material_country_breaches'])}")
    if coverage.get("unpriced_layers"):
        qualifications.append(
            f"cost layer(s) in scope with nothing priced: "
            f"{', '.join(coverage['unpriced_layers'])}")
    if coverage.get("unpriced_countries"):
        qualifications.append(
            f"{len(coverage['unpriced_countries'])} country(ies) unpriced "
            f"and excluded from the headline")
    return {
        "status": status or None,
        "effective_coverage_pct": (str(effective) if effective is not None
                                   else None),
        "qualifications": qualifications,
        # A saving is a percentage of a baseline, and the baseline is only as
        # good as its coverage. Said plainly because the status alone - one
        # word on another page - has not been carried this far before.
        "what_it_means": (
            f"Every saving above is a share of a baseline priced on "
            f"{effective} of its own scope. "
            + ("That baseline is complete. "
               if status == "COMPLETE" else
               "That baseline is qualified, so the savings inherit the "
               "qualification: they are a percentage of a partial picture, "
               "not of the estate. ")
            + (" ".join(qualifications) if qualifications else "")).strip()
        if effective is not None else None,
    }
