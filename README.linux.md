# devin-memory — Linux guide

This guide covers Linux setup only. See [README.md](README.md) for features, shared commands, limitations, and the safety model.

## Prerequisites

- `uv` and Python 3.10 or newer; `uv` can manage Python.

## Install

Install the isolated Python CLI:

```bash
uv tool install 'devin-memory[mcp]==0.3.0'
```

## Devin paths

Session data normally lives under `${XDG_DATA_HOME:-$HOME/.local/share}/devin/cli/`; UI state and ACP stores under `${XDG_CONFIG_HOME:-$HOME/.config}/Devin/User/`.
Use the tool's documented `--data-dir` or `--config-dir` flags for non-default locations.

## Platform notes

- Windows and Linux are the initial tested platforms.
- macOS is planned but not claimed as tested.

## Troubleshooting

- If a command is not found, ensure the `uv` tools directory is on `PATH` and run `uv tool update-shell`.
