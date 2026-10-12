"use strict";

// Contract guard: the devin-memory-mcp pin in package.json, the
// COMPATIBLE_CLI bounds in extension.js, and the real packaged version
// must agree — and the promotion opt-in must never be set by the adapter.

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ADAPTER = path.join(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(ADAPTER, "package.json"), "utf8"));
const src = fs.readFileSync(path.join(ADAPTER, "extension.js"), "utf8");

// packaging/devin-memory-mcp/pyproject.toml is the source of truth for the
// version of the published MCP dist the adapter launches.
const pyproject = fs.readFileSync(
  path.join(ADAPTER, "..", "..", "packaging", "devin-memory-mcp", "pyproject.toml"),
  "utf8",
);
const realVersion = /^version\s*=\s*"([^"]+)"/m.exec(pyproject)[1];

function parseRange(range) {
  const m = /^>=(\d+)\.(\d+)\.(\d+),<(\d+)\.(\d+)\.(\d+)$/.exec(range);
  assert.ok(m, `pin "${range}" must be a ">=x.y.z,<x.y.z" range`);
  return {
    min: [Number(m[1]), Number(m[2])],
    maxExclusive: [Number(m[4]), Number(m[5])],
  };
}

test("package.json pins the devin-memory-mcp range", () => {
  assert.ok(pkg["devin-memory-mcp"], "missing devin-memory-mcp field");
  parseRange(pkg["devin-memory-mcp"]);
});

test("COMPATIBLE_CLI matches the package.json pin", () => {
  const { min, maxExclusive } = parseRange(pkg["devin-memory-mcp"]);
  const m = /COMPATIBLE_CLI\s*=\s*\{\s*min:\s*\[(\d+),\s*(\d+)\],\s*maxExclusive:\s*\[(\d+),\s*(\d+)\]/.exec(src);
  assert.ok(m, "COMPATIBLE_CLI bounds not found in extension.js");
  assert.deepStrictEqual([Number(m[1]), Number(m[2])], min);
  assert.deepStrictEqual([Number(m[3]), Number(m[4])], maxExclusive);
});

test("the real devin-memory-mcp version falls inside the pinned range", () => {
  const { min, maxExclusive } = parseRange(pkg["devin-memory-mcp"]);
  const [maj, minr] = realVersion.split(".").map(Number);
  const geMin = maj > min[0] || (maj === min[0] && minr >= min[1]);
  const ltMax = maj < maxExclusive[0] || (maj === maxExclusive[0] && minr < maxExclusive[1]);
  assert.ok(geMin && ltMax, `devin-memory-mcp ${realVersion} outside ${pkg["devin-memory-mcp"]}`);
});

test("adapter contributes exactly one MCP provider with a stable id", () => {
  const providers = pkg.contributes.mcpServerDefinitionProviders;
  assert.deepStrictEqual(providers.map((p) => p.id), ["devin-memory"]);
});

test("promotion opt-in is never assigned in extension code", () => {
  // Comments may mention the env var; an actual env assignment cannot.
  assert.ok(
    !/DEVIN_MEMORY_MCP_PROMOTE\s*[:=]/.test(src),
    "DEVIN_MEMORY_MCP_PROMOTE must never be set by the adapter",
  );
});
