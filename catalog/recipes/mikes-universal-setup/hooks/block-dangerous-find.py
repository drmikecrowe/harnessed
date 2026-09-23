#!/usr/bin/env python3

import json
import os
import pwd
import shlex
import sys


def block(message: str) -> None:
    print(f"Blocked Bash command: {message}", file=sys.stderr)
    sys.exit(2)  # PreToolUse exit code 2 aborts the tool call


def tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(
        command,
        posix=True,
        punctuation_chars=";&|()<>\n",
    )
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def is_command_boundary(token: str) -> bool:
    return token == ")" or any(c in token for c in ";&|\n")


def is_find(token: str) -> bool:
    return os.path.basename(token) == "find"


def home_directories() -> set[str]:
    homes = {
        os.path.realpath(os.path.expanduser("~")),
        os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir),
    }

    if os.environ.get("HOME"):
        homes.add(os.path.realpath(os.environ["HOME"]))

    return homes


HOMES = home_directories()
FORBIDDEN = {"/", *HOMES}


def resolve_path(path: str) -> str:
    # Expand common ways Claude may spell the current user's home.
    for marker in ("$HOME", "${HOME}"):
        if path == marker or path.startswith(marker + "/"):
            path = os.environ.get("HOME", os.path.expanduser("~")) + path[len(marker) :]
            break

    path = os.path.expanduser(path)

    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    return os.path.realpath(path)


def starting_paths_after(tokens: list[str], find_index: int) -> list[str]:
    """Return find's starting paths, stopping when its expression begins."""
    paths = []
    i = find_index + 1

    # find's global options
    while i < len(tokens):
        token = tokens[i]

        if token in ("-H", "-L", "-P") or token.startswith("-O"):
            i += 1
        elif token == "-D":
            i += 2
        else:
            break

    while i < len(tokens):
        token = tokens[i]

        if is_command_boundary(token):
            break

        # Skip shell redirections.
        if token.isdigit() and i + 1 < len(tokens) and set(tokens[i + 1]) <= set("<>"):
            i += 3
            continue

        if token and set(token) <= set("<>"):
            i += 2
            continue

        if token == "--":
            i += 1
            continue

        # find expressions begin with -, !, or (
        if token == "!" or token == "(" or token.startswith("-"):
            break

        paths.append(token)
        i += 1

    return paths


try:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")

    if not isinstance(command, str):
        block("could not safely inspect the Bash command")

    tokens = tokenize(command)

    for index, token in enumerate(tokens):
        if not is_find(token):
            continue

        paths = starting_paths_after(tokens, index)

        # With no starting path, find defaults to the current directory.
        if not paths:
            paths = ["."]

        for path in paths:
            resolved = resolve_path(path)
            if resolved in FORBIDDEN:
                block(f"find may not run on {resolved!r}")

except SystemExit:
    raise
except Exception as exc:
    # Fail closed if the command cannot be safely inspected.
    block(f"could not safely inspect command: {exc}")

sys.exit(0)
