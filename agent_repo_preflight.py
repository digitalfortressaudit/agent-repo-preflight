#!/usr/bin/env python3
"""Read-only preflight for agent rule files and repo-declared MCP or hook config.

Walks a local directory, inventories the agent instruction files and MCP or
hook config a coding agent may load, and flags a fixed set of risky patterns.
This program only reads files. It does not execute commands, install packages,
open network connections, or modify the tree. Authorized defensive use only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional

__version__ = "0.1.0"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

MAX_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 64

RULE_FILENAMES = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        ".cursorrules",
        ".windsurfrules",
        "CONVENTIONS.md",
    }
)

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".eggs",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "site-packages",
    }
)

# Zero-width characters. A leading U+FEFF byte-order mark is ignored later.
_ZERO_WIDTH = frozenset({0x034F, 0x180E, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF})
_BIDI = frozenset(
    {
        0x061C,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
    }
)

_INSTALL_RE = re.compile(
    r"(?i)(?:"
    r"\bpython3?\s+-m\s+pip\s+install\b"
    r"|\b(?:pip3?|pipx)\s+(?:install|uninstall)\b"
    r"|\b(?:npm|pnpm|yarn|bun)\s+(?:ci|install|i|add|update|upgrade|uninstall|remove)\b"
    r"|\buv\s+(?:add|sync|pip\s+install|tool\s+install|remove)\b"
    r"|\bcargo\s+(?:install|add|remove)\b"
    r"|\bgo\s+install\b"
    r"|\b(?:poetry|pdm|pipenv|conda|mamba|gem|brew)\s+(?:install|add|remove|uninstall)\b"
    r")"
)
_REPLACE_RE = re.compile(
    r"(?i)\breplace\b(?:\W+\w+){0,8}\W+\b(?:package|dependency|module|library)\b"
)

_REMOTE_PIPE_RE = re.compile(
    r"(?i)\b(?:curl|wget|fetch|irm)\b[^|\n]{0,300}\|\s*(?:sudo\s+)?(?:(?:ba)?sh|iex|python3?|perl|ruby|node)\b"
)
_REMOTE_SUBST_RE = re.compile(
    r"(?i)(?:\$\(|<\()\s*(?:curl|wget|fetch|irm)\b"
)

_PERMISSION_RES = (
    ("auto-approve", re.compile(r"(?i)\bauto[-_ ]?approve(?![A-Za-z0-9])")),
    ("yolo", re.compile(r"(?i)(?<![A-Za-z0-9_])yolo(?![A-Za-z0-9_])")),
    ("skip-permissions", re.compile(r"(?i)\bskip[-_ ]?permissions(?![A-Za-z0-9])")),
    ("bypass-permissions", re.compile(r"(?i)\bbypass[-_ ]?permissions(?![A-Za-z0-9])")),
    (
        "dangerously",
        re.compile(r"(?i)\bdangerously[-_A-Za-z0-9]*"),
    ),
)

_FALSE_ASSIGN_RE = re.compile(
    r"""(?i)\s*["']?\s*[:=]\s*["']?(?:false|0|off|no|disabled|never)\b"""
)
_KEY_LINE_RES = {}
_NEGATION_BEFORE_RE = re.compile(
    r"(?i)\b(?:do not|don't|dont|cannot|can't|never|without|avoid|no|not|disable|disabled)\b"
    r"(?:\W+\w+){0,3}\W*$"
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "before",
        "by",
        "do",
        "for",
        "from",
        "if",
        "in",
        "into",
        "it",
        "of",
        "on",
        "once",
        "or",
        "our",
        "please",
        "run",
        "that",
        "the",
        "their",
        "then",
        "this",
        "to",
        "use",
        "using",
        "via",
        "when",
        "while",
        "with",
        "you",
        "your",
    }
)

_HOOK_MARKERS = frozenset({"type", "command", "matcher"})


class UsageError(Exception):
    """The path or flag could not be used. The process exits 2."""


