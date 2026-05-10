"""Dependency graph engine with advanced query capabilities."""

from __future__ import annotations

from collections import deque
from typing import Optional

from .types import (
    Symbol,
    Reference,
    FileNode,
    ImportEdge,
    CallEdge,
    DependencyGraph,
    Location,
    SymbolKind,
)


class GraphEngine:
    """Engine for building and querying the dependency graph."""

    def __init__(self, graph: Optional[DependencyGraph] = None) -> None:
        self.graph = graph or DependencyGraph()
        self._adjacency: dict[str, set[str]] = {}
        self._reverse_adjacency: dict[str, set[str]] = {}
        self._built = False

    def build_indices(self) -> None:
        """Build adjacency indices for fast graph traversal."""
        if self._built:
            return

        # Build call-graph adjacency
        for edge in self.graph.call_edges:
            self._adjacency.setdefault(edge.caller, set()).add(edge.callee)
            self._reverse_adjacency.setdefault(edge.callee, set()).add(edge.caller)

        # Build import-graph adjacency (file-level)
        for edge in self.graph.import_edges:
            file_caller = f"@file:{edge.importer}"
            file_callee = f"@file:{edge.imported}"
            self._adjacency.setdefault(file_caller, set()).add(file_callee)
            self._reverse_adjacency.setdefault(file_callee, set()).add(file_caller)

        self._built = True

    # ── Graph traversal ──────────────────────────────────────────────

    def find_call_chain(
        self,
        start_symbol: str,
        end_symbol: str,
        max_depth: int = 50,
    ) -> list[list[str]]:
        """Find all call chains from start_symbol to end_symbol."""
        self.build_indices()
        all_paths: list[list[str]] = []

        def dfs(current: str, path: list[str], depth: int) -> None:
            if depth > max_depth or current not in self._adjacency:
                return
            path.append(current)
            if current == end_symbol:
                all_paths.append(list(path))
                path.pop()
                return
            for neighbor in self._adjacency.get(current, set()):
                if neighbor not in path:
                    dfs(neighbor, path, depth + 1)
            path.pop()

        dfs(start_symbol, [], 0)
        return all_paths

    def shortest_path(self, start: str, end: str) -> Optional[list[str]]:
        """BFS shortest path between two symbols."""
        self.build_indices()
        if start not in self._adjacency:
            return None
        queue = deque([(start, [start])])
        visited = {start}
        while queue:
            node, path = queue.popleft()
            if node == end:
                return path
            for neighbor in self._adjacency.get(node, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return None

    def downstream_impact(
        self,
        symbol: str,
        max_depth: int = 100,
    ) -> dict[str, list[str]]:
        """Calculate full downstream impact by level."""
        self.build_indices()
        impact: dict[int, set[str]] = {}
        visited: dict[str, int] = {}
        queue = deque([(symbol, 0)])
        visited[symbol] = 0

        while queue:
            node, depth = queue.popleft()
            if depth > max_depth:
                continue
            impact.setdefault(depth, set()).add(node)
            for neighbor in self._reverse_adjacency.get(node, set()):
                if neighbor not in visited or visited[neighbor] > depth + 1:
                    visited[neighbor] = depth + 1
                    queue.append((neighbor, depth + 1))

        result: dict[str, list[str]] = {}
        for d in sorted(impact.keys()):
            result[f"level_{d}"] = sorted(impact[d])
        return result

    def upstream_trace(
        self,
        symbol: str,
        max_depth: int = 100,
    ) -> dict[str, list[str]]:
        """Trace all upstream dependencies by level."""
        self.build_indices()
        trace: dict[int, set[str]] = {}
        visited: dict[str, int] = {}
        queue = deque([(symbol, 0)])
        visited[symbol] = 0

        while queue:
            node, depth = queue.popleft()
            if depth > max_depth:
                continue
            trace.setdefault(depth, set()).add(node)
            for neighbor in self._adjacency.get(node, set()):
                if neighbor not in visited or visited[neighbor] > depth + 1:
                    visited[neighbor] = depth + 1
                    queue.append((neighbor, depth + 1))

        result: dict[str, list[str]] = {}
        for d in sorted(trace.keys()):
            result[f"level_{d}"] = sorted(trace[d])
        return result

    # ── Centrality and importance ────────────────────────────────────

    def degree_centrality(self) -> dict[str, float]:
        """Compute in-degree + out-degree centrality for all symbols."""
        self.build_indices()
        centrality: dict[str, float] = {}
        all_nodes = set(self._adjacency.keys()) | set(self._reverse_adjacency.keys())
        max_deg = 0
        for node in all_nodes:
            indeg = len(self._reverse_adjacency.get(node, set()))
            outdeg = len(self._adjacency.get(node, set()))
            centrality[node] = indeg + outdeg
            max_deg = max(max_deg, centrality[node])
        if max_deg > 0:
            for node in centrality:
                centrality[node] /= max_deg
        return centrality

    def find_hub_symbols(self, top_n: int = 20) -> list[tuple[str, float]]:
        """Find the most connected (hub) symbols in the codebase."""
        centrality = self.degree_centrality()
        sorted_items = sorted(centrality.items(), key=lambda x: -x[1])
        return sorted_items[:top_n]

    # ── Cycle detection ──────────────────────────────────────────────

    def detect_cycles(self) -> list[list[str]]:
        """Detect all cycles in the dependency graph (circular deps)."""
        self.build_indices()
        cycles: list[list[str]] = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {node: WHITE for node in self._adjacency}
        stack: list[str] = []

        def dfs(node: str) -> None:
            color[node] = GRAY
            stack.append(node)
            for neighbor in self._adjacency.get(node, set()):
                if color.get(neighbor, WHITE) == GRAY:
                    # Found a cycle
                    cycle_start = stack.index(neighbor)
                    cycles.append(stack[cycle_start:] + [neighbor])
                elif color.get(neighbor, WHITE) == WHITE:
                    dfs(neighbor)
            stack.pop()
            color[node] = BLACK

        for node in list(self._adjacency.keys()):
            if color.get(node, WHITE) == WHITE:
                dfs(node)

        return cycles

    def detect_circular_imports(self) -> list[list[str]]:
        """Detect circular import chains between files."""
        file_adj: dict[str, set[str]] = {}
        for edge in self.graph.import_edges:
            file_adj.setdefault(edge.importer, set()).add(edge.imported)

        cycles: list[list[str]] = []
        visited: set[str] = set()
        stack: list[str] = []

        def dfs(node: str) -> None:
            if node in stack:
                cycle_start = stack.index(node)
                cycles.append(stack[cycle_start:] + [node])
                return
            if node in visited:
                return
            visited.add(node)
            stack.append(node)
            for neighbor in file_adj.get(node, set()):
                dfs(neighbor)
            stack.pop()

        for node in list(file_adj.keys()):
            if node not in visited:
                dfs(node)

        return cycles

    # ── File-level queries ───────────────────────────────────────────

    def file_dependency_order(self) -> list[str]:
        """Topological sort of files by dependency (build order)."""
        file_adj: dict[str, set[str]] = {}
        file_indeg: dict[str, int] = {}

        for edge in self.graph.import_edges:
            file_adj.setdefault(edge.importer, set()).add(edge.imported)
            file_indeg[edge.imported] = file_indeg.get(edge.imported, 0) + 1
            file_indeg.setdefault(edge.importer, 0)

        queue = deque([f for f, d in file_indeg.items() if d == 0])
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in file_adj.get(node, set()):
                file_indeg[neighbor] -= 1
                if file_indeg[neighbor] == 0:
                    queue.append(neighbor)

        return result + [f for f in file_indeg if file_indeg[f] > 0]

    def find_entry_points(self) -> list[str]:
        """Find files that are imported by others but import nothing themselves (roots)."""
        imported: set[str] = set()
        importers: set[str] = set()
        for edge in self.graph.import_edges:
            importers.add(edge.importer)
            imported.add(edge.imported)
        # Entry points: files that import others but are not imported
        return sorted(importers - imported)

    def find_leaf_files(self) -> list[str]:
        """Find files that are imported but don't import anything (leaf utils)."""
        imported: set[str] = set()
        importers: set[str] = set()
        for edge in self.graph.import_edges:
            importers.add(edge.importer)
            imported.add(edge.imported)
        return sorted(imported - importers)

    # ── Statistics ───────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get comprehensive graph statistics."""
        self.build_indices()
        all_symbol_nodes = {
            node for node in self._adjacency
            if not node.startswith("@file:")
        }
        return {
            "total_files": len(self.graph.file_nodes),
            "total_symbols": len(all_symbol_nodes),
            "total_edges": len(self.graph.call_edges),
            "total_imports": len(self.graph.import_edges),
            "avg_dependencies": (
                sum(len(v) for v in self._adjacency.values()) / max(len(all_symbol_nodes), 1)
            ),
            "cycles": len(self.detect_cycles()),
            "circular_imports": len(self.detect_circular_imports()),
            "entry_points": len(self.find_entry_points()),
            "leaf_files": len(self.find_leaf_files()),
        }
