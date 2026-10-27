# Changelog

## v0.1.2

- Inventory Claude Code `.mcp.json` (project-scoped MCP config) as kind `config`, at the repository root and in subfolders, and run the existing `mcp-command`, `hooks`, and line checks on it. Servers are read from the `mcpServers` object. Format and locations follow https://code.claude.com/docs/en/mcp#project-scope
- In `.claude/settings*.json`, report a top-level `enableAllProjectMcpServers: true` and a non-empty `enabledMcpjsonServers` list as `permission-bypass` (FAIL). Both approve `.mcp.json` servers without the per-server prompt: https://code.claude.com/docs/en/settings-reference#enableallprojectmcpservers. `disabledMcpjsonServers` only rejects servers and is not reported.
- In `.github/agents/`, `.cursor/rules/`, and `.clinerules*` folders, a known binary file type whose content is not valid UTF-8 or contains a NUL byte is listed, then reported under a new `skipped` list with a note, instead of giving exit 2. Known binary types: extensions `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.ico`, `.bmp`, `.svgz`, `.pdf` (case-insensitive) and files named `.DS_Store`. Every other non-UTF-8 file there still gives exit 2. Every other file there with a NUL byte is scanned and reported as an error (exit 2). Named rule and config files elsewhere are unchanged.
- Escape terminal control characters in the error messages that echo a path or flag value on stderr.
- README and exit-code table: every dangling symlink, including a symlink loop, gives exit 2.
- Ship `CHANGELOG.md` in the sdist (`MANIFEST.in`).
- Tests: new cases for the above, a `.mcp.json` in `examples/clean`, and a 15 s bound on the large MCP file timing test.

## v0.1.1

- Inventory GitHub Copilot custom agent profiles under `.github/agents/`. A `.md` file there, which includes `*.agent.md`, is kind `agent`. Any other file in that folder is kind `agent-other`. Subfolders are included. File patterns follow GitHub's custom agents documentation: https://docs.github.com/en/copilot/reference/custom-agents-configuration
- Run the rule-file checks on both kinds: `hidden-unicode`, `package-install`, `remote-script`, `permission-bypass`, and, with `--known-packages`, `unknown-package`.
- A file under `.github/agents/` whose name is already a rule or config path, such as `.github/agents/AGENTS.md`, keeps its existing kind.
- Add a benign agent profile to `examples/clean` and tests for the new inventory and checks.
- Update the README inventory table, limitations, and sample output.

## v0.1.0

- Initial public release. Inventory the rule and config paths in the README, flag the checks in the table, and accept an optional package allowlist.