def classify(relative: str) -> Optional[str]:
    """Return ``rule`` or ``config`` when ``relative`` is an inventoried file."""
    parts = tuple(part for part in relative.split("/") if part and part != ".")
    if not parts:
        return None
    name = parts[-1]
    parent = parts[-2] if len(parts) > 1 else ""
    if name in RULE_FILENAMES or name.startswith(".clinerules"):
        return "rule"
    if any(part.startswith(".clinerules") for part in parts[:-1]):
        return "rule"
    if name == "copilot-instructions.md" and parent == ".github":
        return "rule"
    if _under(parts, ".cursor", "rules"):
        return "rule"
    if name == "mcp.json" and parent in {".cursor", ".vscode"}:
        return "config"
    if name == "settings.json" and parent == ".vscode":
        return "config"
    if name == "config.json" and parent == ".zcode":
        return "config"
    if parent == ".claude" and name.startswith("settings") and name.endswith(".json"):
        return "config"
    return None


def _under(parts: tuple, directory: str, child: str) -> bool:
    for index, part in enumerate(parts[:-1]):
        if part == directory and index + 1 < len(parts) - 1 and parts[index + 1] == child:
            return True
    return False


def _skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.endswith(".egg-info")


def inventory(root: Path) -> tuple:
    """Return ``(files, errors)`` for inventoried paths under ``root``."""
    files = []
    errors = []

    def on_error(err: OSError) -> None:
        filename = getattr(err, "filename", None) or str(root)
        errors.append({"path": _relative_or_abs(root, filename), "line": None, "message": "directory could not be listed"})

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=on_error, followlinks=False):
        kept = []
        for name in dirnames:
            candidate = Path(dirpath) / name
            if _is_symlink(candidate):
                errors.append(
                    {
                        "path": candidate.relative_to(root).as_posix(),
                        "line": None,
                        "message": "symlinked directory was not followed",
                    }
                )
                continue
            if not _skip_dir(name):
                kept.append(name)
        dirnames[:] = kept
        for filename in filenames:
            path = Path(dirpath) / filename
            relative = path.relative_to(root).as_posix()
            if _is_symlink(path):
                if _symlink_points_at_directory(path):
                    errors.append({"path": relative, "line": None, "message": "symlinked directory was not followed"})
                elif not _symlink_target_exists(path):
                    errors.append({"path": relative, "line": None, "message": "dangling symlink was not followed"})
                elif classify(relative) is not None:
                    errors.append({"path": relative, "line": None, "message": "symlink was not followed"})
                continue
            kind = classify(relative)
            if kind is None:
                continue
            if not path.is_file():
                continue
            files.append({"path": relative, "kind": kind, "absolute": path})
    files.sort(key=lambda item: item["path"])
    errors.sort(key=lambda item: item["path"])
    return files, errors


def _is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


def _symlink_points_at_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _symlink_target_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _relative_or_abs(root: Path, filename: str) -> str:
    try:
        return Path(filename).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(filename)


def read_text(path: Path) -> tuple:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, "could not stat file: {0}".format(exc.strerror or exc.__class__.__name__)
    if size > MAX_BYTES:
        return None, "file is larger than {0} bytes and was not scanned".format(MAX_BYTES)
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return None, "file is not valid UTF-8 and was not scanned"
    except OSError as exc:
        return None, "could not read file: {0}".format(exc.strerror or exc.__class__.__name__)


def _escape_shown(text: str) -> str:
    """Escape control and other non-printable characters before they are printed."""
    parts = []
    for char in text:
        code = ord(char)
        if code < 32 or code == 127:
            parts.append("\\x{0:02x}".format(code))
            continue
        if unicodedata.category(char).startswith("C"):
            parts.append("\\u{0:04x}".format(code))
            continue
        parts.append(char)
    return "".join(parts)


def _finding(severity: str, check: str, path: str, line: Optional[int], message: str) -> dict:
    return {
        "severity": severity,
        "check": check,
        "path": path,
        "line": line,
        "message": message,
    }


def _negated(line: str, start: int) -> bool:
    prefix = line[max(0, start - 80) : start]
    return _NEGATION_BEFORE_RE.search(prefix) is not None


