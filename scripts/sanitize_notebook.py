#!/usr/bin/env python3
"""Deterministically rebuild and sanitize the committed Edith notebook.

The source notebook has malformed JSON and inconsistent legacy format metadata.
This script recovers the cells, rebuilds a fresh nbformat-v4 container, removes
saved outputs and embedded MT5 credentials, and validates the emitted notebook.
Trading calculations and source ordering are otherwise preserved.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import nbformat
from json_repair import repair_json

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


def load_payload(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        repaired = repair_json(raw, skip_json_loads=True)
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError as repair_exc:
            raise ValueError(
                "Unable to recover notebook JSON after original error at "
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from repair_exc
        print(
            "Recovered malformed notebook JSON "
            f"(line {exc.lineno}, column {exc.colno}: {exc.msg})."
        )

    if not isinstance(payload, dict):
        raise ValueError("Notebook root must be a JSON object")
    if not isinstance(payload.get("cells"), list):
        raise ValueError("Notebook must contain a cells array")
    return payload


def source_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    if value is None:
        return ""
    return str(value)


def sanitize_code(source: str) -> str:
    lines = source.splitlines(keepends=True)
    output: list[str] = []
    needs_os = False

    for line in lines:
        raw = line.rstrip("\r\n")
        ending = line[len(raw) :]
        replacement: str | None = None

        for name, pattern in ASSIGNMENT_PATTERNS.items():
            match = pattern.match(raw)
            if match:
                replacement = f"{match.group('indent')}{REPLACEMENTS[name]}{ending}"
                needs_os = True
                break

        output.append(replacement if replacement is not None else line)

    if needs_os and not any(
        re.match(r"^\s*import\s+os(?:\s|$)", line) for line in output
    ):
        insert_at = next(
            (
                index
                for index, line in enumerate(output)
                if line.lstrip().startswith(("import ", "from "))
            ),
            0,
        )
        output.insert(insert_at, "import os\n")

    return "".join(output)


def safe_metadata(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def rebuild_notebook(payload: dict[str, Any]) -> nbformat.NotebookNode:
    rebuilt_cells: list[nbformat.NotebookNode] = []

    for index, original in enumerate(payload["cells"]):
        if not isinstance(original, dict):
            print(f"Skipping non-object cell at index {index}.")
            continue

        cell_type = str(original.get("cell_type", "raw")).lower()
        source = source_to_text(original.get("source", ""))
        metadata = safe_metadata(original.get("metadata"))

        if cell_type == "code":
            rebuilt = nbformat.v4.new_code_cell(
                source=sanitize_code(source),
                metadata=metadata,
                execution_count=None,
                outputs=[],
            )
        elif cell_type == "markdown":
            rebuilt = nbformat.v4.new_markdown_cell(source=source, metadata=metadata)
        else:
            # Unknown or legacy cell kinds are retained as raw text rather than lost.
            rebuilt = nbformat.v4.new_raw_cell(source=source, metadata=metadata)

        rebuilt_cells.append(rebuilt)

    if not rebuilt_cells:
        raise ValueError("No recoverable notebook cells were found")

    root_metadata = safe_metadata(payload.get("metadata"))
    notebook = nbformat.v4.new_notebook(cells=rebuilt_cells, metadata=root_metadata)
    notebook["nbformat"] = 4
    notebook["nbformat_minor"] = 5
    return notebook


def main() -> int:
    payload = load_payload(NOTEBOOK)
    notebook = rebuild_notebook(payload)

    nbformat.validate(notebook)
    nbformat.write(notebook, NOTEBOOK, version=4)

    # Validate the exact representation that will be committed.
    emitted = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(emitted)

    print(
        f"Rebuilt and validated edith.ipynb as nbformat v4 with "
        f"{len(emitted.cells)} preserved cells; outputs cleared and credentials externalized."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
