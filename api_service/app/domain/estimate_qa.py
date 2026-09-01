"""Answering questions about a published estimate, without letting it invent one.

An analyst holding a V0 wants to ask three kinds of thing: how was this
calculated, why is confidence where it is, and what would improve it. All three
are answerable from what the run already recorded - the snapshot pins the
method, the coverage basis, the origin mix and the ceilings that were applied,
and the dispositions carry every finding and its grade.

Two rules make this safe to build.

**The gaps are computed, not asked for.** "What is missing" has a deterministic
answer: which countries have no approved price, which domains are
DECLARED_UNKNOWN and why, which topology fields are still seeded assumptions,
which facts rest on one source. Asking a model to work that out would invite a
plausible list; computing it and asking the model to explain and prioritise it
keeps the facts arithmetic and the judgement language.

**Every figure in the answer must already be in the packet.** The model is
explaining a calculation, not performing one, so a number it states that the
snapshot does not contain is a fabrication however plausible - and an
explanation of a cost model is exactly where a fabricated figure would be
believed. `unsupported_figures` finds them deterministically and the gate
refuses the answer.

What this deliberately is not: an advisory service. It explains what was
computed and what is absent. It does not recommend a scenario, size a saving or
approve anything - LLM-07 exists for the first, and the last is a named
person's act.
"""
import re
from decimal import Decimal, InvalidOperation

# A figure worth checking: three or more digits, or any decimal. Two-digit
# numbers are years, counts of domains and percentages the answer may
# legitimately reason with, and treating those as citations would reject an
# answer for saying "17 domains".
FIGURE = re.compile(r"\d[\d,\u00a0.]{2,}")


def _norm(text: str) -> str:
    """Digits only, so 2,600 and 2600 and 2.600 compare equal."""
    return re.sub(r"[,.\u00a0 ]", "", str(text))