def _false_assignment(line: str, end: int) -> bool:
    return _FALSE_ASSIGN_RE.match(line, end) is not None


def scan_unicode(relative: str, text: str) -> list:
    grouped = {}
    line_no = 1
    for index, char in enumerate(text):
        if char == "\n":
            line_no += 1
            continue
        codepoint = ord(char)
        if codepoint == 0xFEFF and index == 0:
            continue
        if codepoint not in _ZERO_WIDTH and codepoint not in _BIDI and codepoint != 0xE0001 and not (0xE0020 <= codepoint <= 0xE007F):
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            name = "UNNAMED CHARACTER"
        label = "U+{0:04X} {1}".format(codepoint, name)
        bucket = grouped.setdefault(line_no, [])
        if label not in bucket:
            bucket.append(label)
    findings = []
    for line_no in sorted(grouped):
        findings.append(
            _finding(
                "FAIL",
                "hidden-unicode",
                relative,
                line_no,
                "hidden character: {0}".format(", ".join(grouped[line_no])),
            )
        )
    return findings


def _package_token(token: str) -> Optional[str]:
    token = token.strip("\"'`.,()[]{}")
    if not token or token.startswith("-") or token.startswith(("/", ".", "~")):
        return None
    lowered = token.lower()
    if "://" in token or lowered.startswith(("git+", "file:", "http:", "https:")):
        return None
    if lowered.endswith((".txt", ".toml", ".lock", ".in", ".cfg", ".json", ".yaml", ".yml")):
        return None
    if token.startswith("@"):
        body = token[1:]
        name, _sep, _version = body.partition("@")
        if "/" not in name or not name:
            return None
        return "@" + name
    if "@" in token:
        token = token.split("@", 1)[0]
    token = token.split("[", 1)[0]
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if separator in token:
            token = token.split(separator, 1)[0]
            break
    token = token.strip()
    if not token or token.lower() in _STOPWORDS:
        return None
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+/-]*$", token):
        return None
    return token


def packages_from_line(line: str) -> list:
    """Return package tokens that follow an install or remove command."""
    match = _INSTALL_RE.search(line)
    if match is None:
        return []
    rest = line[match.end() :]
    rest = re.split(r"\s*(?:&&|\|\||;|\|)\s*", rest, maxsplit=1)[0]
    names = []
    for raw in rest.split():
        if raw.lower().rstrip(".,") in _STOPWORDS:
            break
        if raw.startswith("-"):
            continue
        name = _package_token(raw)
        if name is None:
            if raw[:1] in {"/", ".", "~"} or "://" in raw:
                continue
            break
        names.append(name)
    return names


def scan_line_patterns(relative: str, kind: str, line_no: int, line: str, known: Optional[set]) -> list:
    findings = []
    install = _INSTALL_RE.search(line)
    replace = _REPLACE_RE.search(line)
    if install is not None and not _negated(line, install.start()):
        findings.append(
            _finding(
                "WARN",
                "package-install",
                relative,
                line_no,
                "install or replace instruction: {0}".format(_escape_shown(install.group(0))),
            )
        )
        if known is not None and kind == "rule":
            for name in packages_from_line(line):
                if name.lower() not in known:
                    findings.append(
                        _finding(
                            "WARN",
                            "unknown-package",
                            relative,
                            line_no,
                            "package not on the known-packages list: {0}".format(_escape_shown(name)),
                        )
                    )
    elif replace is not None and not _negated(line, replace.start()):
        findings.append(
            _finding(
                "WARN",
                "package-install",
                relative,
                line_no,
                "instruction to replace a package",
            )
        )
    for regex in (_REMOTE_PIPE_RE, _REMOTE_SUBST_RE):
        match = regex.search(line)
        if match is not None and not _negated(line, match.start()):
            shown = " ".join(match.group(0).split())
            if len(shown) > 80:
                shown = shown[:77] + "..."
            shown = _escape_shown(shown)
            findings.append(
                _finding(
                    "FAIL",
                    "remote-script",
                    relative,
                    line_no,
                    "remote script fetch-and-run instruction: {0}".format(shown),
                )
            )
            break
    for _label, regex in _PERMISSION_RES:
        for match in regex.finditer(line):
            if _negated(line, match.start()) or _false_assignment(line, match.end()):
                continue
            findings.append(
                _finding(
                    "FAIL",
                    "permission-bypass",
                    relative,
                    line_no,
                    "permission bypass setting: {0}".format(_escape_shown(match.group(0))),
                )
            )
    return findings


