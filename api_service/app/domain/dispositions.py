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

DISPOSITIONS = ("EVIDENCED_PUBLIC", "DERIVED_PUBLIC", "BENCHMARK_PRIOR",
                "ANALYST_ASSERTED_PRIOR", "SIMULATED", "DECLARED_UNKNOWN")

UNKNOWN_REASONS = ("NO_PUBLIC_EVIDENCE", "BUDGET_EXHAUSTED", "OUT_OF_PERIMETER",
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
