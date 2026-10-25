"""Bridge learning-loop ``learned-*`` drafts into the skill-catalog registry.

``devin-learning extract`` writes ``learned-<topic>/SKILL.md`` drafts; the
``devin-skill-catalog`` package gates and promotes items through its
lifecycle (``proposed → quarantined → approved → active → retired``). This
module closes the write side of that loop: each draft becomes a
``skill:<name>`` entry in state ``proposed`` — the catalog's
registered-but-not-yet-vetted lane — inside the same JSON registry file
the catalog reads and writes:

    <config-dir>/.devin-ecosystem/skill-catalog.json
    {"version": 1, "items": {"skill:<name>": {...}}}

Writer compatibility: the file is produced exactly like
``devin_skill_catalog.registry.Registry.save()`` — same schema
(``version: 1``, ``items`` keyed by ``{kind}:{name}``), same dump
(``indent=2``, ``sort_keys=True``, trailing newline) and the same atomic
write (tempfile in the registry dir + ``os.replace``). The skill-catalog
package is never imported, so honoring its format costs no dependency.

Lifecycle authority stays with the catalog: the bridge only creates or
refreshes ``proposed`` entries. Once the catalog has moved an item to
``quarantined``/``approved``/``active``/``retired`` the entry is reported
as skipped and left untouched — re-scanning can never silently un-vet an
item that is already in the gate pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__

LEARNED_PREFIX = "learned-"
SKILL_FILENAME = "SKILL.md"

# Registry schema — mirrors devin_skill_catalog.paths/model/registry.
ECOSYSTEM_DIRNAME = ".devin-ecosystem"
REGISTRY_FILENAME = "skill-catalog.json"
REGISTRY_VERSION = 1
KIND_SKILL = "skill"
STATE_PROPOSED = "proposed"

_KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(?:\s(.*))?$")


class CatalogBridgeError(RuntimeError):
    """Malformed draft, bad layout, or unreadable/unwritable registry."""


@dataclass(frozen=True)
class ScannedSkill:
    """One ``learned-*/SKILL.md`` draft that passed frontmatter checks."""

    name: str
    path: Path
    sha256: str
    description: str


# ---------------------------------------------------------------------------
# registry location (same resolution as devin-skill-catalog)
# ---------------------------------------------------------------------------


def default_config_dir(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Devin config dir — ``DEVIN_CONFIG_DIR`` wins, then
    ``%APPDATA%\\Devin`` (Windows), ``~/Library/Application Support/Devin``
    (macOS), ``$XDG_CONFIG_HOME/Devin|devin`` with a ``~/.config/devin``
    fallback (Linux). Mirrors ``devin_skill_catalog.paths``."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = env.get("DEVIN_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    home = Path(env.get("HOME") or Path.home())
    if plat.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "Devin"
        return home / "AppData" / "Roaming" / "Devin"
    if plat == "darwin":
        return home / "Library" / "Application Support" / "Devin"
    config_home = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    candidates = [config_home / "Devin", config_home / "devin"]
    return next((c for c in candidates if c.is_dir()), candidates[-1])


def default_registry_path(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """``<config-dir>/.devin-ecosystem/skill-catalog.json``."""
    return (
        default_config_dir(environ, platform)
        / ECOSYSTEM_DIRNAME
        / REGISTRY_FILENAME
    )


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def split_frontmatter(text: str) -> tuple[dict, bool]:
    """Return ``(frontmatter, had_block)`` — the scalar subset of the
    ``---`` block (enough for ``name``/``description``). Indented lines
    and nested lists are skipped; same minimal-YAML approach as
    ``devin_skill_catalog.frontmatter``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, False
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, False
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in (" ", "\t"):
            continue  # nested content (lists, maps) — scalars only here
        m = _KEY_RE.match(line)
        if m:
            fm[m.group(1)] = _scalar(m.group(2) or "")
    return fm, True


def resolve_skills_root(skills_dir: Path) -> tuple[Path, Path]:
    """Map the CLI argument to ``(skills_root, origin_dir)``.

    Accepts a dir holding ``learned-*/`` directly (the ``--out`` layout
    ``emit_drafts`` writes, or ``.devin/skills``) or a ``.devin`` dir that
    wraps a ``skills/`` tree. ``origin_dir`` is the ``.devin`` dir when one
    can be identified — ``<x>/.devin/skills`` → ``<x>/.devin`` — else the
    scanned dir itself. The catalog stores this as ``origin`` and uses it
    to re-locate the item on disk for ``quarantine``.
    """
    p = Path(skills_dir).expanduser()
    if not p.is_dir():
        raise CatalogBridgeError(f"skills dir {p} does not exist")
    has_learned = any(
        c.is_dir() and c.name.startswith(LEARNED_PREFIX)
        for c in p.iterdir()
    )
    if not has_learned and (p / "skills").is_dir():
        return p / "skills", p
    origin = p.parent if p.name == "skills" else p
    return p, origin


