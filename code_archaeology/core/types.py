"""Core type definitions for the Code Archaeology system."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class SymbolKind(enum.Enum):
    """Kinds of code symbols the system understands."""
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    MODULE = "module"
    PARAMETER = "parameter"
    PROPERTY = "property"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    DECORATOR = "decorator"
    UNKNOWN = "unknown"


class RefactoringKind(enum.Enum):
    """Types of refactoring operations available."""
    RENAME = "rename"
    EXTRACT_FUNCTION = "extract_function"
    EXTRACT_CLASS = "extract_class"
    MOVE_SYMBOL = "move_symbol"
    MOVE_FILE = "move_file"
    CHANGE_SIGNATURE = "change_signature"
    INLINE = "inline"
    REORDER_PARAMS = "reorder_params"
    ADD_PARAMETER = "add_parameter"
    REMOVE_PARAMETER = "remove_parameter"


class RiskLevel(enum.Enum):
    """Risk assessment for refactoring operations."""
    SAFE = "safe"          # No risk - rename local var, etc.
    LOW = "low"            # Low risk - rename private method
    MEDIUM = "medium"      # Medium risk - rename public API
    HIGH = "high"          # High risk - change widely-used interface
    CRITICAL = "critical"  # Critical risk - change core framework API


@dataclass
class Location:
    """A location in a source file."""
    file: str
    line: int
    column: int
    end_line: int = 0
    end_column: int = 0

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"

    def __hash__(self) -> int:
        return hash((self.file, self.line, self.column))


@dataclass
class Symbol:
    """A named code symbol (function, class, variable, etc.)."""
    name: str
    kind: SymbolKind
    location: Location
    qualified_name: str = ""
    parent: Optional[str] = None     # Parent scope (class name, module)
    docstring: Optional[str] = None
    signature: Optional[str] = None  # Function signature if applicable
    visibility: str = "public"       # public, private, protected
    is_exported: bool = True
    metadata: dict = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.qualified_name, self.location))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Symbol):
            return NotImplemented
        return self.qualified_name == other.qualified_name and self.location == other.location


@dataclass
class Reference:
    """A reference from one symbol to another."""
    source: Symbol
    target_qualified_name: str
    location: Location
    ref_type: str = "call"  # call, import, inheritance, type_annot, access
    context: str = ""       # Surrounding code context for disambiguation

    def __hash__(self) -> int:
        return hash((self.source.qualified_name, self.target_qualified_name, self.location))


@dataclass
class FileNode:
    """Represents a source file in the dependency graph."""
    path: str
    symbols: dict[str, Symbol] = field(default_factory=dict)
    references: list[Reference] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)
    language: str = ""
    content_hash: str = ""
    lines: list[str] = field(default_factory=list)

    def get_symbol(self, name: str) -> Optional[Symbol]:
        return self.symbols.get(name)

    def find_references_to(self, qualified_name: str) -> list[Reference]:
        return [r for r in self.references if r.target_qualified_name == qualified_name]


@dataclass
class ImportEdge:
    """An edge representing an import relationship between files."""
    importer: str       # File that does the importing
    imported: str       # File being imported
    symbols: list[str]  # Specific symbols imported
    import_line: int = 0
    is_dynamic: bool = False


@dataclass
class CallEdge:
    """An edge representing a call/use relationship between symbols."""
    caller: str         # Qualified name of caller
    callee: str         # Qualified name of callee
    location: Location
    edge_type: str = "call"  # call, override, implement, decorate
    call_count: int = 1
    is_direct: bool = True


@dataclass
class DependencyGraph:
    """Complete dependency graph for a codebase."""
    file_nodes: dict[str, FileNode] = field(default_factory=dict)
    import_edges: list[ImportEdge] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)

    # Indexes for fast lookup
    _symbol_index: dict[str, list[Symbol]] = field(default_factory=dict)
    _reference_index: dict[str, list[Reference]] = field(default_factory=dict)

    # Reverse dependency caches
    _dependents_cache: dict[str, set[str]] = field(default_factory=dict)
    _dependencies_cache: dict[str, set[str]] = field(default_factory=dict)

    def add_file_node(self, node: FileNode) -> None:
        self.file_nodes[node.path] = node
        for name, sym in node.symbols.items():
            key = sym.qualified_name or name
            self._symbol_index.setdefault(key, []).append(sym)
        for ref in node.references:
            self._reference_index.setdefault(ref.target_qualified_name, []).append(ref)
        self._invalidate_caches()

    def add_import_edge(self, edge: ImportEdge) -> None:
        self.import_edges.append(edge)

    def add_call_edge(self, edge: CallEdge) -> None:
        self.call_edges.append(edge)
        self._invalidate_caches()

    def get_symbol(self, qualified_name: str) -> Optional[Symbol]:
        syms = self._symbol_index.get(qualified_name, [])
        return syms[0] if syms else None

    def get_all_definitions(self, name: str) -> list[Symbol]:
        results = []
        for key, syms in self._symbol_index.items():
            if key.endswith(name) or key == name:
                results.extend(syms)
        return results

    def find_references(self, qualified_name: str) -> list[Reference]:
        return self._reference_index.get(qualified_name, [])

    def get_dependents(self, qualified_name: str) -> set[str]:
        """Get all symbols that depend on the given symbol."""
        if qualified_name in self._dependents_cache:
            return self._dependents_cache[qualified_name]
        deps: set[str] = set()
        for refs in self._reference_index.values():
            for ref in refs:
                if ref.target_qualified_name == qualified_name:
                    deps.add(ref.source.qualified_name)
        self._dependents_cache[qualified_name] = deps
        return deps

    def get_dependencies(self, qualified_name: str) -> set[str]:
        """Get all symbols the given symbol depends on."""
        if qualified_name in self._dependencies_cache:
            return self._dependencies_cache[qualified_name]
        deps: set[str] = set()
        for file_node in self.file_nodes.values():
            for ref in file_node.references:
                if ref.source.qualified_name == qualified_name:
                    deps.add(ref.target_qualified_name)
        self._dependencies_cache[qualified_name] = deps
        return deps

    def get_import_chain(self, file_path: str) -> list[list[str]]:
        """Get the full import chain for a file (for archaeology)."""
        chains: list[list[str]] = []
        visited: set[str] = set()

        def dfs(current: str, chain: list[str]) -> None:
            if current in visited:
                chains.append(chain + [current])
                return
            visited.add(current)
            is_leaf = True
            for edge in self.import_edges:
                if edge.importer == current:
                    is_leaf = False
                    dfs(edge.imported, chain + [current])
            if is_leaf:
                chains.append(chain + [current])
            visited.discard(current)

        dfs(file_path, [])
        return chains

    def get_impacted_files(self, qualified_name: str) -> set[str]:
        """Get all files that would be impacted by changing a symbol."""
        impacted: set[str] = set()
        refs = self.find_references(qualified_name)
        for ref in refs:
            impacted.add(ref.location.file)
        # Also add file defining the symbol
        sym = self.get_symbol(qualified_name)
        if sym:
            impacted.add(sym.location.file)
        return impacted

    def _invalidate_caches(self) -> None:
        self._dependents_cache.clear()
        self._dependencies_cache.clear()

    def transitive_dependents(self, qualified_name: str, max_depth: int = 100) -> set[str]:
        """Get all transitive dependents (full downstream impact chain)."""
        result: set[str] = set()
        frontier = {qualified_name}
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            new_frontier: set[str] = set()
            for name in frontier:
                deps = self.get_dependents(name)
                for dep in deps:
                    if dep not in result:
                        result.add(dep)
                        new_frontier.add(dep)
            frontier = new_frontier
        return result

    def transitive_dependencies(self, qualified_name: str, max_depth: int = 100) -> set[str]:
        """Get all transitive dependencies (full upstream chain)."""
        result: set[str] = set()
        frontier = {qualified_name}
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            new_frontier: set[str] = set()
            for name in frontier:
                deps = self.get_dependencies(name)
                for dep in deps:
                    if dep not in result:
                        result.add(dep)
                        new_frontier.add(dep)
            frontier = new_frontier
        return result


@dataclass
class RefactoringStep:
    """A single atomic step in a refactoring plan."""
    kind: RefactoringKind
    description: str
    file: str
    location: Location
    old_text: str = ""
    new_text: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    dependencies: list[str] = field(default_factory=list)
    validation: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.risk, str):
            self.risk = RiskLevel(self.risk)
        if isinstance(self.kind, str):
            self.kind = RefactoringKind(self.kind)


@dataclass
class ChangeSet:
    """A set of changes to be applied to files."""
    steps: list[RefactoringStep] = field(default_factory=list)
    total_files: int = 0
    total_symbols: int = 0
    estimated_risk: RiskLevel = RiskLevel.SAFE

    @property
    def file_changes(self) -> dict[str, list[RefactoringStep]]:
        grouped: dict[str, list[RefactoringStep]] = {}
        for step in self.steps:
            grouped.setdefault(step.file, []).append(step)
        return grouped


@dataclass
class RefactoringPlan:
    """A complete plan for a refactoring operation."""
    title: str
    description: str
    kind: RefactoringKind
    primary_symbol: str
    change_sets: list[ChangeSet]
    impacted_files: set[str]
    impacted_symbols: set[str]
    risk_assessment: str = ""
    rollback_plan: str = ""
    estimated_steps: int = 0

    def __post_init__(self):
        self.estimated_steps = sum(len(cs.steps) for cs in self.change_sets)
        self.impacted_files = set()
        self.impacted_symbols = set()
        for cs in self.change_sets:
            for step in cs.steps:
                self.impacted_files.add(step.file)
