#!/usr/bin/env python3
"""Back up what people typed, and restore it.

    python tools/backup_cases.py backup  --out ./case-backups
    python tools/backup_cases.py restore --file ./case-backups/<file>.json
    python tools/backup_cases.py restore --dir  ./case-backups

Nothing in the application deletes a known fact, and the database sits in a
named volume that survives a rebuild. What does not survive is
`docker compose down -v`, which drops the volume - and that command appears in
this project's own troubleshooting notes as a way past a schema problem.
Someone typing what they know into a register and losing it to a maintenance
instruction is a failure of this system whichever layer removed the row.

Run `backup` before any command with `-v` in it. It writes one readable JSON
file per case: the case, its known facts, its dispositions and any promoted
footprint.

Restore mints new identifiers by default, so restoring into a database that
still holds part of the original does not collide with it. Pass --same-ids for
a restore into an empty database where the original ids should be kept.
"""
import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime


def _call(base, path, token, payload=None, timeout=60.0):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{base}{path}", data=data,
        headers={"Content-Type": "application/json",
                 **({"X-API-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"API returned HTTP {e.code}: {e.read().decode()[:400]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"API unreachable at {base}: {e.reason}")


def backup(args):
    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    cases = _call(args.api, "/v1/outside-in/cases?include_archived=true",
                  args.token).get("cases", [])
    if not cases:
        print("no cases to back up")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    written = 0
    for case in cases:
        cid = case["case_id"]
        payload = _call(args.api, f"/v1/outside-in/cases/{cid}:export",
                        args.token)
        name = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                       for ch in (case.get("subject_entity_legal_name")
                                  or "unnamed"))[:60]
        path = out / f"{stamp}_{name}_{cid[:8]}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        counts = payload.get("counts", {})
        print(f"  {path.name}  "
              + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
        written += 1
    print(f"\n{written} case(s) backed up to {out}")
    return 0


def restore(args):
    files = []
    if args.file:
        files = [pathlib.Path(args.file).expanduser()]
    elif args.dir:
        files = sorted(pathlib.Path(args.dir).expanduser().glob("*.json"))
    if not files:
        print("nothing to restore - pass --file or --dir")
        return 1

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = _call(args.api,
                       f"/v1/outside-in/cases:import?new_case="
                       f"{'false' if args.same_ids else 'true'}",
                       args.token, payload=payload)
        detail = ", ".join(
            f"{v['restored']} {k}" for k, v in result.items()
            if isinstance(v, dict) and "restored" in v)
        print(f"  {path.name} -> case {result['case_id'][:8]}  {detail}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["backup", "restore"])
    ap.add_argument("--out", default="./case-backups")
    ap.add_argument("--file")
    ap.add_argument("--dir")
    ap.add_argument("--same-ids", action="store_true",
                    help="restore under the original identifiers; for a "
                         "restore into an empty database")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token")
    args = ap.parse_args()
    return backup(args) if args.action == "backup" else restore(args)


if __name__ == "__main__":
    sys.exit(main())
