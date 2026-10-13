"""Admit named promoted prices into the rate card.

A price entering the card prices every circuit at its (country, product,
tier) in every case, so this is deliberate and attributed. Rows are named
explicitly - there is no "approve everything" - and the band each one takes
is reported, because `promote` stores a single observation as a point and a
point is immune to evidence widening.

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \
        python tools/approve_prices.py --by "name" ES-DIA-100-researched ...'
"""
import argparse
import sys

from app import db
from app.domain import promotion


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("row_ids", nargs="+")
    ap.add_argument("--by", required=True,
                    help="the person approving; recorded on every row")
    ap.add_argument("--revoke", default="",
                    help="take these rows back out of the card, with this "
                         "reason")
    args = ap.parse_args()

    with db.SessionLocal() as s:
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