def _figures(payload, into: set) -> set:
    """Every number anywhere in a nested structure, normalised."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            _figures(key, into)
            _figures(value, into)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _figures(item, into)
    elif payload is not None and not isinstance(payload, bool):
        text = str(payload)
        for match in FIGURE.findall(text):
            digits = _norm(match)
            if digits:
                into.add(digits)
                # A rounded restatement of a packet figure is legitimate - an
                # answer saying "about 2.9 million" of 2,855,220 is explaining,
                # not inventing - so leading-digit prefixes count as present.
                for length in range(2, len(digits)):
                    into.add(digits[:length])
        try:
            value = Decimal(str(payload))
        except (InvalidOperation, TypeError, ValueError):
            pass
        else:
            into.add(_norm(f"{value:f}"))
            into.add(_norm(f"{value:.0f}"))
    return into


def _rounds_to(claim: str, known: set) -> bool:
    """Is the claim a rounded restatement of a figure the packet contains?

    "about 2.9 million" of 2,855,220 is explaining, not inventing, and an
    answer that may not round is an answer nobody can read. Compared by
    significant digits at the claim's own precision, so 2.9 matches 2855220
    (2.9 million) and 0.782 does not match 0.550.
    """
    digits = _norm(claim).lstrip("0")
    if not digits:
        return False
    width = len(digits)
    for value in known:
        head = value.lstrip("0")
        if not head or len(head) < width:
            continue
        # Both directions: truncated and half-up. "2.9 million" of 2,855,220
        # rounds up from 2.85 and truncating alone read it as invented, which
        # would refuse an answer for the reasonable act of rounding.
        if head[:width] == digits:
            return True
        if len(head) > width:
            # Half-up at the claim's precision. round(285, -1) is 280, which is
            # banker's rounding on the wrong digit - so the arithmetic is done
            # explicitly: 2855220 at two significant digits is 29, and reading
            # it as 28 refused an answer for rounding the way a person does.
            try:
                significant = int(head[:width])
                if int(head[width]) >= 5:
                    significant += 1
            except (ValueError, IndexError):
                continue
            if str(significant) == digits:
                return True
    return False


def unsupported_figures(answer: str, packet: dict) -> list[str]:
    """Figures the answer states that the packet does not contain.

    The model is explaining a calculation, not performing one. A number the
    snapshot does not contain is a fabrication however plausible, and an
    explanation of a cost model is exactly where one would be believed.
    """
    known = _figures(packet, set())
    unsupported = []
    for match in FIGURE.findall(answer or ""):
        digits = _norm(match)
        if digits and digits not in known and not _rounds_to(match, known):
            unsupported.append(match)
    return sorted(set(unsupported))


def gaps(*, snapshot: dict, dispositions: list[dict],
         topology_basis: dict | None = None,
         known_facts: list[dict] | None = None) -> list[dict]:
    """What is absent, computed. Ordered by what it costs the estimate.

    Each gap names the thing missing, why it matters, and the concrete act that
    would close it - because "coverage is 55%" is a measurement and "research
    domain 19 for FR and NL prices" is a next step.
    """
    found = []
    coverage = snapshot.get("coverage") or {}
    confidence = snapshot.get("confidence") or {}

    unpriced = coverage.get("unpriced_countries") or []
    if unpriced:
        found.append({
            "gap": "unpriced countries",
            "detail": f"{', '.join(unpriced)} have no approved price for the "
                      f"products their sites use, so their circuits are "
                      f"excluded from the total rather than estimated.",
            "costs": "coverage, and therefore the confidence ceiling",
            "closes_it": "research domain 19 for those countries and promote "
                         "the prices, or approve a benchmark band for them",
        })

    pairs = coverage.get("unpriced_pairs") or []
    if pairs and not unpriced:
        found.append({
            "gap": "unpriced product tiers",
            "detail": f"{len(pairs)} (country, product, bandwidth) "
                      f"combination(s) have no approved price at or above the "
                      f"bandwidth required.",
            "costs": "coverage",
            "closes_it": "add a price band at that tier, or correct the "
                         "archetype bandwidth if the tier is wrong",
        })

    unknown = [d for d in dispositions
               if d.get("disposition") == "DECLARED_UNKNOWN"]
    by_reason = {}
    for d in unknown:
        by_reason.setdefault(d.get("reason") or "unstated", []).append(
            f"{d.get('domain_no')}. {d.get('domain_name')}")
    for reason, domains in sorted(by_reason.items()):
        found.append({
            "gap": f"domains declared unknown ({reason})",
            "detail": f"{len(domains)} domain(s): {', '.join(domains[:6])}"
                      + (" and others" if len(domains) > 6 else ""),
            "costs": "domain completeness, which feeds the target-cost "
                     "confidence component",
            "closes_it": (
                "re-run research now that the reason is recorded - a partial "
                "finding below the source threshold is kept and visible"
                if reason == "PARTIAL_EVIDENCE_BELOW_THRESHOLD" else
                "add an alias on page 1 if the source described the entity "
                "under another name"
                if reason == "OUT_OF_PERIMETER" else
                "research the domain, or register what the team knows"),
        })

    assumed = (topology_basis or {}).get("assumed_fields") or []
    if assumed:
        found.append({
            "gap": "topology still assumed",
            "detail": f"{len(assumed)} site-type field(s) come from the seeded "
                      f"prior or an industry default rather than this case's "
                      f"evidence: {', '.join(assumed[:6])}"
                      + (" and others" if len(assumed) > 6 else ""),
            "costs": "nothing measurable - a simulated topology is a sizing "
                     "instrument either way (0.3B) - but the circuit mix and "
                     "the bandwidths are guesses about this client",
            "closes_it": "research domains 7, 8, 14 and 15 and promote the "
                         "findings, or register what the team knows",
        })

    thin = [f for f in (known_facts or [])
            if f.get("corroboration_state") in (None, "", "PENDING",
                                                "UNCORROBORATED")]
    if thin:
        found.append({
            "gap": "uncorroborated assertions",
            "detail": f"{len(thin)} registered fact(s) have not been "
                      f"corroborated against a public source.",
            "costs": "the 0.6A ceiling caps the baseline component at 0.50 "
                     "while an asserted quantity carries the estimate",
            "closes_it": "corroborate them on page 2 - a corroborated fact is "
                         "superseded by the public fact that confirmed it and "
                         "stops counting toward asserted share",
        })

    # Ported from the duplicate implementation before deleting it. Two gaps
    # existed only there, and removing the module without them would have
    # repeated exactly the mistake that lost page 2 its entry form: a slice
    # that took a feature out with the thing it was replacing.
    if (snapshot.get("pins") or {}).get("footprint_basis", {}).get("needs_split"):
        found.append({
            "gap": "unallocated footprint",
            "detail": "a registered site total is not split by country and "
                      "site type, so the whole estate sits in one row.",
            "costs": "every circuit's product and bandwidth - a row states "
                     "that every site in it is identical, and the whole row is "
                     "priced at that archetype's tier",
            "closes_it": "allocate it by country and site type on the "
                         "simulation page",
        })

    anchor = (snapshot.get("pins") or {}).get("anchor_basis") or {}
    if anchor and anchor.get("anchor_origin") not in (None, "", "EVIDENCED_PUBLIC"):
        found.append({
            "gap": "asserted anchor",
            "detail": f"the anchor is a typed figure "
                      f"({anchor.get('anchor_origin')}), not a disclosed one.",
            "costs": "the whole ANCHOR method rests on it, and an asserted "
                     "anchor caps the baseline component under 0.6A",
            "closes_it": "research domain 9 or 10 and promote the cost line - "
                         "it then arrives as evidence with its sources",
        })

    ceilings = confidence.get("ceilings_applied") or []
    if ceilings:
        found.append({
            "gap": "confidence ceilings applied",
            "detail": f"{len(ceilings)} ceiling(s) bound the score: "
                      f"{', '.join(str(c) for c in ceilings[:4])}.",
            "costs": "the score cannot rise above these regardless of what "
                     "else improves",
            "closes_it": "a stage ceiling lifts only by advancing the stage; "
                         "an evidence ceiling lifts by replacing assertions "
                         "with public evidence",
        })

    return found


def packet(*, case: dict, snapshot: dict, dispositions: list[dict],
           topology_basis: dict | None = None,
           known_facts: list[dict] | None = None,
           progression: dict | None = None) -> dict:
    """Everything a question about this estimate can be answered from.

    Deliberately the stored record and nothing derived here: if a figure is not
    in the snapshot it is not in the packet, and an answer that states it will
    be refused. That is the point - the model explains what was computed.
    """
    coverage = snapshot.get("coverage") or {}
    confidence = snapshot.get("confidence") or {}
    pins = snapshot.get("pins") or {}
    return {
        "subject": case.get("subject_entity_legal_name"),
        "method": pins.get("estimate_method", "BUILD_UP"),
        "v0_status": snapshot.get("v0_status"),
        "calculation_version": pins.get("calculation_version"),
        "simulation_model_version": pins.get("simulation_model_version"),
        "current_tco": snapshot.get("current_tco"),
        "by_layer": snapshot.get("by_layer"),
        "scenarios": snapshot.get("scenarios"),
        "confidence": confidence,
        "coverage": coverage,
        "origin_breakdown": pins.get("origin_breakdown"),
        "anchor_basis": pins.get("anchor_basis"),
        "topology_basis": topology_basis or {},
        "asserted_share": snapshot.get("asserted_share"),
        "simulated_share": snapshot.get("simulated_share"),
        "dispositions": [
            {"domain_no": d.get("domain_no"), "domain_name": d.get("domain_name"),
             "disposition": d.get("disposition"), "reason": d.get("reason"),
             "grade": ((d.get("evidence") or {}).get("reliability") or {})
                      .get("grade")}
            for d in dispositions],
        "known_facts": [
            {"fact_class": f.get("fact_class"), "subject": f.get("subject"),
             "value_base": f.get("value_base"), "unit": f.get("unit"),
             "corroboration_state": f.get("corroboration_state"),
             "basis": f.get("basis")}
            for f in (known_facts or [])],
        "progression": progression or {},
        "gaps": gaps(snapshot=snapshot, dispositions=dispositions,
                     topology_basis=topology_basis, known_facts=known_facts),
    }
