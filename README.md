# agent-repo-preflight: read-only pre-open check for AGENTS.md, rule files, MCP and hook configs
Flags hidden Unicode, package-install and curl-pipe-shell lines, auto-approve settings, MCP command entries and hooks before a coding agent loads them.

Read a freshly cloned repository and inventory the agent rule files and repo-declared MCP or hook config before you open that repository in a coding agent. One read-only Python script. The standard library is enough.

Use it on repositories you own or are explicitly allowed to review.

mcp-tool-pin-check pins live MCP tool descriptions. agent-k8s-harden-check reads Kubernetes manifests. This checker reads rule files and repository config that a coding agent may load on open.

## Why it matters

Coding agents load repository instruction files and repository-declared tool config when a project is opened. Two public sources are the reason this checker exists:

- The [PackHallu](https://arxiv.org/html/2610.09264) paper studies `AGENTS.md`, `CLAUDE.md`, and `.cursorrules` as files that can change which package a coding agent selects. This repository does not include prompts from that paper. The checker flags install instructions and, when you pass an allowlist, package names that are not on it.
- [The Injection's week 42 roundup](https://theinjection.dev/week/2026-w42/) (12–18 October 2026) describes coding agents loading MCP config and hooks that a repository declares. This checker inventories those files and flags command entries and hook definitions.

Those are links to the public pages. This repository does not restate procedures from them. It reads the files you already have and reports the patterns below.

## Quick start

Requires Python 3.9 or newer.

```bash
git clone https://github.com/digitalfortressaudit/agent-repo-preflight.git
cd agent-repo-preflight
python3 agent_repo_preflight.py /path/to/cloned/repo
```

From that directory, the same flags are available on the script:

```bash
python3 agent_repo_preflight.py examples/clean
python3 agent_repo_preflight.py examples/clean --json
python3 agent_repo_preflight.py . --known-packages examples/known-packages.txt
```

`pip install .` from the clone installs the `agent-repo-preflight` command. `--help` prints that name:

```bash
agent-repo-preflight examples/clean
agent-repo-preflight examples/clean --json
agent-repo-preflight . --known-packages examples/known-packages.txt
```

The positional argument is a local directory. The checker walks it, inventories the paths listed under [Files it inventories](#files-it-inventories), and prints a table. `--json` prints the same result as JSON. `--version` prints `agent-repo-preflight 0.1.1`. `--known-packages FILE` is an allowlist, one package name per line. `#` starts a comment. With that flag, package tokens on install or remove lines in rule files and `.github/agents/` files are compared with the list.

`examples/clean` is a benign fixture. That run exits `0`. Scanning this repository's own root also exits `0`: the only inventoried files are that fixture.

## Sample output

`examples/clean`:

```text
Agent repo preflight

root: examples/clean
files inventoried: 3

inventoried:
  .cursor/rules/style.md  (rule)
  .github/agents/docs-reviewer.agent.md  (agent)
  AGENTS.md  (rule)

No findings.

summary: files=3 warn=0 fail=0 errors=0
This is a reading of local files. It is not permission to open the repository in a coding agent.
```

A review directory is not shipped in this repository, so a scan of this tree stays clean. The unit tests build this shape in a temporary directory and assert the inventoried files, the four rows, and the summary. `AGENTS.md` has U+200B inserted on line 3 and `pip install example-widget` on line 4, `.claude/settings.json` has `"autoApprove": true`, and `.cursor/mcp.json` has a server `local-echo` whose `command` is `echo` and whose `args` are `["ok"]`. That run exits `1`. The sample below uses the root name `review-fixture`:

```text
Agent repo preflight

root: review-fixture
files inventoried: 3

inventoried:
  .claude/settings.json  (config)
  .cursor/mcp.json  (config)
  AGENTS.md  (rule)

severity  check              location                 detail
--------  -----------------  -----------------------  -------------------------------------------------
FAIL      permission-bypass  .claude/settings.json:2  permission bypass setting: autoApprove
FAIL      mcp-command        .cursor/mcp.json:4       MCP server "local-echo" declares command and args
FAIL      hidden-unicode     AGENTS.md:3              hidden character: U+200B ZERO WIDTH SPACE
WARN      package-install    AGENTS.md:4              install or replace instruction: pip install

summary: files=3 warn=1 fail=3 errors=0
This is a reading of local files. It is not permission to open the repository in a coding agent.
```

The hidden character is reported by code point. The output does not echo the character.

## Checks

| Check | Pass | Warn | Fail |
| --- | --- | --- | --- |
| `hidden-unicode` | No zero-width character, bidi control, or Unicode tag character | | U+200B, U+200C, U+200D, U+2060, U+FEFF after the first character, U+180E, U+034F, U+200E, U+200F, U+061C, U+202A–U+202E, U+2066–U+2069, U+E0001, or U+E0020–U+E007F. A leading U+FEFF byte-order mark is ignored. |
| `package-install` | No install, upgrade, remove, or replace instruction | `pip`, `pipx`, `python -m pip`, `npm`, `pnpm`, `yarn`, `bun`, `uv`, `cargo`, `go install`, `poetry`, `pdm`, `pipenv`, `conda`, `mamba`, `gem`, or `brew` install/add/remove line, or a line that says to replace a package, dependency, module, or library | |
| `remote-script` | No fetch-and-run instruction | | `curl`, `wget`, `fetch`, or `irm` piped to a shell or interpreter, or a `$(...)` / `<()` substitution that starts with one of those commands |
| `permission-bypass` | No enabled auto-approve, yolo, skip-permissions, bypass-permissions, or `dangerously-*` setting | | The phrase is present and is not assigned `false`, `off`, `no`, `disabled`, or `never` |
| `mcp-command` | No MCP server entry with a non-empty `command` or `args` | | A server under `mcpServers`, or under `servers` in an `mcp.json` or an `mcp` object, declares `command` or `args` |
| `hooks` | No hook definition | | A JSON `hooks` value contains a `type`, `command`, or `matcher` object, or a non-empty string |
| `unknown-package` | The flag was omitted, or every package token on a rule-file or `.github/agents/` install line is on the allowlist | A package token in a rule file or a `.github/agents/` file is not on the `--known-packages` list | |

A phrase immediately after `do not`, `don't`, `never`, `without`, `avoid`, `no`, `not`, `cannot`, or `disable` is not flagged for `package-install`, `remote-script`, or `permission-bypass`. Hidden characters, MCP command entries, and hook definitions are still flagged. An allowlisted package still produces `package-install` when the install line is present. `unknown-package` is the extra row for a name that is absent from the list. Config files are not mined for package names.

WARN and FAIL are both findings. Either one makes the process exit `1`.

## Files it inventories

| Path | Kind |
| --- | --- |
| `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.cursor/rules/**`, `.github/copilot-instructions.md`, `.clinerules*`, `.windsurfrules`, `CONVENTIONS.md` | rule |
| `.cursor/mcp.json`, `.vscode/mcp.json`, `.vscode/settings.json`, `.claude/settings*.json`, `.zcode/config.json` | config |
| `.github/agents/**/*.md`, which includes `*.agent.md`: GitHub Copilot custom agent profiles ([GitHub Docs](https://docs.github.com/en/copilot/reference/custom-agents-configuration)) | agent |
| Any other file under `.github/agents/` | agent-other |

`agent` and `agent-other` files get the same checks as `rule` files: `hidden-unicode`, `package-install`, `remote-script`, `permission-bypass`, and, with `--known-packages`, `unknown-package`. A file under `.github/agents/` whose name is already in the rule or config rows, such as `.github/agents/AGENTS.md`, keeps that kind. Subfolders of `.github/agents/` are included.

Names are case-sensitive. A match in any directory is inventoried. These directory names are skipped: `.git`, `.hg`, `.svn`, `.eggs`, `.tox`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `dist`, `build`, `site-packages`, and names ending in `.egg-info`. A symlinked file that would be inventoried is not followed and is reported as an error. Every symlinked directory the walk encounters is reported as an error and is not followed.

## What it does

It walks the directory you name, prints one row per finding with `file:line` when it has a line, and returns the exit code below. Config JSON may contain `//` comments, `/* */` comments, and a trailing comma. Those are stripped only in memory so the file can be parsed. The checker does not write the stripped copy back.

`--json` prints `root`, `files`, `findings`, `errors`, and `summary`.

## What it does not do

- It does not execute a command, install a package, open a network connection, or modify a file.
- It does not decide that a repository is safe to open in a coding agent. A clean table means these patterns were absent from the inventoried files.
- It does not read source files, READMEs, or workflow files unless the name is in the inventory list.
- It does not parse the YAML frontmatter of a custom agent profile. An `mcp-servers` entry with a `command` in a `.github/agents/` file is not an `mcp-command` finding. Its lines still get the line checks.
- It does not start an MCP server, call a hook, or connect to a `url` entry. A URL-only server entry is inventoried and is not an `mcp-command` finding.
- A symlink given as the root argument is followed. Every symlinked directory encountered during the walk, including `node_modules`, is reported and gives exit 2 by design. Dangling symlinked directories are reported too. It does not scan a file larger than 2 MiB.
- It does not treat a warning as a clean result. Warnings exit `1`.

## Manual review checklist

1. Confirm you are allowed to review this repository, and record the commit you are reading.
2. Run this checker on the local clone before a coding agent opens the tree.
3. Read every inventoried file yourself. A clean checker result is a file reading, not a review.
4. Treat each WARN and each FAIL as a stop until a person records what the team will do with it.
5. Compare package names with a known-packages list your team maintains.
6. When an MCP entry declares a command or args, accept that command on an inventory or remove the entry before the agent loads it.
7. When a hook is defined, read the hook before the agent can run it.
8. Read install lines and remote-script lines yourself before anyone follows them.
9. Keep the coding agent closed during the review, and leave commands in the rule files unrun.
10. Record the decision, the commit, and who accepted any exception before the repository is opened in the agent.

## Limitations

The checks are line-oriented heuristics. A negated sentence within a few words of a phrase is skipped for three of the checks, and a prose sentence that mentions an install without those words can be missed. Package names are tokens from an install or remove line, not every word in the file. Hook detection looks for a JSON `hooks` object with a `type`, `command`, `matcher`, or string entry. Another product's schema can be missed. Custom agent coverage is the repository-level `.github/agents/` folder only. Organization and enterprise agent profiles live in a top-level `agents/` folder of a `.github` or `.github-private` repository, and personal profiles live in `~/.copilot/agents/`. Neither is inventoried. Every file under `.github/agents/` is read as UTF-8 text, so an image or other binary file there is an error and gives exit 2. A pass is not a guarantee that the repository is safe to open, and a finding is not by itself a judgment that the line is malicious. A person still reads the file.

## Authorized use

This repository is [MIT licensed](https://github.com/digitalfortressaudit/agent-repo-preflight/blob/main/LICENSE). It is for **defensive checks only**.

- Review repositories you own or are authorized to assess.
- Keep the examples as local fixtures. They are fictional and contain no hidden characters.
- Point the checker only at trees you are allowed to read.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The walk finished and there are no findings. |
| `1` | The walk finished and there is at least one WARN or FAIL. |
| `2` | A path or flag could not be used, or an inventoried file could not be read (missing directory, path is not a directory, unknown flag, missing allowlist, unreadable file, symlinked file, symlinked directory, file over 2 MiB, config that is not JSON, or JSON nested too deeply). Findings are still printed when some files were read. |

## Tests

From this directory:

```bash
python3 -m unittest discover -s tests -v
```

`.github/workflows/ci.yml` runs that command on `ubuntu-24.04` for Python 3.9, 3.10, 3.11, 3.12, and 3.13. It does not install packages and it does not open a network connection.

## Changelog

### v0.1.1

- Inventory GitHub Copilot custom agent profiles under `.github/agents/` (kind `agent`) and any other file in that folder (kind `agent-other`), and run the rule-file checks on them.

### v0.1.0

- Initial public release. Inventory the rule and config paths above, flag the checks in the table, and accept an optional package allowlist.

## For more from Digital Fortress

For more from Digital Fortress:

- **[Coding Agent Repo Trust Pack ($99)](https://fortressaudit.gumroad.com/l/qbxntsf)**, the pack closest to this script: the pre-open review of rule files, repo-declared MCP config, hooks, skills, and packages.
- **[AI Security & Infrastructure Prompt Pack ($99)](https://fortressaudit.gumroad.com/l/myyeen)**
- **[Multi-Agent Orchestration Blueprint ($149)](https://fortressaudit.gumroad.com/l/cvxfw)**
- **[Agent Runtime Containment Pack ($99)](https://fortressaudit.gumroad.com/l/ngouvf)**: agent egress, identity, Kubernetes sandboxing, and tool-call authorization.

## Other free checkers

- [MCP Tool Definition Pinning Checker](https://github.com/digitalfortressaudit/mcp-tool-pin-check) pins live tool descriptions and diffs a later `tools/list` export.
- [Kubernetes Agent Workload Hardening Checker](https://github.com/digitalfortressaudit/agent-k8s-harden-check) reads Kubernetes manifests for agent workload isolation.
- [AI Security Starter Checklist](https://github.com/digitalfortressaudit/ai-security-starter-checklist) is a free checklist and a read-only repository scan.

## Sources

- [PackHallu](https://arxiv.org/html/2610.09264)
- [The Injection, week 42](https://theinjection.dev/week/2026-w42/)

## License

[MIT](https://github.com/digitalfortressaudit/agent-repo-preflight/blob/main/LICENSE). Authorized defensive use only, as described above.

© 2026 Digital Fortress · github.com/digitalfortressaudit
