#!/usr/bin/env bash
# Wait for the provider to actually be reachable, then repair the two
# companies that caught the outages.
#
# Reachability means a TLS handshake completing, not a DNS lookup resolving.
# The last repair ran on a host that resolved api.anthropic.com perfectly and
# could not complete a handshake with it, so 98 of 106 agent runs failed with
# ProviderUnavailable and two companies came back with four and two
# researched domains. Checking the wrong layer is how that happened twice.
set -u
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

say() { printf '\n== %s == %s\n' "$(date +%H:%M:%S)" "$*"; }

probe() {
  docker compose exec -T api python -c '
import urllib.error, urllib.request
try:
    urllib.request.urlopen(urllib.request.Request(
        "https://api.anthropic.com/v1/messages", method="POST"), timeout=20)
except urllib.error.HTTPError:
    print("UP")          # 4xx is the API answering, which is reachability
except Exception as e:
    print("DOWN", type(e).__name__)
' 2>/dev/null | tr -d '\r'
}

say "waiting for the provider"
tries=0
while :; do
  r=$(probe)
  case "$r" in
    UP*) echo "  reachable"; break ;;
  esac
  tries=$((tries + 1))
  printf '  %s (attempt %s)\n' "${r:-no answer}" "$tries"
  # Two consecutive hours of this is not a blip worth burning calls after.
  [ "$tries" -ge 60 ] && { echo "still down after 60 attempts; giving up"; exit 1; }
  sleep 120
done

# Twice in a row, a minute apart, before spending anything.
sleep 60
[ "$(probe)" = "UP" ] || { echo "flapped on recheck; not starting"; exit 1; }
say "stable on recheck"

say "repairing lufthansa and unilever"
docker compose exec -T api sh -c '
cd /app
rm -f /tmp/logs/fix2_*.log
for s in lufthansa unilever; do
  PYTHONPATH=/app nohup python -u /tmp/run_samples.py --out /tmp/samples \
    --repair --only "$s" > /tmp/logs/fix2_$s.log 2>&1 &
done
wait
echo "--- outcome ---"
grep -hE "repair:|promote |footprint:|done in|\[FAIL\]|completed" /tmp/logs/fix2_*.log | sed "s/^ *//"
echo "--- verdicts ---"
grep -hoE "(EVIDENCED_PUBLIC|DECLARED_UNKNOWN|CONTRADICTED|-) +[0-9]+\.[0-9]+s" /tmp/logs/fix2_*.log \
  | awk "{print \$1}" | sort | uniq -c'

say "researched counts"
docker compose exec -T api python -c '
import json
from sqlalchemy import select
from app import db
s = db.SessionLocal()
led = json.load(open("/tmp/samples/_cases.json"))
for slug in ("lufthansa", "unilever"):
    rows = s.execute(select(db.domain_disposition.c.agent_run_id).where(
        db.domain_disposition.c.case_id == led[slug])).all()
    print(f"  {slug}: {sum(1 for r in rows if r.agent_run_id)} of 17 researched")
'
say "done"
