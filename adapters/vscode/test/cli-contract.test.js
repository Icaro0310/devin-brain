"use strict";

// Contract guard: the devin-memory-mcp pin in package.json, the
// COMPATIBLE_CLI bounds in extension.js, and the real packaged version
// must agree — and the promotion opt-in must be pinned off by the adapter.

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
    min: [Number(m[1]), Number(m[2]), Number(m[3])],
    maxExclusive: [Number(m[4]), Number(m[5]), Number(m[6])],
  };
}

const cmp = (a, b) =>
  a[0] - b[0] || a[1] - b[1] || a[2] - b[2];

test("package.json pins the devin-memory-mcp range", () => {
  assert.ok(pkg["devin-memory-mcp"], "missing devin-memory-mcp field");
  parseRange(pkg["devin-memory-mcp"]);
});

test("COMPATIBLE_CLI matches the package.json pin", () => {
  const { min, maxExclusive } = parseRange(pkg["devin-memory-mcp"]);
  const m = /COMPATIBLE_CLI\s*=\s*\{\s*min:\s*\[(\d+),\s*(\d+)\],\s*maxExclusive:\s*\[(\d+),\s*(\d+)\]/.exec(src);
  assert.ok(m, "COMPATIBLE_CLI bounds not found in extension.js");
  assert.deepStrictEqual([Number(m[1]), Number(m[2])], min.slice(0, 2));
  assert.deepStrictEqual([Number(m[3]), Number(m[4])], maxExclusive.slice(0, 2));
});

test("the real devin-memory-mcp version falls inside the pinned range", () => {
  const { min, maxExclusive } = parseRange(pkg["devin-memory-mcp"]);
  const v = realVersion.split(".").map(Number).slice(0, 3);
  assert.ok(
    cmp(v, min) >= 0 && cmp(v, maxExclusive) < 0,
    `devin-memory-mcp ${realVersion} outside ${pkg["devin-memory-mcp"]}`,
  );
});

test("adapter contributes exactly one MCP provider with a stable id", () => {
  const providers = pkg.contributes.mcpServerDefinitionProviders;
  assert.deepStrictEqual(providers.map((p) => p.id), ["devin-memory"]);
});

test("promotion opt-in is only ever pinned to \"0\"", () => {
  // Strip full-line comments (they may mention the flag); every remaining
  // occurrence must be part of the pinned-off assignment.
  const code = src.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
  const mentions = code.match(/DEVIN_MEMORY_MCP_PROMOTE/g) || [];
  const pinned = code.match(/DEVIN_MEMORY_MCP_PROMOTE:\s*"0"/g) || [];
  assert.ok(pinned.length >= 1, "DEVIN_MEMORY_MCP_PROMOTE must be pinned off in env");
  assert.strictEqual(
    mentions.length, pinned.length,
    "every code-level mention of the promotion flag must pin it to \"0\"",
  );
});
