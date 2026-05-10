"""Multi-language parser engine that coordinates language-specific parsers."""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
from typing import Optional

from .types import FileNode, DependencyGraph, ImportEdge
from ..languages.base import LanguageParser, ParseResult
from ..languages.python import PythonParser


class ParserEngine:
    """Orchestrates parsing of a codebase using language-specific parsers."""

    def __init__(self) -> None:
        self.parsers: list[LanguageParser] = [
            PythonParser(),
        ]
        self._file_cache: dict[str, FileNode] = {}

    def register_parser(self, parser: LanguageParser) -> None:
        """Register a new language parser."""
        self.parsers.append(parser)

    def get_parser(self, file_path: str) -> Optional[LanguageParser]:
        """Get the appropriate parser for a file."""
        for parser in self.parsers:
            if parser.can_parse(file_path):
                return parser
        return None

    def parse_file(self, file_path: str) -> ParseResult:
        """Parse a single file."""
        parser = self.get_parser(file_path)
        if parser is None:
            return ParseResult(
                file_node=FileNode(path=file_path, language="unknown"),
                errors=[f"No parser available for {file_path}"],
            )
        result = parser.parse_file(file_path)
        if result.success:
            self._file_cache[file_path] = result.file_node
        return result

    def parse_directory(
        self,
        root_dir: str,
        exclude_patterns: Optional[list[str]] = None,
        progress_callback: Optional[callable] = None,
    ) -> DependencyGraph:
        """Parse all supported files in a directory tree."""
        exclude_patterns = exclude_patterns or [
            "__pycache__", ".git", ".venv", "venv", "node_modules",
            ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
            "*.pyc", "*.egg-info",
        ]
        graph = DependencyGraph()
        py_files = self._collect_files(root_dir, exclude_patterns)
        total = len(py_files)

        for i, file_path in enumerate(py_files):
            if progress_callback:
                progress_callback(i, total, file_path)
            result = self.parse_file(file_path)
            if result.success:
                graph.add_file_node(result.file_node)

        # Build import edges between files
        self._build_import_edges(graph, root_dir)

        return graph

    def parse_files(self, file_paths: list[str]) -> DependencyGraph:
        """Parse a specific set of files."""
        graph = DependencyGraph()
        for fp in file_paths:
            result = self.parse_file(fp)
            if result.success:
                graph.add_file_node(result.file_node)
        return graph

    def _collect_files(self, root_dir: str, exclude_patterns: list[str]) -> list[str]:
        """Collect all parseable files from a directory."""
        result: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Filter out excluded directories
            dirnames[:] = [
                d for d in dirnames
                if not any(self._match_pattern(d, p) for p in exclude_patterns)
            ]
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                if any(self._match_pattern(fname, p) for p in exclude_patterns):
                    continue
                if self.get_parser(full_path):
                    result.append(full_path)
        return sorted(result)

    def _build_import_edges(self, graph: DependencyGraph, root_dir: str) -> None:
        """Infer import edges between files in the graph."""
        # Map module names to file paths
        module_to_file: dict[str, str] = {}
        for fp, node in graph.file_nodes.items():
            rel = os.path.relpath(fp, root_dir)
            mod_name = rel.replace(os.sep, ".").removesuffix(".py")
            module_to_file[mod_name] = fp
            # Also map by basename
            base = os.path.splitext(os.path.basename(fp))[0]
            module_to_file[base] = fp

        for fp, node in graph.file_nodes.items():
            for imp in node.imports:
                target_file = self._resolve_import(imp, module_to_file, os.path.dirname(fp))
                if target_file and target_file in graph.file_nodes:
                    graph.add_import_edge(ImportEdge(
                        importer=fp,
                        imported=target_file,
                        symbols=[imp],
                    ))

    def _resolve_import(
        self, import_name: str, module_map: dict[str, str], current_dir: str,
    ) -> Optional[str]:
        """Resolve an import name to a file path."""
        # Direct match
        if import_name in module_map:
            return module_map[import_name]
        # Try relative to current dir
        parts = import_name.split(".")
        # Try top-level module name
        top = parts[0]
        if top in module_map:
            return module_map[top]
        # Try relative path
        candidate = os.path.join(current_dir, *parts) + ".py"
        if os.path.exists(candidate):
            return candidate.replace(os.sep, "/")
        candidate = os.path.join(current_dir, *parts[:-1], parts[-1] + ".py")
        if os.path.exists(candidate):
            return candidate.replace(os.sep, "/")
        return None

    @staticmethod
    def _match_pattern(name: str, pattern: str) -> bool:
        """Simple glob-style pattern matching."""
        import fnmatch
        return fnmatch.fnmatch(name, pattern)

    def compute_content_hash(self, file_path: str) -> str:
        """Compute a SHA-256 hash of file contents."""
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
