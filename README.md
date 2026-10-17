# 42-desk

**Choose your tools. Prepare your 42 / 1337 Linux workstation without sudo.**

`42-desk` is a small no-sudo workstation bootstrapper designed for shared
42 / 1337 Linux machines.

It installs your choice of native **VS Code, Brave, and Codex CLI** inside
`goinfre`. It migrates existing editor/browser profiles, creates familiar
`code`, `brave`, and `codex` commands for the selected programs, and checks
for updates when you open a shell.

## Features

- No `sudo`
- Uses `goinfre`
- Native VS Code
- Native Brave
- Native Codex CLI (no Node.js/npm required)
- Interactive program chooser and saved selections
- Codex cache, logs, and temporary files in `goinfre`
- VS Code profile migration
- Brave profile migration
- VS Code extension support
- `code .`
- `brave <url>`
- `codex` in your current terminal
- Desktop application entries
- Visible first-run setup
- Safe per-app locking
- Background update checks after first setup
- Old Flatpak / Snap detection
- Fresh-install reset for testing
- Minimal CLI

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/nachat-ayoub/42-desk/main/install.sh | bash
```

Then open a new terminal.

Or reload your current shell:

```bash
source ~/.zshrc
```

The installer registers shell integration first. Your next terminal offers a
program chooser before downloading applications. Setup shows the selected
programs and progress such as `[1/2] VS Code`.

You can also choose immediately:

```bash
~/.local/bin/desk install

# Explicit choices work without an interactive terminal:
~/.local/bin/desk install code codex
~/.local/bin/desk install all
```

The download installer reads `main`. To try a local checkout before publishing,
run `./desk install` from the repository instead.

## First setup

On the first shell after installation, `42-desk` performs the initial setup
in the foreground. Select numbers or program names, separated by spaces or
commas. Press Enter to keep the displayed selection, or `q` to cancel.

Example:

```text
42-desk first setup
Preparing this workstation for you.

Choose your programs
Program files and the Codex cache use /goinfre/you. No sudo needed.

  1  [x] VS Code
  2  [x] Brave
  3  [ ] Codex CLI

Enter numbers or names, e.g. 1 3; all; none; q to cancel.
Enter keeps: VS Code, Brave
Install: 1 3
› Selected: VS Code, Codex CLI
› [1/2] VS Code
...
› [2/2] Codex CLI
...
✓ Workstation ready

  VS Code    code .
  Codex CLI  codex   (sign in on first use)

Change programs anytime: desk install
```

For selected VS Code or Brave installations, `42-desk` checks whether the old
application is running before copying its profile and asks you to close it first.

Example:

```text
! Before the first setup, close your old apps so their profiles can be copied safely.

  • VS Code — File > Exit
  • Brave   — Ctrl+Shift+Q

Close them, then press Enter to continue (q to cancel):
```

Once the old apps are closed, press Enter and setup continues.

While the first setup is running, any additional terminals open immediately and
remain usable; they do not wait for the setup terminal to finish.

Slow phases print what they are doing (for example `Checking VS Code`, `Checking Brave`,
and profile backup/import messages), so the setup does not sit silently during network
or migration work.

After the first successful setup, future shell sessions stay fast. Periodic
maintenance and update checks run in the background.

## Usage

```bash
desk
```

Prepare your saved selection and open the selected desktop applications.
Codex is a terminal application: run `codex` or `desk ai` when you want to use it.
Plain `desk` does not start a Codex session automatically.

### VS Code

```bash
desk c .
```

or directly:

```bash
code .
```

### Brave

```bash
desk b
```

or:

```bash
desk b https://github.com
```

or directly:

```bash
brave https://github.com
```

### Codex CLI

```bash
desk install codex       # Select only Codex and install/update it
codex                   # Start in the current terminal
codex login             # Sign in with your own account
desk ai --help          # Same managed program, without relying on PATH
desk codex exec "explain this project"
```

Codex installation needs `curl`, `python3`, and `tar`.

Codex is downloaded from OpenAI's official `@openai/codex` native platform
package on `registry.npmjs.org`. The archive's SHA-512 integrity is checked
before installation. No global npm installation or Node.js runtime is needed.
Linux x86-64 and ARM64 are supported for Codex; VS Code and Brave downloads
currently target Linux x86-64.

Codex keeps the current terminal, standard input, signals, and exit status.
Installation does not log you in or require an API key. Use Codex's normal
sign-in flow after installation. Updates are managed with `desk p`; running
Codex sessions postpone binary replacement.

### Choose programs

```bash
desk install               # Interactive chooser
desk choose                # Alias for the same chooser
desk install code codex    # Save exactly this selection and prepare it
desk install brave         # Browser only
desk install all           # VS Code, Brave, and Codex CLI
desk install none          # Disable automatic program preparation
desk p                     # Prepare/update the saved selection
desk st                    # Show selection, installation state, and versions
```

Choices are stored as plain names in `~/.config/desk/programs` (or under
`XDG_CONFIG_HOME`). Selecting a different set does not uninstall or delete
previous programs, profiles, or command wrappers. Explicit commands such as
`desk b` still work for programs outside the saved selection; these commands
do not change the selection. `desk clean` resets all desk-managed programs.

Existing installations retain VS Code and Brave until you choose differently.
A fresh noninteractive `desk p` also uses these defaults. For unattended
selection, pass names explicitly to `desk install`; the argument-free chooser
requires an interactive terminal. Invalid choices and cancellation leave the
saved selection unchanged.

### Automatic WebGL compatibility

With Brave selected, run `desk` as usual to open your desktop applications. Brave keeps your existing
accounts, history, bookmarks, extensions, and profile.

On workstations with no accessible GPU render node under `/dev/dri/renderD*`,
`desk` automatically adds `--ignore-gpu-blocklist` when starting Brave. This
allows Mesa's software renderer (such as `llvmpipe`) to attempt WebGL without
sudo. The same behavior applies to `desk b` and the managed `brave` command.
Workstations with an accessible render node keep the default graphics flags.

After installing this change, fully quit Brave once using Menu > Exit or
Ctrl+Shift+Q, then run `desk`. Chromium reads GPU flags when its browser process
starts; an already-running browser cannot pick up changed launch flags. You can
check `brave://gpu` to confirm that WebGL works with your normal profile.

