#!/usr/bin/env bash
# Wait for the domain fill, verify every company reached 17, rebuild, gate,
# commit. Fails without committing if any company is still short.
set -u
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
say() { printf '\n== %s == %s\n' "$(date +%H:%M:%S)" "$*"; }

say "waiting for the fill"
while :; do
  n=$(docker compose exec -T api sh -c \
      'grep -lE "completed [0-9]+, failed" /tmp/logs/fill_*.log 2>/dev/null | wc -l' \
      2>/dev/null | tr -d '\r ')
  [ "${n:-0}" = "5" ] && break
  d=$(docker compose exec -T api sh -c \
      'grep -hcE "domain +[0-9]+ " /tmp/logs/fill_*.log 2>/dev/null | paste -sd+ -' \
      2>/dev/null | tr -d '\r ')
  printf '  %s of 57 calls, %s/5 streams done\n' "${d:-?}" "${n:-0}"
  sleep 180
done

say "fill outcome"
docker compose exec -T api sh -c \
  'grep -hE "repair:|footprint:|done in|\[FAIL\]|completed" /tmp/logs/fill_*.log' | sed 's/^ *//'

say "coverage, from the database"
docker compose exec -T api python -c '
import json
from sqlalchemy import select
from app import db
s = db.SessionLocal()
AGENT = {1,2,6,7,8,9,10,12,13,14,15,16,18,19,20,21,22}
led = json.load(open("/tmp/samples/_cases.json"))
short = []
for slug, cid in sorted(led.items()):
    rows = s.execute(select(db.domain_disposition.c.domain_no,
                            db.domain_disposition.c.agent_run_id).where(
        db.domain_disposition.c.case_id == cid)).all()
    done = {r.domain_no for r in rows if r.agent_run_id} & AGENT
    if len(done) < 17:
        short.append((slug, len(done), sorted(AGENT - done)))
        print(f"  {slug}: {len(done)}/17 still missing {sorted(AGENT - done)}")
print(f"  fully researched: {len(led) - len(short)} of {len(led)}")
'

say "pulling artifacts"
rm -rf ./_samples_backup
docker compose cp api:/tmp/samples ./_samples_backup || exit 1

say "rebuilding summary"
python tools/build_sample_summary.py --out ./_samples_backup --build 4.272.0 || exit 1

say "gate"
# Every company must now be at 17. The floor is the whole set, not a
# nominated pair - that is the point of this pass.
python tools/check_samples.py --out ./_samples_backup \
    --baseline samples/outside_in \
    --repaired "$(python -c '
import json,pathlib
print(",".join(sorted(p.name for p in pathlib.Path("_samples_backup").iterdir() if p.is_dir())))')" \
  || { echo "GATE FAILED - not committing"; exit 1; }

say "committing"
cp -r ./_samples_backup/. samples/outside_in/ || exit 1
git add -A samples/ 2>&1 | grep -v "LF will be" | head -3
git commit -q -F - <<'MSG'
Every company researched on all seventeen agent-routed domains

The set has carried partial coverage since the first run: a mean of 14.2 of
17, with twelve companies short and Volkswagen, Accor, Deutsche Bahn and
Siemens under ten. Every gap was a domain the fallback disposed
BENCHMARK_PRIOR after a provider failure, not a domain an agent looked at
and found nothing in.

57 calls, bought only where a gap existed - --repair re-researches the
domains the net disposed and keeps everything an agent answered, so a
company at 16 of 17 cost one call rather than seventeen.

The summary and highlights are rebuilt across all twenty because both are
derived. Estimates move where new domains changed a footprint or a
disposition mix.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
git log --oneline -1
git push -q origin HEAD && echo pushed
say "done"
