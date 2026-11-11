#!/usr/bin/env bash
# Runs inside the WSL distro (called by win_test.ps1).  Tests one commit with Python 3.10 and 3.13, one after the
# other, and writes linux-<py>.log / .xml / .exit / .versions and linux-warnings.txt into RESULTS (a /mnt/c path,
# so the Windows side can read them).  win_test.ps1 decides pass or fail.
#
#   bash linux_test.sh BUNDLE SHA RESULTS [PYTHONS]     # PYTHONS: space-separated, default "3.10 3.13"
set -uo pipefail  # no -e: every step's exit code is recorded instead

bundle="$1"; sha="$2"; res="$3"
read -r -a pythons <<< "${4:-3.10 3.13}"  # win_test.ps1 passes its own list, so both sides agree
root="$HOME/coat-test"            # on the Linux file system: running from /mnt/c is much slower
run="$root/run-${sha:0:12}"
export PATH="$HOME/.local/bin:$PATH"  # uv's default install location; this shell is not a login shell
export QT_QPA_PLATFORM=offscreen
unset PYTHONUTF8                  # keep the default encoding so encoding bugs show up
mkdir -p "$root" "$res"
warn() { echo "$*" >> "$res/linux-warnings.txt"; }

fail_all() {
  for py in "${pythons[@]}"; do echo 2 > "$res/linux-$py.exit"; done
  warn "$1"
  exit 0
}

command -v git >/dev/null || fail_all "git is not installed in WSL (see docs/WINDOWS_WSL_TESTING.md)"
command -v uv >/dev/null || fail_all "uv is not installed in WSL (see docs/WINDOWS_WSL_TESTING.md)"

# Qt runtime libraries (the CI list plus what a clean WSL image lacks) and a Korean font
# "a|b": either name counts (Ubuntu 24.04 renamed libglib2.0-0 to libglib2.0-0t64; dpkg -s fails on the old name)
missing=()
for pkg in libegl1 libgl1 libopengl0 "libglib2.0-0t64|libglib2.0-0" libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \
           libfontconfig1 libdbus-1-3 fonts-nanum; do
  found=0
  IFS='|' read -r -a names <<< "$pkg"
  for name in "${names[@]}"; do dpkg -s "$name" >/dev/null 2>&1 && found=1; done
  (( found )) || missing+=("${names[0]}")
done
(( ${#missing[@]} )) && warn "missing packages: ${missing[*]} (run scripts/remote/bootstrap_wsl.sh)"

rm -rf "$run"
{ git -c core.autocrlf=false clone --no-checkout --quiet "$bundle" "$run" &&
  git -C "$run" checkout --quiet --detach "$sha"; } > "$res/linux-checkout.log" 2>&1 \
  || fail_all "checkout of $sha failed; see linux-checkout.log"
# keep the three newest checkouts
ls -1dt "$root"/run-* 2>/dev/null | tail -n +4 | xargs -r rm -rf

versions='import sys, numpy, scipy, matplotlib, PySide6; print("VERSIONS:", sys.version.split()[0], "numpy", numpy.__version__, "scipy", scipy.__version__, "matplotlib", matplotlib.__version__, "PySide6", PySide6.__version__)'
for py in "${pythons[@]}"; do
  venv="$root/venv-$py"            # reused between runs; only the project is reinstalled
  log="$res/linux-$py.log"
  : > "$log"
  status=0
  [[ -x "$venv/bin/python" ]] || uv venv --quiet --python "$py" "$venv" >> "$log" 2>&1 || status=$?
  if (( status == 0 )); then
    # --upgrade: newest wheels each run, as CI installs them
    uv pip install --quiet --upgrade --python "$venv/bin/python" -e "$run[dev]" >> "$log" 2>&1 || status=$?
  fi
  if (( status == 0 )); then
    "$venv/bin/python" -c "$versions" > "$res/linux-$py.versions" 2>> "$log"
    (cd "$run" && "$venv/bin/python" -m pytest -n auto -q -rs -p no:cacheprovider --junitxml "$res/linux-$py.xml") \
      >> "$log" 2>&1 || status=$?
  fi
  echo "$status" > "$res/linux-$py.exit"
done
exit 0
