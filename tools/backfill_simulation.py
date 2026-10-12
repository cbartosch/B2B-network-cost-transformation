"""Replace each sample's simulation.json with the simulation itself.

The driver stored what the poll endpoint returns, which is a progress
summary: status, percent, output_hash, cancel_requested. None of the
simulation is in it - not the site count it generated, not the circuits, not
the serviceability table, and not the pins that say what it was generated
from. A file called simulation.json that contains no simulation is worse than
no file, because it looks like the thing it is missing.

The row carries all of it, so this reads it back per case and rewrites the
file. Run inside the api container, after a run:

    docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \\
        python tools/backfill_simulation.py --out /tmp/samples'
"""
import argparse
import json
import pathlib

from sqlalchemy import select

from app import db

# estate and sample_topology are per-site arrays - tens of thousands of rows
# on a large estate, and the same information the aggregates already carry.
# Dropped by default so a sample directory stays readable and committable;
# --full keeps them.
BULKY = ("estate", "sample_topology")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--full", action="store_true",
                    help="keep the per-site estate and topology arrays")
    args = ap.parse_args()
    root = pathlib.Path(args.out)

    done, skipped = [], []
    for d in sorted(root.iterdir()):
        man = d / "manifest.json" if d.is_dir() else None
        if not man or not man.exists():
            continue
        m = json.loads(man.read_text("utf-8"))
        case_id = m.get("case_id")

        with db.SessionLocal() as s:
            row = s.execute(select(db.simulation_run).where(
                db.simulation_run.c.case_id == case_id).order_by(
                db.simulation_run.c.created_at.desc())).first()
        if row is None:
            skipped.append(d.name)
            continue

        out = dict(row.output or {})
        dropped = []
        if not args.full:
            for k in BULKY:
                if k in out:
                    dropped.append(f"{k} ({len(out[k])} rows)")
                    out.pop(k)

        payload = {
            "simulation_run_id": row.simulation_run_id,
            "case_id": row.case_id,
            "model_version": row.model_version,
            "seed": row.seed,
            "ensemble_size": row.ensemble_size,
            "status": row.status,
            "output_hash": row.output_hash,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            # What it was told to generate.
            "params": row.params,
            # What it was generated from. The runner rebuilds a resumed pass
            # from these, so they are the provenance for every number above.
            "pinned_priors": row.pinned_priors,
            "output": out,
        }
        if dropped:
            payload["output_omitted"] = {
                "fields": dropped,
                "why": ("per-site arrays, the same information the "
                        "aggregates carry; re-run with --full to keep them"),
            }

        (d / "simulation.json").write_text(
            json.dumps(payload, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8")
        done.append(f"{d.name} ({out.get('sites')} sites)")

    for x in done:
        print(f"  rewrote {x}")
    if skipped:
        print(f"  no simulation row: {', '.join(skipped)}")
    print(f"{len(done)} rewritten, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
