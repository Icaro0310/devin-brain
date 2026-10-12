"use strict";

// Minimal vscode stub injected before requiring the extension — captures
// the registered provider and records McpStdioServerDefinition instances.
let settings = {};
let folders = [];
const registered = [];

class McpStdioServerDefinition {
  constructor(label, command, args, env, cwd, version) {
    this.label = label;
    this.command = command;
    this.args = args;
    this.env = env;
    this.cwd = cwd;
    this.version = version;
  }
}

const vscodeStub = {
  McpStdioServerDefinition,
  lm: {
    registerMcpServerDefinitionProvider: (id, provider) => {
      registered.push({ id, provider });
      return { dispose() {} };
    },
  },
  workspace: {
    getConfiguration: () => ({ get: (k, d) => (k in settings ? settings[k] : d) }),
    get workspaceFolders() {
      return folders;
    },
  },
};

const Module = require("module");
const origRequire = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === "vscode") return vscodeStub;
  return origRequire.apply(this, arguments);
};

const ext = require("../extension.js");
const { __internals__ } = ext;
const test = require("node:test");
const assert = require("node:assert");

test("activate registers the provider under the devin-memory id", () => {
  const context = { subscriptions: [] };
  ext.activate(context);
  assert.strictEqual(registered.length, 1);
  assert.strictEqual(registered[0].id, "devin-memory");
  assert.strictEqual(context.subscriptions.length, 1);
});

test("definition launches devin-memory-mcp via stdio with defaults", () => {
  settings = {};
  folders = [{ uri: { fsPath: "/repo" } }];
  const defs = registered[0].provider.provideMcpServerDefinitions();
  assert.strictEqual(defs.length, 1);
  assert.strictEqual(defs[0].command, "devin-memory-mcp");
  assert.deepStrictEqual(defs[0].args, []);
  assert.strictEqual(defs[0].cwd, "/repo");
});

test("env carries DEVIN_MEMORY_DB only when configured — never PROMOTE", () => {
  settings = {};
  assert.deepStrictEqual(__internals__.serverEnv(), {});
  settings = { dbPath: "/data/memory.db" };
  assert.deepStrictEqual(__internals__.serverEnv(), { DEVIN_MEMORY_DB: "/data/memory.db" });
  const defs = __internals__.provideMcpServerDefinitions();
  assert.strictEqual(defs[0].env.DEVIN_MEMORY_DB, "/data/memory.db");
  assert.ok(!("DEVIN_MEMORY_MCP_PROMOTE" in defs[0].env));
});

test("custom executable/args flow into the definition", () => {
  settings = { executable: "uvx", args: ["devin-memory-mcp"] };
  folders = [];
  const defs = __internals__.provideMcpServerDefinitions();
  assert.strictEqual(defs[0].command, "uvx");
  assert.deepStrictEqual(defs[0].args, ["devin-memory-mcp"]);
  assert.strictEqual(defs[0].cwd, undefined);
});
