#!/usr/bin/env sh
set -eu

wait_for_url() {
  name="$1"
  url="$2"
  attempts="${3:-60}"

  i=1
  while [ "$i" -le "$attempts" ]; do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      echo "$name is ready: $url"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done

  echo "$name did not become ready: $url" >&2
  return 1
}

wait_for_url "API" "${API_HEALTH_URL:-http://localhost:8000/health}"
wait_for_url "Streamlit" "${UI_HEALTH_URL:-http://localhost:8501/_stcore/health}"

curl --fail --silent --show-error "${API_HEALTH_URL:-http://localhost:8000/health}"
echo

docker compose ps
