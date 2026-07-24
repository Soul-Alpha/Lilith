#!/usr/bin/env python3
"""Remove embedded MT5 credentials and saved notebook outputs.

This script only edits credential assignments/imports and output metadata. It does
not modify trading calculations, signal generation, risk rules, or execution logic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

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
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    changed = False

    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue

        source, source_changed = sanitize_source(cell.get("source", []))
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

    if not changed:
        print("Notebook already sanitized.")
        return 0

    NOTEBOOK.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print("Sanitized edith.ipynb: credentials externalized and outputs cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
