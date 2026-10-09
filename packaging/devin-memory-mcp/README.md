<!-- mcp-name: io.github.Icaro0310/devin-memory -->

# devin-memory-mcp

Shim package for the MCP registry so `uvx devin-memory-mcp` launches the
[devin-memory](https://github.com/Icaro0310/devin-brain) MCP server.

`devin-memory` ships two console scripts: `devin-memory` (the CLI) and
`devin-memory-mcp` (the MCP server, stdio). Since `uvx` resolves a tool
name to a package of the same name, this shim exists so the server is one
command away:

```bash
uvx devin-memory-mcp
```

For everything else (the CLI, the library, the docs), see the main package:

```bash
pip install devin-memory
```
