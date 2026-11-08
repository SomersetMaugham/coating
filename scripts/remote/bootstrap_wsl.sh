#!/usr/bin/env bash
# One-time setup inside the WSL distro (run it yourself in a WSL terminal; it asks for your sudo password).
# Safe to run again.  Installs git, the Qt runtime libraries the GUI tests need without a display, a Korean font,
# uv and Python 3.10 / 3.13.  See docs/WINDOWS_WSL_TESTING.md.
set -euo pipefail

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git curl \
  libegl1 libgl1 libopengl0 libglib2.0-0 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libfontconfig1 libdbus-1-3 \
  fonts-nanum

# linux_test.sh runs in a non-login shell and looks for uv in ~/.local/bin only, so install it there even if
# another uv is on the interactive PATH.
if [[ ! -x "$HOME/.local/bin/uv" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME/.local/bin" sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.10 3.13
echo "WSL setup done: $(uv --version), Python 3.10 and 3.13 installed"