def _next_significant(text: str, index: int) -> int:
    """Return the index of the next JSON token, skipping whitespace and comments."""
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\r\n":
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index = min(length, index + 2)
            continue
        break
    return index


def relax_json(text: str) -> str:
    """Drop JSONC comments and trailing commas so config files can be read."""
    out = []
    index = 0
    length = len(text)
    in_string = False
    escape = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index < length:
                if text[index] == "\n":
                    out.append("\n")
                if text[index] == "*" and index + 1 < length and text[index + 1] == "/":
                    index += 2
                    break
                index += 1
            continue
        if char == ",":
            nxt = _next_significant(text, index + 1)
            if nxt < length and text[nxt] in "}]":
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _key_line_re(key: str):
    pattern = _KEY_LINE_RES.get(key)
    if pattern is None:
        pattern = re.compile(r'["\']' + re.escape(key) + r'["\']\s*:')
        _KEY_LINE_RES[key] = pattern
    return pattern


def _key_line(text: str, key: str, start: int = 0) -> Optional[int]:
    pattern = _key_line_re(key)
    match = pattern.search(text, start)
    if match is None and start:
        match = pattern.search(text, 0)
    if match is None:
        return None
    return _line_of(text, match.start())


def _iter_server_maps(value, file_name: str, parent: Optional[str] = None):
    stack = [(value, parent)]
    while stack:
        current, current_parent = stack.pop()
        if isinstance(current, list):
            for item in reversed(current):
                stack.append((item, current_parent))
            continue
        if not isinstance(current, dict):
            continue
        for key, child in reversed(list(current.items())):
            if key.lower() == "hooks":
                continue
            normalized = key.lower().replace("-", "").replace("_", "")
            if normalized == "mcpservers" and isinstance(child, dict):
                yield child
                continue
            if key == "servers" and isinstance(child, dict) and ((current_parent or "").lower() == "mcp" or file_name == "mcp.json"):
                yield child
                continue
            stack.append((child, key))


def _declares_process(config: dict) -> Optional[str]:
    command = config.get("command")
    args = config.get("args")
    has_command = False
    has_args = False
    if isinstance(command, str) and command.strip():
        has_command = True
    elif isinstance(command, list) and any(str(item).strip() for item in command):
        has_command = True
    if isinstance(args, str) and args.strip():
        has_args = True
    elif isinstance(args, list) and any(str(item).strip() for item in args):
        has_args = True
    if has_command and has_args:
        return "command and args"
    if has_command:
        return "command"
    if has_args:
        return "args"
    return None


def scan_mcp(relative: str, text: str, data) -> list:
    file_name = relative.rsplit("/", 1)[-1]
    findings = []
    cursor = 0
    cursor_line = 1
    for server_map in _iter_server_maps(data, file_name):
        for name, config in server_map.items():
            if not isinstance(config, dict):
                continue
            declared = _declares_process(config)
            if declared is None:
                continue
            needle = '"{0}"'.format(name)
            anchor = text.find(needle, cursor)
            rewound = False
            if anchor < 0:
                anchor = text.find(needle, 0)
                rewound = anchor >= 0
            field = "command" if "command" in declared else "args"
            pattern = _key_line_re(field)
            if anchor < 0:
                match = pattern.search(text, 0)
                line = _line_of(text, match.start()) if match is not None else None
            else:
                if rewound:
                    cursor = 0
                    cursor_line = 1
                cursor_line += text.count("\n", cursor, anchor)
                name_line = cursor_line
                match = pattern.search(text, anchor)
                if match is None:
                    match = pattern.search(text, 0)
                    line = _line_of(text, match.start()) if match is not None else None
                else:
                    line = name_line + text.count("\n", anchor, match.start())
                next_cursor = anchor + len(needle)
                cursor_line = name_line + text.count("\n", anchor, next_cursor)
                cursor = next_cursor
            findings.append(
                _finding(
                    "FAIL",
                    "mcp-command",
                    relative,
                    line,
                    'MCP server "{0}" declares {1}'.format(_escape_shown(str(name)), declared),
                )
            )
    return findings


