#!/usr/bin/env bash
set -euo pipefail

REPO="nachat-ayoub/session-setup"
BRANCH="main"

BIN_DIR="$HOME/.local/bin"
DESK="$BIN_DIR/desk"

URL="https://raw.githubusercontent.com/$REPO/$BRANCH/desk"


if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  G='\033[1;32m'
  C='\033[1;36m'
  Y='\033[1;33m'
  R='\033[0m'
else
  G=''
  C=''
  Y=''
  R=''
fi


mkdir -p "$BIN_DIR"


tmp=$(mktemp)


trap \
  'rm -f "$tmp"' \
  EXIT


printf \
  '%b›%b installing desk\n' \
  "$C" \
  "$R"


curl \
  -fsSL \
  "$URL" \
  -o "$tmp"


bash \
  -n \
  "$tmp"


install \
  -m 755 \
  "$tmp" \
  "$DESK"


"$DESK" fix


mkdir -p \
  "${XDG_CONFIG_HOME:-$HOME/.config}/desk"


nohup \
  "$DESK" \
  _shell \
  >"${XDG_CONFIG_HOME:-$HOME/.config}/desk/install.log" \
  2>&1 &


printf \
  '%b✓%b desk installed\n' \
  "$G" \
  "$R"


printf \
  '  command: %s\n' \
  "$DESK"


printf \
  '  open a new terminal, or run: %bsource ~/.zshrc%b\n' \
  "$Y" \
  "$R"


printf \
  '  setup continues safely in the background.\n'