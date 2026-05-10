"""Symbol resolver for cross-file reference resolution."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .types import Symbol, Reference, DependencyGraph, FileNode, SymbolKind


class SymbolResolver:
    """Resolves symbols and references across the entire dependency graph."""

    def __init__(self, graph: DependencyGraph) -> None:
        self.graph = graph
        self._name_index: dict[str, list[Symbol]] = defaultdict(list)
        self._build_index()

    def _build_index(self) -> None:
        """Build a name-based index for fuzzy symbol lookup."""
        for file_node in self.graph.file_nodes.values():
            for sym in file_node.symbols.values():
                # Index by simple name
                self._name_index[sym.name].append(sym)
                # Index by qualified name
                self._name_index[sym.qualified_name].append(sym)

    def resolve(self, name: str, context_file: Optional[str] = None) -> list[Symbol]:
        """Resolve a symbol name to all matching definitions."""
        results = self._name_index.get(name, [])
        if context_file:
            # Prefer symbols in the same file
            results.sort(key=lambda s: 0 if s.location.file == context_file else 1)
        return results

    def find_definition(self, name: str, file_path: Optional[str] = None) -> Optional[Symbol]:
        """Find the definition of a symbol, optionally scoped to a file."""
        candidates = self.resolve(name, file_path)
        return candidates[0] if candidates else None

    def find_all_usages(self, qualified_name: str) -> list[Reference]:
        """Find all usages/references to a symbol across the codebase."""
        return self.graph.find_references(qualified_name)

    def find_dead_code(self) -> list[Symbol]:
        """Find symbols that are defined but never referenced."""
        dead: list[Symbol] = []
        for file_node in self.graph.file_nodes.values():
            for sym in file_node.symbols.values():
                if sym.kind in (SymbolKind.IMPORT, SymbolKind.MODULE):
                    continue
                refs = self.graph.find_references(sym.qualified_name)
                if not refs:
                    dead.append(sym)
        return dead

    def find_duplicate_definitions(self) -> dict[str, list[Symbol]]:
        """Find symbols defined in multiple places."""
        dupes: dict[str, list[Symbol]] = defaultdict(list)
        all_syms: dict[str, Symbol] = {}
        for file_node in self.graph.file_nodes.values():
            for sym in file_node.symbols.values():
                key = sym.qualified_name
                if key in all_syms:
                    dupes[key].append(all_syms[key])
                    dupes[key].append(sym)
                else:
                    all_syms[key] = sym
        return dict(dupes)

    def find_unresolved_references(self) -> list[Reference]:
        """Find references to symbols that have no definition."""
        unresolved: list[Reference] = []
        for file_node in self.graph.file_nodes.values():
            for ref in file_node.references:
                if not self.find_definition(ref.target_qualified_name):
                    unresolved.append(ref)
        return unresolved

    def get_call_hierarchy(self, func_name: str) -> dict:
        """Build a call hierarchy tree for a function."""
        sym = self.find_definition(func_name)
        if not sym:
            return {"error": f"Symbol '{func_name}' not found", "symbol": func_name}

        def build_tree(name: str, depth: int = 0, max_depth: int = 10) -> dict:
            if depth > max_depth:
                return {"name": name, "children": [], "truncated": True}
            deps = self.graph.get_dependencies(name)
            children = []
            for dep in sorted(deps):
                children.append(build_tree(dep, depth + 1, max_depth))
            return {"name": name, "children": children}

        return {
            "symbol": func_name,
            "file": sym.location.file,
            "line": sym.location.line,
            "signature": sym.signature,
            "call_tree": build_tree(func_name),
        }

    def get_inheritance_chain(self, class_name: str) -> dict:
        """Trace the full inheritance chain for a class."""
        sym = self.find_definition(class_name)
        if not sym:
            return {"error": f"Class '{class_name}' not found"}

        chain = [class_name]
        bases = sym.metadata.get("bases", [])
        visited: set[str] = {class_name}

        while bases:
            base = bases[0].split(".")[-1]  # Take the class name part
            if base in visited:
                chain.append(f"{base} (circular)")
                break
            visited.add(base)
            chain.append(base)
            base_sym = self.find_definition(base)
            if base_sym:
                bases = base_sym.metadata.get("bases", [])
            else:
                break

        return {
            "class": class_name,
            "file": sym.location.file,
            "chain": " -> ".join(chain),
            "depth": len(chain) - 1,
        }

    def get_module_dependencies(self, file_path: str) -> dict:
        """Get all module-level dependencies for a file."""
        if file_path not in self.graph.file_nodes:
            return {"error": f"File '{file_path}' not in graph"}

        imports = self.graph.file_nodes[file_path].imports
        imported_by: list[str] = []
        for edge in self.graph.import_edges:
            if edge.imported == file_path:
                imported_by.append(edge.importer)

        return {
            "file": file_path,
            "imports": sorted(imports),
            "imported_by": sorted(set(imported_by)),
            "total_deps": len(imports),
            "total_dependents": len(imported_by),
        }
