"use strict";

// Thin adapter: registers devin-memory (devin-brain) as a VS Code MCP
// server through the MCP server definition provider API. All behavior
// lives in the server — the extension only describes how to launch it.
//
// Safety: the env is built from scratch — never inherited — and
// DEVIN_MEMORY_MCP_PROMOTE is pinned to "0", so even an ambient
// DEVIN_MEMORY_MCP_PROMOTE=1 in the editor's environment cannot reach the
// server. The promotion overrides (release/approve) stay gated behind the
// human opt-in — src/devin_memory/mcp_server.py::_promotion_enabled.

const vscode = require("vscode");
// Shared Restricted-Mode-safe executable resolver — byte-identical copy of
// devin-powerups' adapters/shared/safe-executable.cjs (lockstep enforced by
// config-restricted-check). On Windows, CreateProcess searches cwd before
// PATH: the definition must carry the absolute path this returns — with it,
// the workspace cwd assigned below stays inert.
const { resolveSafeExecutable } = require("./safe-executable.cjs");

// Contract with the devin-memory-mcp dist (packaging/devin-memory-mcp).
// Keep in sync with the "devin-memory-mcp" range in package.json —
// test/cli-contract.test.js asserts it.
const COMPATIBLE_CLI = { min: [0, 3], maxExclusive: [0, 4] };
const PROVIDER_ID = "devin-memory";

function config() {
  const c = vscode.workspace.getConfiguration("devinMemory");
  return {
    executable: c.get("executable", "devin-memory-mcp"),
    args: c.get("args", []),
    dbPath: c.get("dbPath", ""),
  };
}

// The server's default DB is ./memory.db relative to its cwd — anchor it
// to the first workspace folder's Uri when one is open.
function workspaceUri() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length ? folders[0].uri : undefined;
}

// The env the server is launched with — built from scratch so nothing is
// inherited: DEVIN_MEMORY_DB only when configured, and the promotion gate
// explicitly off so release/approve never reach an AI client.
function serverEnv() {
  const { dbPath } = config();
  const env = { DEVIN_MEMORY_MCP_PROMOTE: "0" };
  if (dbPath) env.DEVIN_MEMORY_DB = dbPath;
  return env;
}

function provideMcpServerDefinitions() {
  const { executable, args } = config();
  const wsUri = workspaceUri();
  // Resolve BEFORE handing the command to VS Code: the definition's cwd is
  // the workspace, and on Windows a bare name there would run a binary
  // planted inside an untrusted repo. In Restricted Mode the helper also
  // rejects candidates resolving inside the workspace.
  const spec = resolveSafeExecutable(executable, {
    workspaceDir: wsUri ? wsUri.fsPath : null,
    trusted: vscode.workspace.isTrusted,
    npmPackage: null,
  });
  if (!spec) {
    throw new Error(
      "devin-memory-mcp not found on PATH. Install it " +
      "(pipx install devin-memory-mcp) or set devinMemory.executable.");
  }
  // The ctor is (label, command, args?, env?, version?) — cwd is a writable
  // Uri property on the definition, not a constructor argument. Assign it
  // so the server's default ./memory.db lands inside the workspace.
  const def = new vscode.McpStdioServerDefinition(
    "devin-memory (devin-brain)", spec.file, spec.argv.concat(args), serverEnv());
  def.cwd = wsUri;
  return [def];
}

function activate(context) {
  const emitter = new vscode.EventEmitter();
  context.subscriptions.push(
    emitter,
    vscode.lm.registerMcpServerDefinitionProvider(PROVIDER_ID, {
      provideMcpServerDefinitions,
      onDidChangeMcpServerDefinitions: emitter.event,
    }),
    // Settings and workspace folders are read at collection time — fire so
    // VS Code re-collects the definition instead of reusing a stale one.
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("devinMemory")) emitter.fire();
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => emitter.fire()),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
// Test-only surface — pure internals reachable without the editor.
module.exports.__internals__ = {
  COMPATIBLE_CLI, PROVIDER_ID, serverEnv, workspaceUri, provideMcpServerDefinitions,
};
