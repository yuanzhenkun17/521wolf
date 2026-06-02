"""Structural tests enforcing layered architecture in agent.

Verifies:
- No root-level .py files other than __init__.py (no shims)
- No v1_*.py files anywhere in agent/
- Python bytecode/cache outputs are ignored by git
- No imports through shim module paths (only legit packages or __init__)
- No imports from the old playeragent package
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_ROOT = ROOT / "agent"

# Packages that correspond to actual directories (legitimate subpackages)
_SUBPACKAGES = {
    d.name for d in AGENT_ROOT.iterdir()
    if d.is_dir() and (d / "__init__.py").exists()
}


def _find_py_files(root: Path, *, skip_structural: bool = True) -> list[Path]:
    """Recursively find .py files, excluding __pycache__ and .git dirs."""
    files = []
    for pyfile in sorted(root.rglob("*.py")):
        rel = pyfile.relative_to(ROOT)
        if any(p.startswith(".") or p == "__pycache__" or p == ".git" for p in rel.parts):
            continue
        if skip_structural and "structural" in pyfile.name:
            continue
        files.append(pyfile)
    return files


def _parse_imports(path: Path) -> list[str]:
    """Extract all module-level import strings from a .py file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _find_shim_violations(root: Path) -> list[str]:
    """Find imports referencing agent.X where X is a shim (not a subpackage)."""
    violations = []
    for pyfile in _find_py_files(root):
        rel = pyfile.relative_to(ROOT)
        for imp in _parse_imports(pyfile):
            parts = imp.split(".")
            if len(parts) >= 3 and parts[0] == "agent":
                module_name = parts[1]
                if module_name not in _SUBPACKAGES and module_name != "__init__":
                    violations.append(f"{rel}: {imp}")
    return violations


def _find_playeragent_imports(root: Path) -> list[str]:
    """Find imports from the old playeragent package."""
    violations = []
    for pyfile in _find_py_files(root):
        rel = pyfile.relative_to(ROOT)
        for imp in _parse_imports(pyfile):
            if imp == "playeragent" or imp.startswith("playeragent."):
                violations.append(f"{rel}: {imp}")
    return violations


class NoRootShimsTest(unittest.TestCase):
    """No .py files should exist at agent/ root except __init__.py."""

    def test_only_init_py_at_root(self):
        root_py_files = list(AGENT_ROOT.glob("*.py"))
        names = {p.name for p in root_py_files}
        extra = names - {"__init__.py"}
        self.assertEqual(
            names, {"__init__.py"},
            f"Root shim files still exist: {sorted(extra)}",
        )


class NoV1FilesTest(unittest.TestCase):
    """No v1_*.py files should exist anywhere in agent/."""

    def test_no_v1_files(self):
        v1_files = list(AGENT_ROOT.rglob("v1_*.py"))
        self.assertFalse(v1_files, f"v1_* files still exist: {v1_files}")


class BytecodeIgnoredTest(unittest.TestCase):
    """Python bytecode/cache outputs should be ignored by git.

    The test runner itself creates __pycache__ directories, so asserting that
    they do not exist is unstable. The enforceable source-control boundary is
    that they must be ignored.
    """

    def test_python_bytecode_outputs_are_ignored(self):
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", ignore_text)
        self.assertIn("*.py[cod]", ignore_text)


class NoShimImportsInAgentTest(unittest.TestCase):
    """No imports inside agent/ should reference shim paths."""

    def test_no_shim_imports(self):
        violations = _find_shim_violations(AGENT_ROOT)
        self.assertFalse(
            violations,
            "Shim imports found in agent/:\n" + "\n".join(violations),
        )


class NoShimImportsInTestsTest(unittest.TestCase):
    """No imports in tests/ should reference shim paths."""

    def test_no_shim_imports_in_tests(self):
        violations = _find_shim_violations(ROOT / "tests")
        self.assertFalse(
            violations,
            "Shim imports found in tests/:\n" + "\n".join(violations),
        )


class NoPlayeragentPackageImportsTest(unittest.TestCase):
    """No imports from the old playeragent package."""

    def test_no_playeragent_imports_in_agent(self):
        violations = _find_playeragent_imports(AGENT_ROOT)
        self.assertFalse(
            violations,
            "playeragent package imports found in agent/:\n" + "\n".join(violations),
        )

    def test_no_playeragent_imports_in_tests(self):
        violations = _find_playeragent_imports(ROOT / "tests")
        self.assertFalse(
            violations,
            "playeragent package imports found in tests/:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
