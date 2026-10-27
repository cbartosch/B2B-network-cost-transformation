"""Re-read stored source captures with the reader the fetch uses now.

Captures stored before the fetch refused binary - a PDF or a spreadsheet
decoded as text - kept a claim marked verified on the strength of digits
inside the binary. This applies the fixed reader to what was stored, and
grades a finding again only where research graded it and nobody has changed
its disposition since. No provider is called; run it once, then re-run the
samples.

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app         python tools/reverify_captures.py'
"""
import sys

from app.db import SessionLocal
from app.domain import policy, research
from app.routers import api


def main() -> int:
    with SessionLocal() as s:
        grading = research._grading_policy(
            api._research_policy(s),
            policy.TriangulationPolicy.from_rows(
                api._thresholds(s, "triangulation_policy")))
        changed = research.reverify_dispositions(s, policy=grading)
    for c in changed:
        print(f"  {c['case_id']} domain {c['domain_no']}: "
              f"{c['captures_reread']} capture(s) re-read; grade "
              f"{c['grade'][0]} -> {c['grade'][1]}; disposition "
              f"{c['disposition'][0]} -> {c['disposition'][1]}")
    regraded = sum(1 for c in changed if c["grade"][0] != c["grade"][1]
                   or c["disposition"][0] != c["disposition"][1])
    print(f"{len(changed)} finding(s) re-read, {regraded} of them regraded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
