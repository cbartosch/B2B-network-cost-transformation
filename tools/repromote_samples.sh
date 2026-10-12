#!/usr/bin/env bash
# Deploy the current image and re-offer every company's findings to it.
#
# No provider calls. Separated from finish_samples.sh because the waiting
# half of that script is done: this is the part worth being able to repeat,
# and it has had to be repeated.
set -u
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

say() { printf '\n== %s == %s\n' "$(date +%H:%M:%S)" "$*"; }

say "saving artifacts before the restart"
rm -rf ./_samples_backup
docker compose cp api:/tmp/samples ./_samples_backup || exit 1
echo "  $(ls ./_samples_backup | wc -l) entries"

say "restarting api"
docker compose up -d api || exit 1
for _ in $(seq 1 40); do
  sleep 5
  curl -sf http://localhost:8000/v1/ready >/dev/null 2>&1 && break
done
curl -s http://localhost:8000/v1/ready | head -c 80; echo

say "restoring"
docker compose exec -T api sh -c 'mkdir -p /tmp/samples /tmp/logs'
docker compose cp ./_samples_backup/. api:/tmp/samples/ || exit 1
docker compose cp tools/run_samples.py api:/tmp/run_samples.py || exit 1
# cp writes as root; the image runs as workbench (uid 10001).
docker compose exec -T --user root api \
    chown -R workbench:workbench /tmp/samples /tmp/run_samples.py || exit 1

say "re-promote"
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
echo "--- promote status ---"
grep -hoE "promote [0-9]+ footprint finding\(s\): [0-9]+" /tmp/logs/promo*.log \
  | sort | uniq -c
echo "--- footprints ---"
grep -hE "footprint:" /tmp/logs/promo*.log | sed "s/^ *//"
echo "--- outcomes ---"
grep -hE "\[FAIL\]|completed" /tmp/logs/promo*.log | sed "s/^ *//"'

say "saving the finished set"
rm -rf ./_samples_backup
docker compose cp api:/tmp/samples ./_samples_backup
echo "  $(ls ./_samples_backup | wc -l) entries"
say "done"
