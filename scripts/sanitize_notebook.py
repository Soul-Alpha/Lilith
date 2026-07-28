#!/usr/bin/env python3
"""Normalize and sanitize the committed Edith notebook.

This script preserves notebook source cells while removing embedded MT5
credentials, saved outputs, execution counts, and invalid notebook metadata.
It does not modify trading calculations, signal generation, risk rules, or
execution logic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import nbformat
from nbformat.validator import normalize

NOTEBOOK = Path("edith.ipynb")

ASSIGNMENT_PATTERNS = {
    "login": re.compile(r"^(?P<indent>\s*)login\s*=.*$"),
    "password": re.compile(r"^(?P<indent>\s*)password\s*=.*$"),
    "server": re.compile(r"^(?P<indent>\s*)server\s*=.*$"),
}

REPLACEMENTS = {
    "login": 'login = int(os.environ["MT5_LOGIN"])  # Required environment variable',
    "password": 'password = os.environ["MT5_PASSWORD"]  # Never commit credentials',
    "server": 'server = os.environ["MT5_SERVER"]  # Required environment variable',
}


def sanitize_source(source: list[str]) -> tuple[list[str], bool]:
    changed = False
    output: list[str] = []
    needs_os = False

    for line in source:
        raw = line.rstrip("\n")
        newline = "\n" if line.endswith("\n") else ""
        replacement = None

        for name, pattern in ASSIGNMENT_PATTERNS.items():
            match = pattern.match(raw)
            if match:
                replacement = f"{match.group('indent')}{REPLACEMENTS[name]}{newline}"
                needs_os = True
                break

        if replacement is not None:
            if replacement != line:
                changed = True
            output.append(replacement)
        else:
            output.append(line)

    if needs_os and not any(re.match(r"^\s*import\s+os(?:\s|$)", line) for line in output):
        insert_at = next(
            (index for index, line in enumerate(output) if line.lstrip().startswith(("import ", "from "))),
            0,
        )
        output.insert(insert_at, "import os\n")
        changed = True

    return output, changed


def main() -> int:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    normalization_changes, notebook = normalize(notebook, relax_add_props=True)
    changed = normalization_changes > 0

    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue

        source, source_changed = sanitize_source(list(cell.get("source", [])))
        if source_changed:
            cell["source"] = source
            changed = True

        # Saved output can expose account IDs, balances, server names, and errors.
        if cell.get("outputs"):
            cell["outputs"] = []
            changed = True
        if cell.get("execution_count") is not None:
            cell["execution_count"] = None
            changed = True

    nbformat.validate(notebook)

    if not changed:
        print("Notebook already normalized and sanitized.")
        return 0

    nbformat.write(notebook, NOTEBOOK, version=4)
    print("Normalized and sanitized edith.ipynb; source logic preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
