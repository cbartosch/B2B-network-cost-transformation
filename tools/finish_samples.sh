#!/usr/bin/env bash
# Wait out the repair pass, deploy the two fixes it was blocking, then
# re-offer every company's findings to the estimate.
#
# The restart in the middle is the reason this is a script rather than three
# commands: /tmp inside the api container does not survive one, and the
# sample artifacts live there. They are copied out before and back after.
set -u
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

say() { printf '\n== %s == %s\n' "$(date +%H:%M:%S)" "$*"; }

# ---------------------------------------------------------------- 1. wait
say "waiting for the repair pass"
while :; do
  n=$(docker compose exec -T api sh -c \
      'grep -lE "completed [0-9]+, failed" /tmp/logs/rep*.log 2>/dev/null | wc -l' \
      2>/dev/null | tr -d '\r ')
  d=$(docker compose exec -T api sh -c \
      'grep -h "done in" /tmp/logs/rep*.log 2>/dev/null | wc -l' \
      2>/dev/null | tr -d '\r ')
  [ "${n:-0}" = "5" ] && break
  printf '  repair %s/13 companies, %s/5 streams exited\n' "${d:-?}" "${n:-0}"
  sleep 180
done
say "repair finished"
docker compose exec -T api sh -c 'grep -h "done in\|\[FAIL\]" /tmp/logs/rep*.log' \
  | sed 's/^ *//' | cut -c1-90

# ------------------------------------------------------- 2. save and restart
say "copying artifacts out before the restart"
rm -rf ./_samples_backup
docker compose cp api:/tmp/samples ./_samples_backup || exit 1
echo "  $(ls ./_samples_backup | wc -l) entries saved"

say "restarting api to deploy P-14 and P-15"
docker compose up -d api || exit 1
for _ in $(seq 1 30); do
  sleep 5
  curl -sf http://localhost:8000/v1/ready >/dev/null 2>&1 && break
done
curl -s http://localhost:8000/v1/ready | head -c 80; echo

say "restoring artifacts"
docker compose exec -T api sh -c 'mkdir -p /tmp/samples /tmp/logs'
docker compose cp ./_samples_backup/. api:/tmp/samples/ || exit 1
docker compose cp tools/run_samples.py api:/tmp/run_samples.py || exit 1
docker compose exec -T api sh -c 'ls /tmp/samples | wc -l'

# -------------------------------------------------------- 3. the repromote
say "re-promote pass: no provider calls"
docker compose exec -T api sh -c '
cd /app
rm -f /tmp/logs/promo*.log
p1="tesco,inditex,deutsche-post-dhl,bnp-paribas"
p2="allianz,mcdonalds,volkswagen,novartis"
p3="shell,iberdrola,accor,lufthansa"
p4="basf,nestle,fresenius,siemens"
p5="saint-gobain,rio-tinto,deutsche-bahn,unilever"
i=1
for g in "$p1" "$p2" "$p3" "$p4" "$p5"; do
  PYTHONPATH=/app nohup python -u /tmp/run_samples.py --out /tmp/samples \
    --repromote --only "$g" > /tmp/logs/promo$i.log 2>&1 &
  i=$((i+1))
done
wait
echo "--- re-promote results ---"
grep -hE "footprint:|done in|\[FAIL\]|completed" /tmp/logs/promo*.log | sed "s/^ *//"'

say "saving the finished set"
rm -rf ./_samples_backup
docker compose cp api:/tmp/samples ./_samples_backup
echo "  $(ls ./_samples_backup | wc -l) entries"
say "done"