This restores a software-rendering path, not AMD hardware acceleration. CPU
rendering can be slow, and bypassing Chromium's blocklist can expose rendering
bugs or instability. The sandbox stays enabled. If Linux was booted with
`nomodeset`, enabling the hardware driver still requires an administrator.
If WebGL only works with a clean test profile, check acceleration settings and
extensions in your existing profile; `desk` does not reset your data.

## Commands

```text
desk                 prepare selection + open selected desktop apps
desk c [ARGS]        open VS Code
desk b [ARGS]        open Brave
desk ai [ARGS]       run Codex CLI in this terminal
desk install [APPS]  choose, save, and prepare programs
desk p               prepare/update selected programs
desk s [c|b]         re-import profile data
desk x               close old Flatpak/Snap apps
desk st              show status
desk clean           reset to fresh-install state
desk fix             repair CLI + shell hook
```

Long command names also work:

```bash
desk code
desk brave
desk prep
desk sync
desk close
desk status
desk reset
```

## Fresh workstation behavior

You do not need to run the full setup before using an app.

For example:

```bash
desk c .
```

on a fresh or partially reset workstation will prepare only VS Code if needed:

```text
check VS Code
    ↓
missing
    ↓
install VS Code
    ↓
import profile
    ↓
configure extensions
    ↓
open project
```

It does not wait for Brave or Codex.

Likewise:

```bash
desk b
```

only prepares Brave if Brave is missing.

Running:

```bash
desk
```

or:

```bash
desk p
```

prepares the saved selection.

## Background behavior

The shell hook runs:

```bash
command desk _shell
```

On a fresh workstation, exactly one shell owns the visible first-run setup. If
you open more terminals while it is still running, their shell hooks skip the
first-run work immediately instead of waiting on its locks.

After the workstation is initialized:

- normal shell startup stays fast
- an update check for selected programs happens after the 12-hour interval
- that maintenance check runs in the background
- if everything is already ready, nothing visible happens

## Shell integration

`42-desk` adds a managed block to your shell configuration. For example, when
VS Code and Codex are selected in zsh:

```bash
# >>> desk >>>
export PATH="$HOME/.local/bin:$PATH"

unalias code 2>/dev/null || true
unfunction code 2>/dev/null || true
unalias codex 2>/dev/null || true
unfunction codex 2>/dev/null || true

command desk _shell
# <<< desk <<<
```

For Bash, the equivalent block uses:

```bash
unset -f code 2>/dev/null || true
unset -f codex 2>/dev/null || true
```

Only selected program names are cleared. This prevents old aliases/functions
from overriding the commands managed by `42-desk`. Existing open terminals may
need to reload their shell configuration before the new commands take precedence.

## Safe concurrency

Each program has a separate directory lock, alongside the core and first-run locks:

```text
~/.config/desk/locks/code.lock/
~/.config/desk/locks/brave.lock/
~/.config/desk/locks/codex.lock/
~/.config/desk/locks/core.lock/
~/.config/desk/locks/first-run.lock/
```

The `first-run` lock elects one shell to own the visible initial setup without
blocking any terminals opened afterward. The per-app locks prevent duplicate
downloads or simultaneous profile imports for the same application, while still
allowing Code and Brave setup to proceed independently.

## Storage

