# Changelog

## v0.1.1

- Inventory GitHub Copilot custom agent profiles under `.github/agents/`. A `.md` file there, which includes `*.agent.md`, is kind `agent`. Any other file in that folder is kind `agent-other`. Subfolders are included. File patterns follow GitHub's custom agents documentation: https://docs.github.com/en/copilot/reference/custom-agents-configuration
- Run the rule-file checks on both kinds: `hidden-unicode`, `package-install`, `remote-script`, `permission-bypass`, and, with `--known-packages`, `unknown-package`.
- A file under `.github/agents/` whose name is already a rule or config path, such as `.github/agents/AGENTS.md`, keeps its existing kind.
- Add a benign agent profile to `examples/clean` and tests for the new inventory and checks.
- Update the README inventory table, limitations, and sample output.

## v0.1.0

- Initial public release. Inventory the rule and config paths in the README, flag the checks in the table, and accept an optional package allowlist.
