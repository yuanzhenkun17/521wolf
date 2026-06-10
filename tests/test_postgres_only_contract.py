from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = (ROOT / "app", ROOT / "storage", ROOT / "ui")
LOCAL_DB_RE = re.compile(r"\b[\w.-]+\." + "db" + r"\b")
LOCAL_GAME_ARTIFACT_FILENAMES = {
    "ui_snapshot.json",
    "archive.json",
    "game_events.jsonl",
    "agent_decisions.jsonl",
    "game_history_index.json",
    "ui_backend_tasks.json",
    "ui_backend_task_events.jsonl",
    "state.json",
    "manifest.json",
}
LOCAL_GAME_ARTIFACT_ALLOWED_FILES = {
    ROOT / "app" / "util" / "json.py",
    ROOT / "app" / "tools" / "cleanup_runs.py",
    ROOT / "app" / "tools" / "full_local_evidence_snapshot.py",
    ROOT / "app" / "tools" / "run_full_local_samples.py",
    ROOT / "app" / "tools" / "update_mvp_research_report.py",
}
EXPLICIT_EXPORT_NAME_RE = re.compile(r"\bexport\b|export_", re.IGNORECASE)


def test_runtime_code_is_postgresql_only() -> None:
    findings: list[str] = []

    for path in _runtime_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstring_locations = _docstring_locations(tree)
        visitor = _PostgresOnlyVisitor(path, docstring_locations)
        visitor.visit(tree)
        findings.extend(visitor.findings)

    assert findings == []


def test_project_dependencies_do_not_include_local_database_checkpointing() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    local_checkpoint_package = "langgraph-checkpoint-" + "sql" + "ite"

    assert "psycopg[binary]" in pyproject
    assert local_checkpoint_package not in pyproject


def test_runtime_code_does_not_use_local_game_artifacts_as_source_of_truth() -> None:
    findings: list[str] = []

    for path in _runtime_python_files():
        if path in LOCAL_GAME_ARTIFACT_ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstring_locations = _docstring_locations(tree)
        visitor = _LocalGameArtifactVisitor(path, docstring_locations)
        visitor.visit(tree)
        findings.extend(visitor.findings)

    assert findings == []


def _runtime_python_files() -> list[Path]:
    files: list[Path] = []
    for root in RUNTIME_DIRS:
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return sorted(files)


def _docstring_locations(tree: ast.AST) -> set[tuple[int, int]]:
    locations: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            locations.add((first.value.lineno, first.value.col_offset))
    return locations


class _PostgresOnlyVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, docstring_locations: set[tuple[int, int]]) -> None:
        self.path = path
        self.docstring_locations = docstring_locations
        self.findings: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        local_module = "sql" + "ite3"
        for alias in node.names:
            if alias.name == local_module or alias.name.startswith(local_module + "."):
                self._add(node, "imports local database module")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        local_module = "sql" + "ite3"
        if module == local_module or module.startswith(local_module + "."):
            self._add(node, "imports local database module")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and not self._is_docstring(node):
            storage_backend = "STORAGE" + "_BACKEND"
            if storage_backend in node.value:
                self._add(node, "references legacy storage selector")
            if LOCAL_DB_RE.search(node.value):
                self._add(node, f"references local database file {node.value!r}")
        self.generic_visit(node)

    def _is_docstring(self, node: ast.Constant) -> bool:
        return (node.lineno, node.col_offset) in self.docstring_locations

    def _add(self, node: ast.AST, message: str) -> None:
        rel = self.path.relative_to(ROOT)
        self.findings.append(f"{rel}:{getattr(node, 'lineno', '?')}: {message}")


class _LocalGameArtifactVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, docstring_locations: set[tuple[int, int]]) -> None:
        self.path = path
        self.docstring_locations = docstring_locations
        self.context_names: list[str] = []
        self.findings: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_named_context(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_named_context(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_named_context(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and not self._is_docstring(node):
            artifact_names = sorted(
                filename
                for filename in LOCAL_GAME_ARTIFACT_FILENAMES
                if filename in node.value
            )
            if artifact_names and not self._is_explicit_export_context():
                self._add(node, f"references local game artifact(s): {', '.join(artifact_names)}")
        self.generic_visit(node)

    def _visit_named_context(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.context_names.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self.context_names.pop()

    def _is_docstring(self, node: ast.Constant) -> bool:
        return (node.lineno, node.col_offset) in self.docstring_locations

    def _is_explicit_export_context(self) -> bool:
        names = [self.path.stem, *self.context_names]
        return any(EXPLICIT_EXPORT_NAME_RE.search(name) for name in names)

    def _add(self, node: ast.AST, message: str) -> None:
        rel = self.path.relative_to(ROOT)
        self.findings.append(f"{rel}:{getattr(node, 'lineno', '?')}: {message}")
