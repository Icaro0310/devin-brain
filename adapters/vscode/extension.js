"use strict";

// Thin adapter: registers devin-memory (devin-brain) as a VS Code MCP
// server through the MCP server definition provider API. All behavior
// lives in the server — the extension only describes how to launch it.
//
// Safety: DEVIN_MEMORY_MCP_PROMOTE is deliberately never set. The server
// gates its promotion overrides (release/approve) behind that opt-in env
// var so an AI client cannot self-promote past the quarantine lane — see
// src/devin_memory/mcp_server.py::_promotion_enabled. Keeping it absent
// preserves the default, non-promoting tool surface.

const vscode = require("vscode");

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
// to the first workspace folder when one is open.
function workspaceCwd() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length ? folders[0].uri.fsPath : undefined;
}

// The env the server is launched with. DEVIN_MEMORY_DB is only set when
// configured; the promotion opt-in is never present here.
function serverEnv() {
  const { dbPath } = config();
  return dbPath ? { DEVIN_MEMORY_DB: dbPath } : {};
}

function provideMcpServerDefinitions() {
  const { executable, args } = config();
  return [
    new vscode.McpStdioServerDefinition(
      "devin-memory (devin-brain)",
      executable,
      args,
      serverEnv(),
      workspaceCwd(),
    ),
  ];
}

function activate(context) {
  context.subscriptions.push(
    vscode.lm.registerMcpServerDefinitionProvider(PROVIDER_ID, {
      provideMcpServerDefinitions,
    }),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
// Test-only surface — pure internals reachable without the editor.
module.exports.__internals__ = {
  COMPATIBLE_CLI, PROVIDER_ID, serverEnv, workspaceCwd, provideMcpServerDefinitions,
};
