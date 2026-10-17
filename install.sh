#!/usr/bin/env bash
set -euo pipefail

REPO="nachat-ayoub/42-desk"
BRANCH="main"

BIN_DIR="$HOME/.local/bin"
DESK="$BIN_DIR/desk"

CONF_DIR=${XDG_CONFIG_HOME:-$HOME/.config}

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


mkdir -p \
  "$BIN_DIR" \
  "$CONF_DIR/desk"


if [ -n "${GOINFRE:-}" ]; then
  storage=$GOINFRE
elif [ -d /goinfre ]; then
  storage="/goinfre/${USER:-$(id -un)}"
elif [ -d "$HOME/goinfre" ]; then
  storage=$(readlink -f "$HOME/goinfre")
else
  storage="$HOME/.local/opt"
fi
mkdir -p "$storage/cache/desk/tmp"
tmp=$(mktemp "$storage/cache/desk/tmp/installer.XXXXXX")

trap \
  'rm -f "$tmp"' \
  EXIT


printf \
  '%b›%b installing 42-desk\n' \
  "$C" \
  "$R"


local_desk=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  local_desk="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/desk"
fi
if [ -n "$local_desk" ] && [ -f "$local_desk" ]; then
  cp -- "$local_desk" "$tmp"
else
  curl -fsSL "$URL" -o "$tmp"
fi


# Never install invalid shell code.
bash -n "$tmp"


install \
  -m 755 \
  "$tmp" \
  "$DESK"


# Register shell integration. App wrappers follow the user's program choice.
"$DESK" fix


printf '\n'

printf \
  '%b✓%b 42-desk installed\n' \
  "$G" \
  "$R"


printf '\n'
printf 'Choose VS Code, Brave, Codex CLI, Claude Code, Android 11 Google Play, or any combination.\n'
printf 'New installations show a checkbox picker in your next terminal.\n\n'
printf 'Open the picker now: ~/.local/bin/desk install\n'
printf 'Without prompts: ~/.local/bin/desk install codex claude\n'
printf 'Install all five tools: ~/.local/bin/desk install all\n'
printf 'After installation, choose what to open: ~/.local/bin/desk\n'
printf 'Update installed programs: ~/.local/bin/desk update\n\n'


case "$(basename "${SHELL:-}")" in

  zsh)

    printf \
      'Open a new terminal, or run:\n\n  %bsource ~/.zshrc%b\n' \
      "$Y" \
      "$R"
    ;;


  bash)

    printf \
      'Open a new terminal, or run:\n\n  %bsource ~/.bashrc%b\n' \
      "$Y" \
      "$R"
    ;;


  *)

    printf \
      'Open a new terminal to start the first setup.\n'
    ;;

esac


printf '\n'