Applications normally live in:

```text
/goinfre/$USER/apps/vscode
/goinfre/$USER/apps/brave
/goinfre/$USER/apps/codex
```

If `/goinfre` is unavailable, `desk` falls back to:

```text
~/.local/opt
```

The CLI itself is installed at:

```text
~/.local/bin/desk
```

Wrappers:

```text
~/.local/bin/code
~/.local/bin/brave
~/.local/bin/codex
```

### Codex cache and persistent data

Managed Codex launches use:

```text
$GOINFRE/cache/codex/xdg   XDG_CACHE_HOME for Codex and its children
$GOINFRE/cache/codex/tmp   TMPDIR for temporary files
$GOINFRE/cache/codex/log   Codex log_dir default supplied by the wrapper
```

These directories are private to the user. The environment changes apply only
to Codex and its child processes. For new Codex homes, `~/.codex/tmp` is linked
to the managed temporary directory too, because Codex stores helper binaries
there independently of `TMPDIR`. An existing scratch directory is left intact
to avoid disrupting live sessions. A user-supplied `CODEX_HOME` is respected.

**Credentials, configuration, session history, and other persistent Codex data
stay in `~/.codex` (or your existing `CODEX_HOME`).** They are not treated as
cache or moved into potentially disposable campus storage. Existing logs are
not migrated; new managed launches use the log directory above. You can supply
an explicit Codex `-c log_dir=...` option to override the wrapper's default.

## Profiles

Native profiles use:

```text
~/.config/Code
```

and:

```text
~/.config/BraveSoftware/Brave-Browser
```

Existing Flatpak or Snap profiles are detected automatically.

Profile migration normally happens only once.

## Re-import profiles

VS Code:

```bash
desk s c
```

Brave:

```bash
desk s b
```

Both:

```bash
desk s
```

The current native profile is backed up before re-importing.

## Status

```bash
desk st
```

Example:

```text
42-desk 2.4.0

  Storage   /goinfre/you
  Selected  VS Code, Codex CLI

  PROGRAM      SELECTED  STATE        VERSION
  VS Code      yes       installed    ...
  Brave        no        not installed -
  Codex CLI    yes       installed    ...

  Update log   ~/.config/desk/last-run.log
  Codex cache  /goinfre/you/cache/codex

Install/change programs: desk install
Prepare/update selection: desk p
```text
desk 2.3.1

  goinfre  /goinfre/anachat
  ✓ setup  initialized
  ✓ code   ready
  ✓ brave  ready

  code   /home/anachat/.local/bin/code
  brave  /home/anachat/.local/bin/brave
  log    ~/.config/desk/last-run.log
```

## Test a fresh installation

Use:

```bash
desk clean
```

`desk clean`:

- fails immediately with a clear message if another desk setup/update is active
- backs up the current native VS Code profile
- backs up the current native Brave profile
- excludes disposable cache data from those backups so reset stays reasonably fast
- removes desk-managed VS Code
- removes desk-managed Brave
- removes desk-managed Codex CLI and its managed cache
- removes the managed `code`, `brave`, and `codex` wrappers
- removes desktop launchers
- removes first-run and update state
- keeps `desk` itself installed
- keeps the shell hook installed
- keeps the selected programs
- keeps Codex credentials, configuration, and sessions

After the clean succeeds:

```bash
exit
```

Open a new terminal.

First-run setup will start again visibly for your saved selection.

## Profile backups created by clean

`desk clean` stores native profile backups under `goinfre`, for example:

```text
/goinfre/$USER/backups/desk-clean-20261006-141500/
```

## Close old apps

```bash
desk x
```

During first setup, closing them manually is preferred so profile data is saved
before migration.

## Repair

If wrappers or shell integration become broken:

```bash
desk fix
```

Then reload your shell:

```bash
source ~/.zshrc
```

## Update applications

```bash
desk p
```

Running applications are not replaced while they are open.

## Logs

Background maintenance:

```text
~/.config/desk/last-run.log
```

State:

```text
~/.config/desk/
```

## Desktop launchers

`42-desk` creates user desktop entries for selected VS Code and Brave installations.
Codex runs in the terminal and has no desktop launcher.

The Brave entry appears as:

```text
Brave (native)
```

This distinguishes it from the old Flatpak/system Brave that may still be
installed on the workstation.

## No sudo

`42-desk` is designed specifically for restricted 42 / 1337 workstations.

It writes only to user-owned locations such as:

```text
$HOME
/goinfre/$USER
```

No root access is required.

## Repository

CLI regression checks (no desktop session, network, or application download required).
They cover program selection, installation integrity, repeat setup, cache routing,
terminal argument/input/exit handling, and Brave launch behavior:

```bash
bash -n desk install.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

```text
https://github.com/nachat-ayoub/42-desk
```

## License

MIT