def _has_hook_definition(value) -> bool:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if _HOOK_MARKERS.intersection(current):
                return True
            stack.extend(current.values())
            continue
        if isinstance(current, list):
            for child in current:
                if isinstance(child, str):
                    if child.strip():
                        return True
                else:
                    stack.append(child)
    return False


def _walk_hooks(value):
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                if key.lower() == "hooks":
                    if _has_hook_definition(child):
                        yield child
                else:
                    stack.append(child)
            continue
        if isinstance(current, list):
            stack.extend(current)


def scan_hooks(relative: str, text: str, data) -> list:
    if not any(True for _ in _walk_hooks(data)):
        return []
    line = _key_line(text, "hooks", 0)
    return [
        _finding(
            "FAIL",
            "hooks",
            relative,
            line,
            "hook definition present",
        )
    ]


def _max_json_depth(text: str) -> int:
    depth = 0
    maximum = 0
    in_string = False
    escape = False
    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in "{[":
            depth += 1
            if depth > maximum:
                maximum = depth
                if maximum > MAX_JSON_DEPTH:
                    return maximum
        elif char in "}]" and depth:
            depth -= 1
    return maximum


def scan_config(relative: str, text: str) -> tuple:
    if not text.strip():
        return [], None
    try:
        relaxed = relax_json(text)
        if _max_json_depth(relaxed) > MAX_JSON_DEPTH:
            return [], "JSON nesting is too deep and was not parsed"
        data = json.loads(relaxed)
        findings = []
        findings.extend(scan_mcp(relative, text, data))
        findings.extend(scan_hooks(relative, text, data))
    except json.JSONDecodeError as exc:
        return [], "invalid JSON at line {0}".format(exc.lineno)
    except RecursionError:
        return [], "JSON nesting is too deep and was not parsed"
    except ValueError as exc:
        return [], "invalid JSON: {0}".format(exc)
    return findings, None


def scan_file(item: dict, known: Optional[set]) -> tuple:
    text, error = read_text(item["absolute"])
    if error is not None:
        return [], {"path": item["path"], "line": None, "message": error}
    findings = []
    findings.extend(scan_unicode(item["path"], text))
    for line_no, line in enumerate(text.splitlines(), start=1):
        findings.extend(scan_line_patterns(item["path"], item["kind"], line_no, line, known))
    errors = []
    if item["kind"] == "config":
        config_findings, config_error = scan_config(item["path"], text)
        findings.extend(config_findings)
        if config_error is not None:
            errors.append({"path": item["path"], "line": None, "message": config_error})
    return findings, errors


def load_known_packages(path: Path) -> set:
    if not path.is_file():
        raise UsageError("known-packages file not found: {0}".format(path))
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UsageError("known-packages file is not valid UTF-8: {0}".format(path)) from exc
    except OSError as exc:
        raise UsageError("known-packages file could not be read: {0}".format(path)) from exc
    names = set()
    for line in text.splitlines():
        body = line.split("#", 1)[0].strip()
        if body:
            names.add(body.lower())
    return names


