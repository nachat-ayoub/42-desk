# 42-desk

**Get any 42 / 1337 Linux workstation ready to work in seconds.**

`42-desk` is a small no-sudo workstation bootstrapper designed for shared
42 / 1337 Linux machines.

It installs native VS Code and Brave inside `goinfre`, migrates your existing
profiles, creates normal `code` and `brave` commands, and automatically checks
your workstation when you open a shell.

## Features

- No `sudo`
- Uses `goinfre`
- Native VS Code
- Native Brave
- VS Code profile migration
- Brave profile migration
- VS Code extension support
- `code .`
- `brave <url>`
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

The installer itself is fast. The actual first workstation setup starts visibly
inside your first shell session so you can see downloads, profile migration,
warnings, and progress.

## First setup

On the first shell after installation, `42-desk` performs the initial setup
in the foreground.

Example:

```text
42-desk first setup
Preparing this workstation for you.

› Downloading VS Code ...
✓ VS Code installed
› Importing VS Code profile
✓ VS Code profile ready

› Downloading Brave ...
✓ Brave installed
› Importing Brave profile
✓ Brave profile ready

✓ Workstation ready

  VS Code: code .
  Brave:   brave
```

If your old VS Code or Brave is still running, `42-desk` stops before copying
their profiles and asks you to close them first.

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

Prepare everything and open VS Code + Brave.

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

## Commands

```text
desk                 prepare + open Code and Brave
desk c [ARGS]        open VS Code
desk b [ARGS]        open Brave
desk p               prepare/update everything
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

It does not wait for Brave.

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

prepares both applications.

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
- a full update check happens at most once every 12 hours
- that maintenance check runs in the background
- if everything is already ready, nothing visible happens

## Shell integration

`42-desk` adds a managed block to your shell configuration:

```bash
# >>> desk >>>
export PATH="$HOME/.local/bin:$PATH"

unalias code brave 2>/dev/null || true
unfunction code brave 2>/dev/null || true

command desk _shell
# <<< desk <<<
```

For Bash, the equivalent block uses:

```bash
unset -f code brave 2>/dev/null || true
```

This also prevents old `code` or `brave` aliases/functions from overriding the
commands managed by `42-desk`.

## Safe concurrency

VS Code and Brave use separate lock files:

```text
~/.config/desk/locks/code
~/.config/desk/locks/brave
~/.config/desk/locks/core
~/.config/desk/locks/first-run
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
```

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
desk 2.3.0

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
- removes the `code` and `brave` wrappers
- removes desktop launchers
- removes first-run and update state
- keeps `desk` itself installed
- keeps the shell hook installed

After the clean succeeds:

```bash
exit
```

Open a new terminal.

The complete first-run setup will start again visibly.

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

`42-desk` creates user desktop entries for the native applications.

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

```text
https://github.com/nachat-ayoub/42-desk
```

## License

MIT