def scan_learned_skills(skills_root: Path) -> list[ScannedSkill]:
    """Inventory ``learned-*/SKILL.md`` drafts, sorted by name.

    Fails loudly — naming the file — on the same frontmatter problems the
    catalog's G1 lint flags as FAIL: no ``---`` block, missing ``name``,
    ``name`` that does not match the directory, missing/empty
    ``description``.
    """
    skills_root = Path(skills_root)
    drafts: list[ScannedSkill] = []
    for child in sorted(skills_root.iterdir()):
        if not child.is_dir() or not child.name.startswith(LEARNED_PREFIX):
            continue
        skill_md = child / SKILL_FILENAME
        if not skill_md.is_file():
            raise CatalogBridgeError(
                f"{child}: learned-* dir has no {SKILL_FILENAME}"
            )
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        fm, had = split_frontmatter(text)
        if not had:
            raise CatalogBridgeError(
                f"{skill_md}: no --- frontmatter block"
            )
        name = str(fm.get("name") or "").strip()
        if not name:
            raise CatalogBridgeError(
                f"{skill_md}: frontmatter `name` is missing"
            )
        if name != child.name:
            raise CatalogBridgeError(
                f"{skill_md}: frontmatter name {name!r} does not match "
                f"directory {child.name!r}"
            )
        desc = str(fm.get("description") or "").strip()
        if not desc:
            raise CatalogBridgeError(
                f"{skill_md}: frontmatter `description` is missing or empty"
            )
        drafts.append(
            ScannedSkill(
                name=child.name,
                path=skill_md,
                sha256=sha256_file(skill_md),
                description=desc,
            )
        )
    return drafts


# ---------------------------------------------------------------------------
# registry io — byte-compatible with devin_skill_catalog.registry.Registry
# ---------------------------------------------------------------------------


def load_registry(path: Path) -> dict:
    """Read the registry file, or return a fresh v1 skeleton when absent."""
    path = Path(path)
    if not path.exists():
        return {"version": REGISTRY_VERSION, "items": {}}
    if not path.is_file():
        raise CatalogBridgeError(f"registry {path} is not a file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogBridgeError(
            f"cannot read registry {path}: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        raise CatalogBridgeError(f"registry {path} has unexpected shape")
    return data


def save_registry(path: Path, data: dict) -> None:
    """Atomic write — tempfile in the registry dir + ``os.replace``, so a
    crash never leaves a half-written registry (same as the catalog)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".skill-catalog-",
            suffix=".tmp",
        )
    except OSError as exc:
        raise CatalogBridgeError(
            f"cannot write registry {path}: {exc}"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise CatalogBridgeError(
            f"cannot write registry {path}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# the bridge
# ---------------------------------------------------------------------------


def bridge(
    skills_dir: str | Path,
    registry_path: str | Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Register every ``learned-*`` draft under ``skills_dir`` into
    ``registry_path`` as ``proposed`` entries.

    Idempotent: an already-``proposed`` entry with the same sha256/origin
    is left untouched; a re-scanned draft whose content moved gets its
    ``sha256``/``origin`` refreshed in place; entries in any other state
    are skipped (the catalog owns them). Other registry items are
    preserved verbatim. Returns a report dict.
    """
    skills_root, origin_dir = resolve_skills_root(Path(skills_dir))
    drafts = scan_learned_skills(skills_root)
    registry_path = Path(registry_path).expanduser()
    registry = load_registry(registry_path)
    items = registry["items"]
    origin = str(origin_dir.resolve())

    report: dict = {
        "tool": "devin-learning",
        "version": __version__,
        "command": "catalog-bridge",
        "skills_root": str(skills_root),
        "origin": origin,
        "registry": str(registry_path),
        "dry_run": dry_run,
        "scanned": len(drafts),
        "registered": [],
        "updated": [],
        "unchanged": [],
        "skipped": [],
    }
    for draft in drafts:
        key = f"{KIND_SKILL}:{draft.name}"
        entry = items.get(key)
        if entry is None:
            items[key] = {
                "kind": KIND_SKILL,
                "name": draft.name,
                "state": STATE_PROPOSED,
                "sha256": draft.sha256,
                "origin": origin,
                "history": [],
            }
            report["registered"].append(draft.name)
            continue
        if not isinstance(entry, dict):
            raise CatalogBridgeError(
                f"registry {registry_path}: entry {key!r} has unexpected "
                "shape"
            )
        state = entry.get("state")
        if state != STATE_PROPOSED:
            report["skipped"].append({"name": draft.name, "state": state})
            continue
        if entry.get("sha256") != draft.sha256 or entry.get("origin") != origin:
            entry["sha256"] = draft.sha256
            entry["origin"] = origin
            report["updated"].append(draft.name)
        else:
            report["unchanged"].append(draft.name)

    if not dry_run and (report["registered"] or report["updated"]):
        save_registry(registry_path, registry)
    return report
