"""Fill case.industry_as_resolved from the candidate each case resolved to.

The column is written when an entity is confirmed, and every case that
existed before it was added is already confirmed - so without this it stays
null on all of them and the cross-check it exists for can never fire on the
set that found the problem.

Deliberately NOT part of migration v69. A migration is a deterministic
schema change; a best-effort data copy has no business sharing its
transaction. The first version did exactly that, inside a try/except, on the
reasoning that an advisory backfill must not stop a migration - and in
PostgreSQL a failed statement aborts the surrounding transaction, so the
catch changed nothing except which error got reported. The API refused to
start on a column it had successfully added.

Here, failing is allowed to mean something.

    docker compose exec api python tools/backfill_resolved_industry.py
"""
import sys

from sqlalchemy import select, update

from app import db
from app.domain import bics


def main() -> int:
    filled = agree = disagree = silent = 0
    with db.SessionLocal() as s:
        cases = s.execute(select(
            db.case.c.case_id, db.case.c.industry,
            db.case.c.resolved_entity_id,
            db.case.c.industry_as_resolved)).all()
        candidates = {
            r.candidate_id: r.industry
            for r in s.execute(select(db.entity_candidate.c.candidate_id,
                                      db.entity_candidate.c.industry)).all()}
        for case in cases:
            if case.industry_as_resolved:
                continue
            text = candidates.get(case.resolved_entity_id)
            if not text:
                continue
            s.execute(update(db.case)
                      .where(db.case.c.case_id == case.case_id)
                      .values(industry_as_resolved=text))
            filled += 1
            verdict = bics.industry_text_agrees(case.industry, text)
            if verdict is True:
                agree += 1
            elif verdict is False:
                disagree += 1
                print(f"  DISAGREES  {case.industry:<26}{text}")
            else:
                silent += 1
        s.commit()
    print(f"\nfilled {filled} case(s): {agree} agree, {disagree} disagree, "
          f"{silent} with nothing comparable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
