# desk

Fast workstation setup for 42 / 1337 Linux machines.

`desk` installs native VS Code and Brave inside `goinfre`, migrates your existing profiles, creates desktop launchers and gives you normal `code` and `brave` terminal commands.

No sudo required.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/nachat-ayoub/42-desk/main/install.sh | bash
```

Then open a new terminal.

Or:

```bash
source ~/.zshrc
```

That's it.

The initial application setup can continue in the background.

---

## Usage

```bash
desk
```

Prepare the workstation and open VS Code + Brave.

### VS Code

```bash
desk c
```

or:

```bash
desk c .
```

You can also use the normal command:

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

You can also use:

```bash
brave https://github.com
```

---

## Commands

```text
desk                 ready workstation + open apps
desk c [ARGS]        open VS Code
desk b [ARGS]        open Brave
desk p               prepare/update only
desk s [c|b]         re-import profile data
desk x               close old apps
desk st              show status
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
```

---

## Automatic shell setup

`desk` adds a small managed section to `~/.zshrc`:

```bash
# >>> desk >>>
export PATH="$HOME/.local/bin:$PATH"

unalias code brave 2>/dev/null || true
unfunction code brave 2>/dev/null || true

{ command desk _shell >/dev/null 2>&1 &! } 2>/dev/null
# <<< desk <<<
```

The check runs in the background, so opening a terminal is not blocked.

If everything is already installed, it exits immediately.

A background update check is performed at most once every 12 hours.

This also prevents old `code` aliases or functions from overriding the VS Code installed by `desk`.

---

## What gets installed

The CLI is installed at:

```text
~/.local/bin/desk
```

Terminal launchers:

```text
~/.local/bin/code
~/.local/bin/brave
```

Applications are normally stored in:

```text
/goinfre/$USER/apps/vscode
/goinfre/$USER/apps/brave
```

If `/goinfre` is unavailable, `desk` falls back to:

```text
~/.local/opt
```

---

## Profiles

Existing Flatpak or Snap profiles are detected automatically.

VS Code:

```text
~/.config/Code
```

Brave:

```text
~/.config/BraveSoftware/Brave-Browser
```

Profile migration happens once.

To manually re-import:

```bash
desk s c
```

for VS Code, or:

```bash
desk s b
```

for Brave.

Both:

```bash
desk s
```

The current native profile is backed up before re-importing.

---

## Status

```bash
desk st
```

Example:

```text
desk 2.0.0

  goinfre  /goinfre/anachat
  ✓ code   ready
  ✓ brave  ready

  code   /home/anachat/.local/bin/code
  brave  /home/anachat/.local/bin/brave
  log    ~/.config/desk/last-run.log
```

---

## Repair

If shell commands or launchers are broken:

```bash
desk fix
```

Then reload Zsh:

```bash
source ~/.zshrc
```

---

## Updating

```bash
desk p
```

`desk` also performs a background update check periodically when a new shell is opened.

Running applications are never replaced while they are open.

---

## Logs

The latest automatic setup log is stored at:

```text
~/.config/desk/last-run.log
```

Installation log:

```text
~/.config/desk/install.log
```

---

## No sudo

`desk` is designed for restricted 42 / 1337 workstations.

It only writes inside locations owned by your user:

```text
$HOME
/goinfre/$USER
```

No root access is required.

---

## License

MIT
