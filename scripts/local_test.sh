#!/usr/bin/env bash
# The local merge gate: the whole suite on Python 3.10 and 3.13 (conda environments coat-py310 and coat-py313, see
# AGENTS.md), both at once, each spread over the CPU cores with pytest-xdist.  About half a minute on the Mac,
# instead of about eight minutes one after the other.
#
#   scripts/local_test.sh [pytest args…]      # extra arguments go to both runs, e.g. -k tolerance
#
# Logs: ${COAT_LOCAL_OUT:-$TMPDIR/coat-local-test}/<env>.log.  Exit status 0 only if both runs pass with no skipped
# test (a missing PySide6 skips the GUI tests, and pytest would still report success).
set -uo pipefail

repo="$(git rev-parse --show-toplevel)"
out="${COAT_LOCAL_OUT:-${TMPDIR:-/tmp}/coat-local-test}"
envs=(coat-py310 coat-py313)
mkdir -p "$out"
cd "$repo" || exit 2

pids=()
for e in "${envs[@]}"; do
  QT_QPA_PLATFORM=offscreen conda run -n "$e" python -m pytest -n auto -rfEs "$@" > "$out/$e.log" 2>&1 &
  pids+=($!)
done

status=0
for i in "${!envs[@]}"; do
  e="${envs[$i]}"
  wait "${pids[$i]}"
  rc=$?
  summary="$(grep -E '[0-9]+ (passed|failed|skipped)|no tests ran|error' "$out/$e.log" | tail -1)"
  if (( rc == 0 )) && grep -qE '^SKIPPED' "$out/$e.log"; then
    rc=1
    summary="$summary (skipped tests count as a failure)"
  fi
  printf '%-11s rc=%d  %s\n' "$e" "$rc" "$summary"
  (( rc == 0 )) || status=1
done
echo "logs: $out"
exit "$status"
