"""Admit named promoted prices into the rate card.

A price entering the card prices every circuit at its (country, product,
tier) in every case, so this is deliberate and attributed. Rows are named
explicitly - there is no "approve everything" - and the band each one takes
is reported, because `promote` stores a single observation as a point and a
point is immune to evidence widening.

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \
        python tools/approve_prices.py --by "name" ES-DIA-100-researched ...'

Or every decision in a register at once:

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \
        python tools/approve_prices.py --by "name" \
            --decisions /src/samples/price_decisions.csv'

The register has one line per researched price: APPROVE, with the band to
approve at or blank for the card's width; REJECT, applied as a revocation
with its reason, so the next re-run does not propose the same figure again;
or HOLD, undecided - a row approved or revoked earlier is reopened. Each line
is the state its row is brought to, so applying it twice changes nothing.

Each line names the figure it decided, in `base` and `currency`. A row that
now holds a different figure is refused, not decided: one row stands for a
country, product and tier across every company, and an approval applied to
whatever figure the last company's research left there approves a number
nobody looked at.
"""
import argparse
import csv
import sys
from decimal import Decimal

from sqlalchemy import select

from app import db
from app.domain import promotion

DECISIONS = ("APPROVE", "REJECT", "HOLD")


def _band(line) -> tuple:
    """The band a line states, or (None, None) for the card's width."""
    low, high = (line.get("band_low") or "").strip(), \
        (line.get("band_high") or "").strip()
    if bool(low) != bool(high):
        raise promotion.NotPromotable(
            f"{line['id']}: a band needs both ends, or neither for the "
            f"card's width")
    return (Decimal(low), Decimal(high)) if low else (None, None)


def _approved_at(row, low, high) -> bool:
    """Is the row approved, at the band this line asks for?"""
    if not row.approved:
        return False
    if low is None:
        base = Decimal(str(row.base))
        low = base * (Decimal("1") - promotion.CARD_BAND_SHARE)
        high = base * (Decimal("1") + promotion.CARD_BAND_SHARE)
    cents = Decimal("0.01")
    return (Decimal(str(row.low)).quantize(cents) == low.quantize(cents)
            and Decimal(str(row.high)).quantize(cents) == high.quantize(cents))


def _same_figure(row, line) -> bool:
    """Does the row still hold the figure this line decided?"""
    cents = Decimal("0.01")
    return (Decimal(str(row.base)).quantize(cents)
            == Decimal(line["base"]).quantize(cents)
            and (row.currency or "USD").upper()
            == (line.get("currency") or "USD").upper())


def apply_decisions(session, lines, *, by: str) -> list:
    """Bring each named row to the state its line asks for.

    Validated whole before anything is written: a register with one
    malformed line applies nothing, rather than half of itself.
    """
    for line in lines:
        if (line.get("decision") or "").upper() not in DECISIONS:
            raise promotion.NotPromotable(
                f"{line.get('id')}: decision must be one of {DECISIONS}, "
                f"not {line.get('decision')!r}")
        reason = (line.get("reason") or "").strip()
        if line["decision"].upper() in ("REJECT", "HOLD") and not reason:
            raise promotion.NotPromotable(
                f"{line['id']}: a rejection or a hold needs its reason - it "
                f"is what the next steward reads")
        for mark in (promotion.REVOKED_MARK, promotion.REOPENED_MARK):
            if mark in reason.lower():
                raise promotion.NotPromotable(
                    f"{line['id']}: the reason cannot contain {mark!r} - the "
                    f"note is read for it to tell revoked from open")
        if line["decision"].upper() != "HOLD" and not (line.get("base")
                                                       or "").strip():
            raise promotion.NotPromotable(
                f"{line['id']}: a decision names the figure it was about, "
                f"in base and currency")
        _band(line)

    out = []
    for line in lines:
        row_id, decision = line["id"], line["decision"].upper()
        row = session.execute(select(db.unit_cost_prior).where(
            db.unit_cost_prior.c.id == row_id)).first()
        if row is None:
            out.append((row_id, "MISSING", "no such price row"))
            continue
        state = promotion.decision_on(row)
        if decision == "HOLD":
            if state is None:
                out.append((row_id, "HELD", "undecided"))
                continue
            promotion.reopen_price(session, row_id=row_id, reopened_by=by,
                                   reason=line["reason"].strip())
            out.append((row_id, "REOPENED",
                        f"was {state['decision'].lower()}; "
                        f"{line['reason'].strip()}"))
        elif not _same_figure(row, line):
            out.append((row_id, "FIGURE_CHANGED",
                        f"decided at {line['base']} {line.get('currency')}, "
                        f"the row now holds {row.base} {row.currency} - "
                        f"not applied"))
        elif decision == "APPROVE":
            low, high = _band(line)
            if _approved_at(row, low, high):
                out.append((row_id, "UNCHANGED", "already approved"))
                continue
            res = promotion.approve_price(session, row_id=row_id,
                                          approved_by=by, low=low, high=high)
            out.append((row_id, "APPROVED",
                        f"{res['low']}/{res['base']}/{res['high']} "
                        f"{row.currency}, band {res['band_origin']}"))
        else:
            if state and state["decision"] == "REVOKED":
                out.append((row_id, "UNCHANGED", "already revoked"))
                continue
            promotion.revoke_price(session, row_id=row_id, revoked_by=by,
                                   reason=line["reason"].strip())
            out.append((row_id, "REVOKED", line["reason"].strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("row_ids", nargs="*")
    ap.add_argument("--by", required=True,
                    help="the person approving; recorded on every row")
    ap.add_argument("--revoke", default="",
                    help="take these rows back out of the card, with this "
                         "reason")
    ap.add_argument("--decisions", default="",
                    help="a register of APPROVE / REJECT / HOLD lines to "
                         "apply, one per researched price")
    args = ap.parse_args()
    if bool(args.decisions) == bool(args.row_ids):
        ap.error("name rows, or give --decisions - one or the other")

    with db.SessionLocal() as s:
        if args.decisions:
            with open(args.decisions, encoding="utf-8") as f:
                lines = list(csv.DictReader(f))
            try:
                results = apply_decisions(s, lines, by=args.by)
            except promotion.NotPromotable as exc:
                print(f"  REFUSED  {exc}")
                return 1
            for row_id, outcome, detail in results:
                print(f"  {outcome.lower():<9} {row_id}: {detail}")
            counts = {}
            for _id, outcome, _detail in results:
                counts[outcome] = counts.get(outcome, 0) + 1
            print("  " + ", ".join(f"{n} {k.lower()}"
                                   for k, n in sorted(counts.items())))
            return 0

        for row_id in args.row_ids:
            try:
                if args.revoke:
                    out = promotion.revoke_price(s, row_id=row_id,
                                                 revoked_by=args.by,
                                                 reason=args.revoke)
                    print(f"  revoked  {out['country']}/{out['product']} "
                          f"{out['bandwidth_mbps']} Mbps: {args.revoke}")
                    continue
                out = promotion.approve_price(s, row_id=row_id,
                                              approved_by=args.by)
            except promotion.NotPromotable as exc:
                print(f"  REFUSED  {row_id}: {exc}")
                continue
            print(f"  approved {out['country']}/{out['product']} "
                  f"{out['bandwidth_mbps']} Mbps  "
                  f"{out['low']}/{out['base']}/{out['high']}  "
                  f"grade {out['evidence_grade']}  band {out['band_origin']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
