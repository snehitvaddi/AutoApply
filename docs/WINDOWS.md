# ApplyLoop on Windows

ApplyLoop runs natively on Windows 10 (1809+) and Windows 11. The brain,
worker, scout, and ATS appliers are all the same code as the Mac build —
the only Windows-specific pieces are the installer (`install.ps1`), the
PTY backend (`pty_windows.py` via pywinpty/ConPTY), and the `.exe` bundle
produced by PyInstaller.

## Install

Open **PowerShell** (Win+X → "Terminal" or "PowerShell"), then run:

```powershell
irm https://raw.githubusercontent.com/snehitvaddi/ApplyLoop/main/install.ps1 | iex
```

You'll be prompted for your activation code (format `AL-XXXX-XXXX`),
then the installer:

1. Installs Python 3.12, Node.js 20, Git via `winget`
2. Installs `openclaw` and `@anthropic-ai/claude-code` via `npm`
3. Clones the repo into `%USERPROFILE%\.applyloop`
4. Creates a Python venv and installs deps
5. Builds the static UI bundle
6. Fetches your profile + integrations from the cloud
7. Writes `.env`, `profile.json`, `AGENTS.md`, `.claude/settings.json`
8. Runs `python build.py --win` to produce `ApplyLoop.exe`
9. Installs a CLI shim at `%LOCALAPPDATA%\Programs\ApplyLoop\applyloop.cmd`
10. Registers a Task Scheduler entry for daily 3 AM auto-updates

Total time: 4–8 minutes on a fresh machine.

## Where files live

