"""Base interface for language-specific parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..core.types import Symbol, Reference, FileNode


@dataclass
class ParseResult:
    """Result of parsing a single source file."""
    file_node: FileNode
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_time_ms: float = 0.0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class LanguageParser(ABC):
    """Abstract base for language-specific code parsers."""

    language: str = "unknown"
    extensions: list[str] = []

    @abstractmethod
    def parse_file(self, file_path: str) -> ParseResult:
        """Parse a single source file and extract symbols and references."""

    @abstractmethod
    def parse_source(self, source: str, file_path: str = "<string>") -> ParseResult:
        """Parse source code string and extract symbols and references."""

    def can_parse(self, file_path: str) -> bool:
        """Check if this parser can handle the given file."""
        return any(file_path.endswith(ext) for ext in self.extensions)

    def _make_file_node(self, path: str, language: str = "") -> FileNode:
        return FileNode(path=path, language=language or self.language)
