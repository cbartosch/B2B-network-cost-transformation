"""Domain disposition contract (spec 0.3A.1). Maximalist means every in-scope
input domain carries a recorded disposition - not that the search ran longer."""

DOMAINS = [
    (1, "Company and industry profile"), (2, "Location footprint"),
    (3, "Site archetype assumptions"), (4, "Bandwidth and traffic assumptions"),
    (5, "Remote-user population"), (6, "Data-centre and cloud footprint"),
    (7, "Current architecture hypothesis"), (8, "Current vendor and product signals"),
    (9, "Public cost evidence"), (10, "IT spend proxy"),
    (11, "Operating-model cost"), (12, "Contract and sourcing events"),
    (13, "Outage and performance evidence"), (14, "Transformation announcements"),
    (15, "Site growth and shrinkage"), (16, "Regulatory and sovereignty"),
    (17, "Resilience assumptions"), (18, "Market serviceability"),
    (19, "Market unit prices"), (20, "Contract-duration assumptions"),
    (21, "Transformation costs"), (22, "Currency, inflation and tax"),
    (23, "Northstar architecture scenarios"), (24, "Evidence and confidence metadata"),
]

# CLIENT_CONFIRMED (Tranche 3) is first-party data: the client stating
# something about their own estate, attributed to a named person at the
# client. It sits deliberately between ANALYST_ASSERTED_PRIOR and
# EVIDENCED_PUBLIC and is neither of them.
#
#   - Stronger than ANALYST_ASSERTED_PRIOR, which is an analyst's unverified
#     recollection of what someone said. Filing a client's own statement there
#     would understate first-party data, and in the direction that matters.
#   - Weaker than EVIDENCED_PUBLIC, which is independently checkable against a
#     stored source fragment. A client self-report is not independently
#     verifiable: internal records go stale, and the person answering may not
#     be the person who knows.
#
# It therefore carries its own governed confidence weight
# (confidence_policy.client_confirmed_evidence_weight) rather than inheriting
# either neighbour's, and it does NOT trip the 0.6A asserted-baseline ceiling,
# which exists to penalise leaning on an unverified *analyst* claim.
DISPOSITIONS = ("EVIDENCED_PUBLIC", "DERIVED_PUBLIC", "CLIENT_CONFIRMED",
                "BENCHMARK_PRIOR", "ANALYST_ASSERTED_PRIOR", "SIMULATED",
                "DECLARED_UNKNOWN")

# PARTIAL_EVIDENCE_BELOW_THRESHOLD distinguishes "there is nothing public"
# from "there is something and it fell short of the governed minimum". Those
# are different problems with different next steps, and they were recorded
# identically - the findings discarded, the domain reported as having found
# nothing, and the provider call paid for and binned.
#
# It remains a DECLARED_UNKNOWN reason rather than a disposition of its own,
# deliberately: summarise() counts any non-DECLARED_UNKNOWN disposition toward
# domain completeness, which feeds confidence, so a new disposition here would
# have raised confidence for a domain that found too little evidence to use.
# UNRELIABLE_FINDING_RECORDED: the agent found something and could not stand it
# up. Kept because that is informative in itself - the figure is in
# circulation and here is where - and because binning it reduces an agent to a
# deterministic search with extra latency.
UNKNOWN_REASONS = ("NO_PUBLIC_EVIDENCE", "PARTIAL_EVIDENCE_BELOW_THRESHOLD",
                   "UNRELIABLE_FINDING_RECORDED",
                   "BUDGET_EXHAUSTED", "OUT_OF_PERIMETER",
                   "CONFLICTING_EVIDENCE_UNRESOLVED", "NOT_APPLICABLE")


def validate(records: list[dict]) -> list[str]:
    """Returns publication blockers. A V0 cannot publish with an undisposed domain."""
    problems = []
    seen = {r["domain_no"] for r in records}
    for no, name in DOMAINS:
        if no not in seen:
            problems.append(f"domain {no} ({name}) has no disposition")
    for r in records:
        if r["disposition"] not in DISPOSITIONS:
            problems.append(f"domain {r['domain_no']}: unknown disposition {r['disposition']!r}")
        if r["disposition"] == "DECLARED_UNKNOWN" and r.get("reason") not in UNKNOWN_REASONS:
            problems.append(
                f"domain {r['domain_no']}: DECLARED_UNKNOWN requires a controlled reason")
    return problems


def summarise(records: list[dict]) -> dict:
    counts = {d: 0 for d in DISPOSITIONS}
    for r in records:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
    # BUDGET_EXHAUSTED is recorded distinctly from searched-and-empty (0.3A.2)
    budget = [r["domain_no"] for r in records if r.get("reason") == "BUDGET_EXHAUSTED"]
    return {"counts": counts, "budget_exhausted_domains": sorted(budget),
            "declared_unknown": counts.get("DECLARED_UNKNOWN", 0),
            "total_domains": len(DOMAINS)}
