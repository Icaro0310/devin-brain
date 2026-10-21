# devin-brain, Personal Windows guide

This guide covers unrestricted Windows setup. For restricted machines, see [README.corporate-windows.md](README.corporate-windows.md); for features, shared commands, limitations, and the safety model, see [README.md](README.md).

Personal Windows uses the extended runtime: local execution plus optional Devin VM/QwenPaw delegation when this artifact supports it.

## Prerequisites

- `uv` and Python 3.10 or newer; `uv` can manage Python.

## Install

Install the isolated Python CLI:

```powershell
uv tool install "devin-memory[mcp]"
```

## Devin paths

Session data normally lives under `%APPDATA%\devin\cli\`; UI state and ACP stores under `%APPDATA%\Devin\User\`.
Use `--db` (memory.db store) and `--sessions-db` for non-default locations.

## Environment notes

- Delegated runtime is optional; this guide installs local tooling only.
- Corporate Windows is a separate local-only environment.
- macOS is planned but not claimed as tested.

## Personal Windows specifics

- **Python:** `uv` manages its own Python, which also avoids the Microsoft Store `python.exe` alias stub (it opens the Store instead of running). If you install Python from python.org anyway, tick "Add python.exe to PATH".
- **Shell:** PowerShell 7 + Windows Terminal is the recommended setup; every command also works in `cmd.exe` and Windows PowerShell 5.1, none require admin.
- **Install location:** executables live under `%USERPROFILE%\.local\bin`; data under `%APPDATA%\devin`. Nothing touches `Program Files` or the registry.
- **WSL:** treat it as a Linux machine, follow [README.linux.md](README.linux.md) inside it.
- **Uninstall:** `uv tool uninstall <package>` (or `npm uninstall -g` for a Node.js tool) removes the CLI; delete `%APPDATA%\devin` to remove local data. No services or scheduled tasks are left behind.

## Recurring runs (optional)

_Weekly knowledge extraction from recent sessions (proposed entries, human-approved). `--db` pins the memory store, otherwise `extract` writes ./memory.db under whatever directory the scheduler runs from._

Quoted path arguments inside `/tr` fail differently in cmd.exe and PowerShell 5.1, so this job goes through a wrapper `.cmd` file in your own profile directory (quoting inside the file works normally, and no other user can replace it). The task inherits your user `PATH`, so the wrapper first prepends the standard tool directory (`%USERPROFILE%\.local\bin`); if the tool lives elsewhere, write its full path inside the `.cmd`. Register from PowerShell with the `ScheduledTask` cmdlets, which take the path literally and replace cleanly on rerun (`-Force`):

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\devin-tasks"   # cmd.exe: mkdir "%USERPROFILE%\devin-tasks"
```

Save this as `%USERPROFILE%\devin-tasks\devin-brain.cmd`:

```batch
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
devin-memory --db "%USERPROFILE%\devin-memory\memory.db" extract --latest --sessions-db "%APPDATA%\devin\cli\sessions.db"
```

```powershell
$action  = New-ScheduledTaskAction -Execute "$env:USERPROFILE\devin-tasks\devin-brain.cmd"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 7AM
Register-ScheduledTask -TaskName "devin-brain" -Action $action -Trigger $trigger -Force
```

_cmd.exe users: the same registration works from Task Scheduler's GUI (Action = the .cmd path)._

Runs under your account, no admin needed. Adjust the `New-ScheduledTaskTrigger` arguments (or `-AtLogOn` for daemons) to taste.


## Troubleshooting

- If a command is not found, reopen PowerShell and run `uv tool update-shell`.
- If `devin-memory-mcp` exits with `error: The MCP server needs the 'mcp' extra`
  (the editor reports the server exiting with code 1), a bare `devin-memory`
  install is on PATH — `uv tool install` does not add extras to an existing
  tool. Force-reinstall with the extra: `uv tool install --force "devin-memory[mcp]"`
  (or `pipx install --force devin-memory-mcp` for the shim).
