#!/usr/bin/env bash
# Run the test suite on the Windows machine next to this Mac: Windows (Python 3.10, 3.13), then Linux in its
# WSL distro (Python 3.10, 3.13), one after the other.  Setup and security notes: docs/WINDOWS_WSL_TESTING.md.
#
#   scripts/remote_test.sh [REF]          # REF: commit, branch or tag to test (default HEAD)
#   scripts/remote_test.sh --dry-run [REF]
#
# Environment: COAT_TEST_HOST (ssh host alias, default coat-win), COAT_TEST_DISTRO (WSL distro, default: WSL's default),
# COAT_TEST_OUT (local results folder, default ./remote-test-results), COAT_TEST_SSHD_START (Automatic or Manual:
# how sshd is expected to start on Windows; win_test.ps1 warns when it differs; default Automatic).
# The commit goes over as a git bundle, so the Windows machine needs no GitHub access.  sshd there starts with
# Windows (the user's choice, 2026-11-08); with COAT_TEST_SSHD_START=Manual it is started and stopped by hand.
# Exit status: 0 only if all four environments ran their tests with no failure and no skipped test; 3 when the host
# cannot be reached, 4 when the results could not be copied back.
set -euo pipefail

HOST="${COAT_TEST_HOST:-coat-win}"
DISTRO="${COAT_TEST_DISTRO:-}"  # empty: the distro marked default in "wsl -l -v"
SSHD_START="${COAT_TEST_SSHD_START:-Automatic}"
DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY=1; shift; fi
REF="${1:-HEAD}"

repo="$(git rev-parse --show-toplevel)"
sha="$(git -C "$repo" rev-parse --verify "$REF^{commit}")"
short="${sha:0:12}"
out="${COAT_TEST_OUT:-$repo/remote-test-results}/$short"
work="$(mktemp -d)"
tmpref="refs/coat-test/$short"
trap 'rm -rf "$work"; git -C "$repo" update-ref -d "$tmpref" 2>/dev/null || true' EXIT

# Every ref is bundled (about 1 MB) and the commit is checked out by hash on the other side.  A temporary ref makes
# sure the commit is in the bundle even when no branch or tag reaches it; it is removed on exit.
bundle="$work/coat-$short.bundle"
git -C "$repo" update-ref "$tmpref" "$sha"
git -C "$repo" bundle create "$bundle" --all >/dev/null 2>&1
cp "$repo/scripts/remote/win_test.ps1" "$repo/scripts/remote/linux_test.sh" "$work/"

ssh_opts=(-o BatchMode=yes -o ConnectTimeout=5)
echo "commit $sha -> $HOST (WSL distro ${DISTRO:-default})"
if (( DRY )); then
  echo "dry run: would copy $(basename "$bundle") win_test.ps1 linux_test.sh to $HOST:coat-test/ and run win_test.ps1"
  ls -la "$work"
  exit 0
fi

if ! ssh "${ssh_opts[@]}" "$HOST" "exit 0" 2>/dev/null; then
  echo "cannot reach $HOST over ssh. Is the Windows machine on, on the same network, and sshd running?" >&2
  echo "  (admin PowerShell there: Start-Service sshd; the Mac's IP must match the firewall rule)" >&2
  exit 3
fi

# Relative remote paths: Windows OpenSSH starts in the user's home and does not expand %USERPROFILE% in scp paths.
ssh "${ssh_opts[@]}" "$HOST" "powershell -NoProfile -Command New-Item -ItemType Directory -Force coat-test" >/dev/null
scp -q "${ssh_opts[@]}" "$bundle" "$work/win_test.ps1" "$work/linux_test.sh" "$HOST:coat-test/"

set +e
ssh "${ssh_opts[@]}" "$HOST" \
  "powershell -NoProfile -ExecutionPolicy Bypass -File coat-test\\win_test.ps1 -Sha $sha -Bundle coat-$short.bundle${DISTRO:+ -Distro $DISTRO} -SshdStart $SSHD_START"
status=$?
set -e

# The summary was printed above by win_test.ps1.  Fetch the logs; a previous run of the same commit is replaced.
rm -rf "$out"
mkdir -p "$out"
# copy the folder itself (remote wildcards are not reliable against Windows OpenSSH)
if scp -q -r "${ssh_opts[@]}" "$HOST:coat-test/results-$short" "$work/" 2>/dev/null; then
  cp -R "$work/results-$short/." "$out/"
  echo "logs and summary: $out"
else
  echo "could not copy the results back from $HOST:coat-test/results-$short" >&2
  (( status == 0 )) && status=4  # a pass that left no evidence on this Mac is not reported as a pass
fi
if [[ "$SSHD_START" == "Manual" ]]; then
  echo "Remember to stop sshd on the Windows machine when you are done (admin PowerShell: Stop-Service sshd)."
fi
exit "$status"
