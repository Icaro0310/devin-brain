"""Opaque machine identity + profile for provenance metadata.

Artifacts written by this tool carry ``machine_id`` + ``profile`` so output
produced on different machines (e.g. personal vs corporate) can be told
apart — without leaking hostnames, usernames or MAC addresses.

Resolution order:

- ``machine_id``: the ``DEVIN_MACHINE_ID`` env var wins; otherwise a random
  ``secrets.token_hex(8)`` persisted at
  ``<devin-config-dir>/.devin-ecosystem/machine-id`` (mode 0600, created on
  first use). Never derived from hostname, username or hardware ids.
- ``profile``: the ``DEVIN_ECOSYSTEM_PROFILE`` env var
  (``"corporate"`` | ``"personal"``), else ``devin-profile.json`` in the
  Devin config dir, else ``"corporate"`` — fail-closed.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

MACHINE_ID_ENV = "DEVIN_MACHINE_ID"
PROFILE_ENV = "DEVIN_ECOSYSTEM_PROFILE"
CONFIG_DIR_ENV = "DEVIN_CONFIG_DIR"
ECOSYSTEM_DIRNAME = ".devin-ecosystem"
MACHINE_ID_FILENAME = "machine-id"
PROFILE_FILENAME = "devin-profile.json"
PROFILES = ("corporate", "personal")
DEFAULT_PROFILE = "corporate"  # fail-closed


def devin_config_dir(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Devin Desktop's config root (``%APPDATA%/Devin``, ``~/.config/Devin``).

    Same rule devin-backup's ``default_config_dir`` uses, so every devin-*
    tool resolves the same ``.devin-ecosystem/machine-id`` on one machine.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = env.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if plat == "nt" or plat.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "Devin"
        return Path.home() / "AppData" / "Roaming" / "Devin"
    if plat == "darwin":
        return Path.home() / "Library" / "Application Support" / "devin"
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    candidates = [config_home / "Devin", config_home / "devin"]
    return next(
        (c for c in candidates if (c / "User").is_dir()), candidates[0]
    )


def machine_id(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> str:
    """Stable opaque id for this machine (16 hex chars)."""
    env = os.environ if environ is None else environ
    override = (env.get(MACHINE_ID_ENV) or "").strip()
    if override:
        return override
    path = (
        devin_config_dir(env, platform)
        / ECOSYSTEM_DIRNAME
        / MACHINE_ID_FILENAME
    )
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    value = secrets.token_hex(8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # filesystems without POSIX modes
        pass
    return value


def _profile_from_file(
    env: dict[str, str], plat: str
) -> str | None:
    path = devin_config_dir(env, plat) / PROFILE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("profile") if isinstance(data, dict) else data
    raw = str(raw or "").strip().lower()
    return raw if raw in PROFILES else None


def profile(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> str:
    """``"corporate"`` | ``"personal"`` — unknown values fail closed."""
    env = os.environ if environ is None else environ
    raw = (env.get(PROFILE_ENV) or "").strip().lower()
    if raw in PROFILES:
        return raw
    if raw:
        return DEFAULT_PROFILE  # set but unrecognized — fail closed
    plat = sys.platform if platform is None else platform
    return _profile_from_file(env, plat) or DEFAULT_PROFILE


def provenance(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> dict[str, str]:
    """``{"machine_id": ..., "profile": ...}`` for embedding in outputs."""
    return {
        "machine_id": machine_id(environ, platform),
        "profile": profile(environ, platform),
    }