| Purpose | Path |
|---|---|
| Source code | `%USERPROFILE%\.applyloop\` |
| Python venv | `%USERPROFILE%\.applyloop\venv\Scripts\python.exe` |
| Runtime config | `%USERPROFILE%\.applyloop\.env` |
| Profile | `%USERPROFILE%\.applyloop\profile.json` |
| Local SQLite (jobs) | `%USERPROFILE%\.autoapply\workspace\applications.db` |
| Resumes | `%USERPROFILE%\.autoapply\workspace\resumes\` |
| Screenshots | `%USERPROFILE%\.autoapply\workspace\screenshots\` |
| Built `.exe` | `%USERPROFILE%\.applyloop\packages\desktop\dist\windows\ApplyLoop\ApplyLoop.exe` |
| CLI shim | `%LOCALAPPDATA%\Programs\ApplyLoop\applyloop.cmd` |
| OpenClaw config | `%USERPROFILE%\.openclaw\openclaw.json` |
| Claude Code auth | `%USERPROFILE%\.claude\` |

The local SQLite at `applications.db` is the **single source of truth**
for all job data — the dashboard reads it directly. The Supabase cloud
DB only stores aggregate status counts. If the dashboard shows
unexpected numbers, query the local file first:

```powershell
sqlite3 "$env:USERPROFILE\.autoapply\workspace\applications.db" "SELECT status, COUNT(*) FROM applications GROUP BY status;"
```

## Update

```powershell
applyloop update
```

This runs `git fetch` + `git reset --hard origin/main` in the install
directory and re-runs `pip install -r requirements.txt` if anything
changed. The Task Scheduler entry runs this daily at 3 AM.

## Uninstall

```powershell
applyloop uninstall
```

Or manually:

```powershell
schtasks /Delete /TN ApplyLoopUpdate /F
Remove-Item -Recurse -Force "$env:USERPROFILE\.applyloop"
Remove-Item -Recurse -Force "$env:USERPROFILE\.autoapply"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Programs\ApplyLoop"
npm uninstall -g openclaw
npm uninstall -g @anthropic-ai/claude-code
```

The `%USERPROFILE%\.openclaw\` and `%USERPROFILE%\.claude\` directories
hold per-user config you may want to keep.

## Troubleshooting

### "Windows protected your PC" SmartScreen warning on first launch

The `.exe` is unsigned (code signing is a $300/yr separate workstream).
Click **More info** → **Run anyway**. Once you've approved it once,
SmartScreen remembers.

### `applyloop` command not found in a new PowerShell window

The installer adds `%LOCALAPPDATA%\Programs\ApplyLoop` to your user PATH
via `[System.Environment]::SetEnvironmentVariable`. Existing windows
don't pick this up — open a brand-new PowerShell or restart your
terminal.

### `winget` not found

Update **App Installer** from the Microsoft Store, or use Windows 10
1809+ / Windows 11. Older Windows won't have winget pre-installed.

### `openclaw gateway start` fails

Run it manually to see the error:

```powershell
openclaw gateway start
```

Common cause: another openclaw process is already running. Check with:

```powershell
tasklist | findstr openclaw
```

Kill it: `taskkill /F /IM openclaw.exe`

### Chrome doesn't open during apply

Make sure Chrome is installed. Verify with:

```powershell
chrome --version
```

If that fails, install Chrome from google.com/chrome and rerun. OpenClaw
auto-detects the system Chrome via the standard install registry keys —
manual `browser.path` overrides are not currently wired into the
generated `openclaw.json`.

### App fails to start with "ConPTY" or "pywinpty" error

You're on Windows < 10 1809. ConPTY (the Pseudo Console API) shipped in
1809 and is required for the Claude Code terminal pane. Update Windows.

### Python or Node version conflicts

Don't install Python or Node from python.org / nodejs.org alongside the
winget version — keeping just one prevents PATH confusion. The
installer uses winget IDs `Python.Python.3.12` and `OpenJS.NodeJS`. If
you need to remove a stray install, use Add/Remove Programs.

## Platform-specific notes

These are the only differences between the Windows and Mac builds:

| Concept | Mac | Windows |
|---|---|---|
| Installer | `install.sh` (bash) | `install.ps1` (PowerShell) |
| Package manager | Homebrew | winget |
| Auto-update | launchd (`~/Library/LaunchAgents`) | Task Scheduler |
| Sleep prevention during apply | `jiggler.sh` + `caffeinate` | `keep_awake.py` (Win32 SetThreadExecutionState) |
| PTY backend | Unix `pty.fork()` | pywinpty (ConPTY) |
| App bundle | `.app` directory | PyInstaller `--onedir` |
| Distribution | `.dmg` | `.zip` (or PyInstaller `.exe`) |
| Browser focus | osascript / AppleScript | PowerShell + `SetForegroundWindow` |
| File ACLs | `chmod 600` | `icacls /inheritance:r /grant:r` |
| Temp dir | `/tmp/openclaw/uploads` | `%TEMP%\openclaw\uploads` |

The 95% that matters — scout, applier, brain, MCP server, db, profile,
dashboard — is identical on both platforms.

## Remote-control gotchas (AnyDesk, RDP, Chrome Remote Desktop)

If you're installing or operating ApplyLoop on a Windows machine via a
remote-desktop tool from a Mac, and your **keystrokes seem to type the
wrong characters** (e.g. `@` becomes `"`, paths shift symbols), open
unintended Windows shortcuts, or the keyboard layout silently switches
mid-session:

This is almost always the remote-desktop tool's keyboard transmission
mode, not ApplyLoop or PowerShell. Nothing in `install.ps1`, the
desktop app, or the worker touches the system keyboard layout.

- **AnyDesk** — toolbar at the top of the remote session → **Input →
  Keyboard transmission → Direct**. The default is "Translate," which
  sends your Mac's layout to Windows and gets confused by mismatched
  symbol positions.
- **Microsoft RDP** — usually fine; the client maps keys to the
  Windows host layout by default. If symbols still misbehave, press
  `Win+Space` once on the remote host to confirm Windows is on `ENG / US`.
- **Chrome Remote Desktop** — no per-session setting; both ends' system
  layouts must agree. Change the Windows host's input language via
  Settings → Time & language → Language to match the Mac.

Specific keystroke combos (`Win+Space`, `Alt+Shift`, `Ctrl+Shift`)
cycle Windows' input languages. If you accidentally hit one mid-install
and the keyboard "feels wrong," that's what happened — press the same
combo again or use `Win+Space` to pick the layout explicitly.