def examine(root: Path, known: Optional[set]) -> dict:
    files, errors = inventory(root)
    findings = []
    for item in files:
        file_findings, file_errors = scan_file(item, known)
        findings.extend(file_findings)
        if isinstance(file_errors, dict):
            errors.append(file_errors)
        else:
            errors.extend(file_errors)
    findings = _dedupe(findings)
    findings.sort(key=lambda item: (item["path"], item["line"] or 0, 0 if item["severity"] == "FAIL" else 1, item["check"], item["message"]))
    errors.sort(key=lambda item: (item["path"], item["message"]))
    public_files = [{"path": item["path"], "kind": item["kind"]} for item in files]
    summary = {
        "files": len(public_files),
        "warn": sum(1 for item in findings if item["severity"] == "WARN"),
        "fail": sum(1 for item in findings if item["severity"] == "FAIL"),
        "errors": len(errors),
    }
    return {
        "root": str(root),
        "files": public_files,
        "findings": findings,
        "errors": errors,
        "summary": summary,
    }


def _dedupe(findings: list) -> list:
    seen = set()
    unique = []
    for item in findings:
        key = (item["severity"], item["check"], item["path"], item["line"], item["message"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def format_text(report: dict) -> str:
    lines = [
        "Agent repo preflight",
        "",
        "root: {0}".format(_escape_shown(str(report["root"]))),
        "files inventoried: {0}".format(report["summary"]["files"]),
        "",
    ]
    if report["files"]:
        lines.append("inventoried:")
        for item in report["files"]:
            lines.append("  {0}  ({1})".format(_escape_shown(item["path"]), item["kind"]))
        lines.append("")
    if report["errors"]:
        lines.append("errors:")
        for item in report["errors"]:
            lines.append("  {0}: {1}".format(_escape_shown(item["path"]), _escape_shown(item["message"])))
        lines.append("")
    if not report["findings"]:
        lines.append("No findings.")
    else:
        rows = []
        for item in report["findings"]:
            shown_path = _escape_shown(item["path"])
            location = shown_path if not item["line"] else "{0}:{1}".format(shown_path, item["line"])
            rows.append((item["severity"], item["check"], location, _escape_shown(item["message"])))
        headers = ("severity", "check", "location", "detail")
        widths = [len(cell) for cell in headers]
        for row in rows:
            for index, cell in enumerate(row):
                widths[index] = max(widths[index], len(cell))

        def render(row: tuple) -> str:
            return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip()

        lines.append(render(headers))
        lines.append(render(tuple("-" * width for width in widths)))
        for row in rows:
            lines.append(render(row))
    summary = report["summary"]
    lines.extend(
        [
            "",
            "summary: files={files} warn={warn} fail={fail} errors={errors}".format(**summary),
            "This is a reading of local files. It is not permission to open the repository in a coding agent.",
        ]
    )
    return "\n".join(lines) + "\n"


def exit_code(report: dict) -> int:
    if report["errors"]:
        return EXIT_USAGE
    if report["findings"]:
        return EXIT_FINDINGS
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-repo-preflight",
        description=(
            "Inventory agent rule files and repo-declared MCP or hook config in a "
            "local directory, and flag hidden Unicode, package install instructions, "
            "remote script fetch-and-run lines, permission-bypass settings, MCP "
            "command entries, and hook definitions. Read-only: does not execute, "
            "install, fetch, or modify anything. Authorized defensive use only."
        ),
    )
    parser.add_argument("directory", help="Local directory to walk")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a text table")
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s {0}".format(__version__),
    )
    parser.add_argument(
        "--known-packages",
        metavar="FILE",
        help=(
            "Allowlist of package names, one per line. "
            "Report names in rule-file install instructions that are not listed."
        ),
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    """Walk a directory. Exit 0 when clean, 1 on findings, 2 on a usage error."""
    args = build_parser().parse_args(argv)
    root = Path(args.directory)
    if not root.exists():
        print("error: directory not found: {0}".format(root), file=sys.stderr)
        return EXIT_USAGE
    if not root.is_dir():
        print("error: path is not a directory: {0}".format(root), file=sys.stderr)
        return EXIT_USAGE
    known = None
    if args.known_packages:
        try:
            known = load_known_packages(Path(args.known_packages))
        except UsageError as exc:
            print("error: {0}".format(exc), file=sys.stderr)
            return EXIT_USAGE
    report = examine(root, known)
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(format_text(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
