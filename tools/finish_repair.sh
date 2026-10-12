#!/usr/bin/env bash
# Wait for the lufthansa/unilever repair, pull the artifacts, rebuild the
# summary, sanity-check it, and commit if it passes.
#
# The gate exists because the last two defects in this set were both visible
# in the summary table and invisible in the logs: a 20-site BASF and an
# estimate priced from a footprint research had quietly shrunk. A pass that
# commits without reading its own output would have shipped them.
set -u
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

# Which repair run to watch. Each pass writes its own log prefix so a later
# attempt cannot be mistaken for the one already read - the first version
# hardcoded "fix_" and would have waited forever on a run writing "fix2_".
PREFIX="${1:-fix}"

say() { printf '\n== %s == %s\n' "$(date +%H:%M:%S)" "$*"; }

say "waiting for both repairs"
while :; do
  n=$(docker compose exec -T api sh -c \
      "grep -lE \"completed [0-9]+, failed\" /tmp/logs/${PREFIX}_*.log 2>/dev/null | wc -l" \
      2>/dev/null | tr -d '\r ')
  [ "${n:-0}" = "2" ] && break
  d=$(docker compose exec -T api sh -c \
      "grep -hcE \"domain +[0-9]+ \" /tmp/logs/${PREFIX}_*.log 2>/dev/null | paste -sd+ -" \
      2>/dev/null | tr -d '\r ')
  printf '  %s of 34 domains\n' "${d:-?}"
  sleep 180
done

say "repair output"
docker compose exec -T api sh -c \
  "grep -hE \"repair:|footprint:|done in|\[FAIL\]|completed\" /tmp/logs/${PREFIX}_*.log" \
  | sed 's/^ *//'

say "pulling artifacts"
rm -rf ./_samples_backup
docker compose cp api:/tmp/samples ./_samples_backup || exit 1

say "rebuilding summary"
python tools/build_sample_summary.py --out ./_samples_backup --build 4.272.0 || exit 1

say "sanity gate"
# The committed set is the baseline: nothing may land worse than what is
# already in, and a company claimed as repaired must clear the floor.
python tools/check_samples.py     --out ./_samples_backup     --baseline samples/outside_in     --repaired lufthansa,unilever   || { echo "GATE FAILED - not committing"; exit 1; }

say "copying into the repo"
cp -r ./_samples_backup/. samples/outside_in/ || exit 1

say "committing"
git add -A samples/ 2>&1 | grep -v "LF will be" | head -3
git commit -q -F - <<'MSG'
Lufthansa and Unilever repaired: the two companies that caught the outage

Both finished the first run with zero researched domains - every call in
their window raised ProviderUnavailable, and the fallback disposed all
seventeen BENCHMARK_PRIOR to keep them publishable. That is the defect P-14
describes, and --repair is the remedy it needed: re-research only the
domains the net disposed, keeping anything an agent actually answered.

Nothing else in the set changed. The summary and highlights are rebuilt
across all twenty because both files are derived, not edited.

Unilever is the company this whole merge rule came from. Its pilot run
returned seventeen sites - five GB plants, four DE plants, a couple of
offices, every one a real sourced fact and together not an estate - which is
what made the case for merging research with disclosure instead of letting
either win alone. It now runs under the corrected rule, where a researched
count supersedes a disclosed one only when it is at least as large.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
git log --oneline -1
git push -q origin HEAD && echo "pushed"
say "done"
