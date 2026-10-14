"use strict";

// Minimal vscode stub injected before requiring the extension — captures
// the registered provider, records McpStdioServerDefinition instances,
// and lets tests fire configuration/workspace-folder changes.
let settings = {};
let folders = [];
let isTrusted = true;
const registered = [];
const configListeners = [];
const folderListeners = [];

class EventEmitter {
  constructor() {
    this.listeners = [];
    this.fired = 0;
    this.event = (fn) => {
      this.listeners.push(fn);
      return { dispose() {} };
    };
  }
  fire(x) {
    this.fired += 1;
    this.listeners.forEach((l) => l(x));
  }
  dispose() {}
}

class McpStdioServerDefinition {
  constructor(label, command, args, env, version) {
    this.label = label;
    this.command = command;
    this.args = args;
    this.env = env;
    this.version = version;
    this.cwd = undefined; // writable Uri property, set after construction
  }
}

// Controllable stand-in for ./safe-executable.cjs — the real helper walks
// PATH, so tests inject resolutions and capture the opts it was given.
const safeExeCalls = [];
let safeExeResult = { file: "/resolved/devin-memory-mcp", argv: [] };
const safeExeStub = {
  resolveSafeExecutable: (exe, opts) => {
    safeExeCalls.push({ exe, opts });
    return safeExeResult;
  },
};

const vscodeStub = {
  McpStdioServerDefinition,
  EventEmitter,
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
    get isTrusted() {
      return isTrusted;
    },
    onDidChangeConfiguration: (fn) => {
      configListeners.push(fn);
      return { dispose() {} };
    },
    onDidChangeWorkspaceFolders: (fn) => {
      folderListeners.push(fn);
      return { dispose() {} };
    },
  },
};

const Module = require("module");
const origRequire = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === "vscode") return vscodeStub;
  if (id === "./safe-executable.cjs") return safeExeStub;
  return origRequire.apply(this, arguments);
};

const ext = require("../extension.js");
const { __internals__ } = ext;
const test = require("node:test");
const assert = require("node:assert");

test("activate registers provider + emitter + change listeners", () => {
  const context = { subscriptions: [] };
  ext.activate(context);
  assert.strictEqual(registered.length, 1);
  assert.strictEqual(registered[0].id, "devin-memory");
  assert.strictEqual(typeof registered[0].provider.onDidChangeMcpServerDefinitions, "function");
  assert.strictEqual(configListeners.length, 1);
  assert.strictEqual(folderListeners.length, 1);
  assert.strictEqual(context.subscriptions.length, 4);
});

test("definition launches the resolved devin-memory-mcp; cwd is the workspace Uri", () => {
  settings = {};
  isTrusted = true;
  safeExeResult = { file: "/resolved/devin-memory-mcp", argv: [] };
  safeExeCalls.length = 0;
  const uri = { fsPath: "/repo" };
  folders = [{ uri }];
  const defs = registered[0].provider.provideMcpServerDefinitions();
  assert.strictEqual(defs.length, 1);
  // The command is the absolute path the shared resolver returned — never
  // the bare configured name (Windows CreateProcess searches cwd first).
  assert.strictEqual(defs[0].command, "/resolved/devin-memory-mcp");
  assert.deepStrictEqual(defs[0].args, []);
  assert.strictEqual(defs[0].cwd, uri); // Uri object, not a string path
  assert.strictEqual(defs[0].version, undefined); // not smuggled via ctor arg
  // The resolver sees the configured name, the workspace fsPath (for the
  // inside-workspace rejection bound) and the live trust state.
  assert.strictEqual(safeExeCalls.length, 1);
  assert.strictEqual(safeExeCalls[0].exe, "devin-memory-mcp");
  assert.strictEqual(safeExeCalls[0].opts.workspaceDir, "/repo");
  assert.strictEqual(safeExeCalls[0].opts.trusted, true);
  assert.strictEqual(safeExeCalls[0].opts.npmPackage, null);
});

test("env is built from scratch — promotion gate pinned off, DB optional", () => {
  settings = {};
  assert.deepStrictEqual(__internals__.serverEnv(), { DEVIN_MEMORY_MCP_PROMOTE: "0" });
  settings = { dbPath: "/data/memory.db" };
  assert.deepStrictEqual(__internals__.serverEnv(), {
    DEVIN_MEMORY_MCP_PROMOTE: "0",
    DEVIN_MEMORY_DB: "/data/memory.db",
  });
  const defs = __internals__.provideMcpServerDefinitions();
  assert.strictEqual(defs[0].env.DEVIN_MEMORY_MCP_PROMOTE, "0");
});

test("custom executable/args flow into the definition", () => {
  settings = { executable: "uvx", args: ["devin-memory-mcp"] };
  isTrusted = true;
  safeExeResult = { file: "/resolved/uvx", argv: [] };
  safeExeCalls.length = 0;
  folders = [];
  const defs = __internals__.provideMcpServerDefinitions();
  assert.strictEqual(defs[0].command, "/resolved/uvx");
  assert.deepStrictEqual(defs[0].args, ["devin-memory-mcp"]);
  assert.strictEqual(defs[0].cwd, undefined);
  assert.strictEqual(safeExeCalls[0].exe, "uvx");
  assert.strictEqual(safeExeCalls[0].opts.workspaceDir, null);
});

test("spec.argv (e.g. a resolved .cmd shim entry) precedes configured args", () => {
  settings = { executable: "devin-memory-mcp", args: ["--flag"] };
  isTrusted = true;
  safeExeResult = { file: process.execPath, argv: ["/shim/entry.js"] };
  folders = [];
  const defs = __internals__.provideMcpServerDefinitions();
  assert.strictEqual(defs[0].command, process.execPath);
  assert.deepStrictEqual(defs[0].args, ["/shim/entry.js", "--flag"]);
});

test("an unresolvable executable throws a not-found error, not a definition", () => {
  settings = { executable: "devin-memory-mcp" };
  isTrusted = true;
  safeExeResult = null;
  folders = [];
  try {
    assert.throws(
      () => __internals__.provideMcpServerDefinitions(),
      /not found on PATH/,
    );
  } finally {
    safeExeResult = { file: "/resolved/devin-memory-mcp", argv: [] };
  }
});

test("the workspace trust state is forwarded to the resolver", () => {
  settings = {};
  safeExeResult = { file: "/resolved/devin-memory-mcp", argv: [] };
  safeExeCalls.length = 0;
  folders = [{ uri: { fsPath: "/repo" } }];
  isTrusted = false;
  try {
    __internals__.provideMcpServerDefinitions();
    assert.strictEqual(safeExeCalls[0].opts.trusted, false);
    assert.strictEqual(safeExeCalls[0].opts.workspaceDir, "/repo");
  } finally {
    isTrusted = true;
  }
});

test("devinMemory config change fires onDidChangeMcpServerDefinitions", () => {
  const emitter = registered[0].provider;
  let fired = 0;
  emitter.onDidChangeMcpServerDefinitions(() => { fired += 1; });
  configListeners.forEach((l) => l({ affectsConfiguration: () => true }));
  assert.strictEqual(fired, 1);
  // Unrelated settings changes do not re-collect.
  configListeners.forEach((l) => l({ affectsConfiguration: () => false }));
  assert.strictEqual(fired, 1);
});

test("workspace-folder change re-collects the definition", () => {
  let fired = 0;
  registered[0].provider.onDidChangeMcpServerDefinitions(() => { fired += 1; });
  folderListeners.forEach((l) => l());
  assert.strictEqual(fired, 1);
});
