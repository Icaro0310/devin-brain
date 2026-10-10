"""Skill/plugin surface contract: the shipped skill exists, has valid
frontmatter, stays inside the approved tool subset, and the plugin
manifest is self-consistent."""

import json
from pathlib import Path

ADAPTERS = Path(__file__).parents[1] / "adapters"
SKILL = ADAPTERS / "skills" / "devin-brain" / "SKILL.md"
MANIFEST = ADAPTERS / ".devin-plugin" / "plugin.json"

# Memory-review operations are human-confirmed CLI work — the skill
# surface must not instruct the agent to run them as tools.
REVIEW_ONLY = ("approve", "retract", "supersede", "quarantine",
               "release", "extract")


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), "SKILL.md missing frontmatter"
    block = text.split("---", 2)[1]
    out = {}
    for line in block.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def _tool_lines(body: str) -> list[str]:
    """Lines that present an MCP tool call (backtick-wrapped names)."""
    return [line for line in body.splitlines()
            if line.lstrip().startswith("- `")]


def test_skill_exists_with_required_frontmatter():
    assert SKILL.is_file()
    fm = _frontmatter(SKILL)
    assert fm["name"] == "devin-brain"
    assert fm["description"]


def test_skill_offers_no_review_tools():
    tool_lines = "\n".join(_tool_lines(
        SKILL.read_text(encoding="utf-8"))).lower()
    for banned in REVIEW_ONLY:
        assert f"`{banned}" not in tool_lines, (
            f"skill exposes review op {banned} as a tool")


def test_skill_documents_cli_only_review():
    body = SKILL.read_text(encoding="utf-8").lower()
    assert "cli-only" in body
    # review commands must be real CLI subcommands — `devin-memory
    # review` does not exist (finding: skill advertised it)
    assert "devin-memory list --status" in body
    assert "devin-memory approve" in body


def test_plugin_manifest_self_consistent():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["name"] == "devin-brain"
    assert (ADAPTERS / "skills" / "devin-brain" / "SKILL.md").is_file()
    servers = manifest.get("mcpServers", {})
    assert "devin-brain" in servers
    args = json.dumps(servers["devin-brain"])
    assert "devin-memory-mcp" in args
