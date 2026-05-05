"""Verify every src/ Python file starts with a module docstring of >=80 chars.

Anti-vibe rule #5: every file ships with a one-paragraph header. This is the
mechanical enforcement. Run from project root: `python runbooks/scripts/check_headers.py src/`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MIN_DOCSTRING_LEN = 80


def check(path: Path) -> str | None:
    src = path.read_text()
    if not src.strip():
        return None  # empty __init__.py is fine
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"syntax error: {e}"
    doc = ast.get_docstring(tree)
    if doc is None:
        return "missing module docstring"
    if len(doc) < MIN_DOCSTRING_LEN:
        return f"docstring too short ({len(doc)} chars; need >={MIN_DOCSTRING_LEN})"
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: check_headers.py <root> [<root> ...]", file=sys.stderr)
        return 2
    failures: list[tuple[Path, str]] = []
    for root_str in argv[1:]:
        root = Path(root_str)
        for py in root.rglob("*.py"):
            if "__init__.py" in py.name and py.read_text().strip() == "":
                continue
            err = check(py)
            if err:
                failures.append((py, err))
    if failures:
        for path, msg in failures:
            print(f"{path}: {msg}", file=sys.stderr)
        return 1
    print(f"OK: all .py files under {', '.join(argv[1:])} have valid headers")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
