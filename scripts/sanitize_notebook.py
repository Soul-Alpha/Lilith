#!/usr/bin/env python3
"""Repair, normalize, and sanitize the committed Edith notebook.

This script preserves notebook source cells while repairing malformed JSON,
removing embedded MT5 credentials, saved outputs, execution counts, and invalid
notebook metadata. It does not modify trading calculations, signal generation,
risk rules, or execution logic.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import nbformat
from json_repair import repair_json
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


def load_repaired_notebook(path: Path) -> tuple[nbformat.NotebookNode, bool]:
    """Load valid JSON or conservatively repair a malformed notebook document."""
    raw = path.read_text(encoding="utf-8-sig")
    repaired = False

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        repaired_text = repair_json(raw, skip_json_loads=True)
        try:
            payload = json.loads(repaired_text)
        except json.JSONDecodeError as repair_exc:
            raise ValueError(
                f"Unable to repair notebook JSON after original error at "
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from repair_exc
        repaired = True
        print(
            "Repaired malformed notebook JSON "
            f"(original error: line {exc.lineno}, column {exc.colno}: {exc.msg})."
        )

    if not isinstance(payload, dict):
        raise ValueError("Notebook root must be a JSON object")
    if not isinstance(payload.get("cells"), list):
        raise ValueError("Notebook must contain a cells array")

    return nbformat.from_dict(payload), repaired


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
    notebook, repaired = load_repaired_notebook(NOTEBOOK)
    normalization_changes, notebook = normalize(notebook, relax_add_props=True)
    changed = repaired or normalization_changes > 0

    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue

        source_value = cell.get("source", [])
        if isinstance(source_value, str):
            source_lines = source_value.splitlines(keepends=True)
        else:
            source_lines = list(source_value)

        source, source_changed = sanitize_source(source_lines)
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
        print("Notebook already valid, normalized, and sanitized.")
        return 0

    nbformat.write(notebook, NOTEBOOK, version=4)
    # Re-read the emitted file so CI proves the committed representation is valid.
    emitted = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(emitted)
    print("Repaired, normalized, and sanitized edith.ipynb; source logic preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
