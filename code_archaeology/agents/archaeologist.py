"""
Archaeologist Agent — traces long dependency chains, reconstructs code
history, and maps the hidden structure of a codebase.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Optional

from .base import BaseAgent, AgentResult
from ..core.types import (
    Symbol, Reference, SymbolKind, RiskLevel, Location,
    FileNode, CallEdge,
)


class ArchaeologistAgent(BaseAgent):
    """Agent specialized in code archaeology — tracing chains and mapping structure."""

    name = "archaeologist"

    def execute(self, **kwargs) -> AgentResult:
        action = kwargs.get("action", "trace")
        start = time.time()

        actions = {
            "trace_downstream": self._trace_downstream,
            "trace_upstream": self._trace_upstream,
            "full_impact_chain": self._full_impact_chain,
            "trace_data_flow": self._trace_data_flow,
            "find_entry_points": self._find_entry_points,
            "map_call_graph": self._map_call_graph,
            "find_circular_deps": self._find_circular_deps,
            "trace_import_chain": self._trace_import_chain,
            "archaeology_report": self._archaeology_report,
            "find_pattern": self._find_pattern,
        }

        handler = actions.get(action)
        if handler is None:
            return self._err([f"Unknown action: {action}. Available: {list(actions.keys())}"])

        try:
            result_data = handler(**kwargs)
            return AgentResult(
                success=True,
                data=result_data,
                agent_name=self.name,
                execution_time_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return self._err([f"Archaeologist error: {e}"])

    def _trace_downstream(self, symbol: str, max_depth: int = 100, **kwargs) -> dict:
        """Trace all downstream dependents of a symbol (who depends on this?)."""
        direct = self.context.graph.get_dependents(symbol)
        transitive = self.context.graph.transitive_dependents(symbol, max_depth)
        impact_levels = self.context.engine.downstream_impact(symbol, max_depth)

        return {
            "symbol": symbol,
            "direct_dependents": sorted(direct),
            "direct_count": len(direct),
            "transitive_dependents": sorted(transitive),
            "transitive_count": len(transitive),
            "impact_by_level": impact_levels,
            "total_impact_depth": len(impact_levels),
            "impacted_files": sorted(self.context.graph.get_impacted_files(symbol)),
        }

    def _trace_upstream(self, symbol: str, max_depth: int = 100, **kwargs) -> dict:
        """Trace all upstream dependencies (what does this symbol depend on?)."""
        direct = self.context.graph.get_dependencies(symbol)
        transitive = self.context.graph.transitive_dependencies(symbol, max_depth)
        dep_levels = self.context.engine.upstream_trace(symbol, max_depth)

        return {
            "symbol": symbol,
            "direct_dependencies": sorted(direct),
            "direct_count": len(direct),
            "transitive_dependencies": sorted(transitive),
            "transitive_count": len(transitive),
            "dependency_levels": dep_levels,
            "total_dependency_depth": len(dep_levels),
        }

    def _full_impact_chain(self, symbol: str, **kwargs) -> dict:
        """Complete impact analysis: both upstream and downstream."""
        downstream = self._trace_downstream(symbol)
        upstream = self._trace_upstream(symbol)
        sym = self.context.graph.get_symbol(symbol)

        # Calculate risk
        transitive_down = len(downstream["transitive_dependents"])
        transitive_up = len(upstream["transitive_dependencies"])
        total_impact = transitive_down + transitive_up

        risk = RiskLevel.SAFE
        if total_impact > 100:
            risk = RiskLevel.CRITICAL
        elif total_impact > 50:
            risk = RiskLevel.HIGH
        elif total_impact > 20:
            risk = RiskLevel.MEDIUM
        elif total_impact > 5:
            risk = RiskLevel.LOW

        return {
            "symbol": symbol,
            "definition": {
                "file": sym.location.file if sym else "unknown",
                "line": sym.location.line if sym else 0,
                "kind": sym.kind.value if sym else "unknown",
                "signature": sym.signature if sym else None,
            },
            "downstream": downstream,
            "upstream": upstream,
            "total_impact": total_impact,
            "risk_assessment": {
                "level": risk.value,
                "reason": f"Affects {transitive_down} dependents, depends on {transitive_up} symbols",
            },
        }

    def _trace_data_flow(self, var_name: str, scope: str = "", **kwargs) -> dict:
        """Trace how data flows through the codebase for a given variable."""
        # Find all assignments to this variable
        assignments: list[dict] = []
        usages: list[dict] = []

        for file_node in self.context.graph.file_nodes.values():
            for sym in file_node.symbols.values():
                if sym.name == var_name:
                    if sym.kind in (SymbolKind.VARIABLE, SymbolKind.CONSTANT):
                        assignments.append({
                            "file": sym.location.file,
                            "line": sym.location.line,
                            "scope": sym.qualified_name,
                        })

            for ref in file_node.references:
                if var_name in ref.target_qualified_name:
                    usages.append({
                        "file": ref.location.file,
                        "line": ref.location.line,
                        "source": ref.source.qualified_name,
                        "type": ref.ref_type,
                    })

        return {
            "variable": var_name,
            "scope": scope or "global",
            "definitions": assignments,
            "definition_count": len(assignments),
            "usages": usages,
            "usage_count": len(usages),
            "flow_summary": f"Defined in {len(assignments)} places, used in {len(usages)} places",
        }

    def _find_entry_points(self, **kwargs) -> dict:
        """Find all entry points in the codebase."""
        entries = self.context.engine.find_entry_points()
        leaves = self.context.engine.find_leaf_files()

        return {
            "entry_points": entries,
            "entry_count": len(entries),
            "leaf_files": leaves,
            "leaf_count": len(leaves),
            "topological_order": self.context.engine.file_dependency_order()[:20],
        }

    def _map_call_graph(self, focal_symbol: str = "", max_depth: int = 5, **kwargs) -> dict:
        """Map the call graph around a focal point or for the whole codebase."""
        if focal_symbol:
            callers = self.context.graph.get_dependents(focal_symbol)
            callees = self.context.graph.get_dependencies(focal_symbol)
            short_paths: list[list[str]] = []

            # Find interesting paths
            for caller in list(callers)[:5]:
                for callee in list(callees)[:5]:
                    path = self.context.engine.shortest_path(caller, callee)
                    if path and len(path) > 2:
                        short_paths.append(path)

            return {
                "focal_symbol": focal_symbol,
                "direct_callers": sorted(callers),
                "direct_callees": sorted(callees),
                "interesting_paths": short_paths[:20],
            }
        else:
            hubs = self.context.engine.find_hub_symbols(50)
            return {
                "hub_symbols": [
                    {"symbol": sym, "centrality": round(cent, 3)}
                    for sym, cent in hubs
                ],
                "total_symbols_in_graph": len(self.context.graph._symbol_index),
            }

    def _find_circular_deps(self, **kwargs) -> dict:
        """Detect circular dependencies in the codebase."""
        cycles = self.context.engine.detect_cycles()
        circular_imports = self.context.engine.detect_circular_imports()

        return {
            "symbol_cycles": [c for c in cycles if len(c) > 2],
            "cycle_count": len(cycles),
            "circular_imports": circular_imports,
            "circular_import_count": len(circular_imports),
            "severity": "WARNING" if cycles else "OK",
        }

    def _trace_import_chain(self, file_path: str, **kwargs) -> dict:
        """Trace the full import chain starting from a file."""
        chains = self.context.graph.get_import_chain(file_path)
        imports = set()
        for chain in chains:
            imports.update(chain)
        imports.discard(file_path)

        return {
            "starting_file": file_path,
            "import_chains": chains[:30],  # Limit to 30 chains
            "total_chains": len(chains),
            "all_reachable_files": sorted(imports),
            "reachable_count": len(imports),
        }

    def _archaeology_report(self, symbol: str, **kwargs) -> dict:
        """Generate a comprehensive archaeology report for a symbol."""
        impact = self._full_impact_chain(symbol)
        entry = self._find_entry_points()
        call_map = self._map_call_graph(focal_symbol=symbol)

        # Find related patterns
        sym = self.context.graph.get_symbol(symbol)
        related_calls: list[str] = []
        if sym:
            # Find symbols often called together
            callers = self.context.graph.get_dependents(symbol)
            co_occurrence: dict[str, int] = defaultdict(int)
            for caller in callers:
                deps = self.context.graph.get_dependencies(caller)
                for dep in deps:
                    if dep != symbol and not dep.startswith("@"):
                        co_occurrence[dep] += 1
            related_calls = sorted(co_occurrence, key=co_occurrence.get, reverse=True)[:20]

        return {
            "report_title": f"Archaeology Report: {symbol}",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol_info": impact["definition"],
            "risk": impact["risk_assessment"],
            "impact_summary": {
                "direct_dependents": impact["downstream"]["direct_count"],
                "transitive_dependents": impact["downstream"]["transitive_count"],
                "direct_dependencies": impact["upstream"]["direct_count"],
                "transitive_dependencies": impact["upstream"]["transitive_count"],
                "impacted_files": len(impact["downstream"].get("impacted_files", [])),
            },
            "co_occurring_symbols": related_calls[:15],
            "hub_status": next(
                (h for h in call_map.get("hub_symbols", []) if h["symbol"] == symbol),
                None,
            ),
            "recommendation": self._generate_recommendation(impact),
        }

    def _find_pattern(self, pattern: str, **kwargs) -> dict:
        """Search for usage patterns across the codebase."""
        matches: list[dict] = []
        for file_node in self.context.graph.file_nodes.values():
            for sym in file_node.symbols.values():
                if pattern.lower() in sym.name.lower():
                    matches.append({
                        "name": sym.name,
                        "qualified_name": sym.qualified_name,
                        "kind": sym.kind.value,
                        "file": sym.location.file,
                        "line": sym.location.line,
                    })

        return {
            "pattern": pattern,
            "matches": matches,
            "match_count": len(matches),
            "by_kind": {
                kind.value: len([m for m in matches if m["kind"] == kind.value])
                for kind in SymbolKind
                if any(m["kind"] == kind.value for m in matches)
            },
        }

    def _generate_recommendation(self, impact: dict) -> str:
        """Generate a human-readable recommendation based on impact analysis."""
        down = impact["downstream"]["transitive_count"]
        up = impact["upstream"]["transitive_count"]

        if down == 0 and up == 0:
            return "This symbol appears to be isolated. Safe to rename or remove."
        elif down == 0:
            return f"This symbol depends on {up} other symbols but nothing depends on it. It may be a leaf utility or dead code."
        elif up == 0:
            return f"This symbol has {down} dependents. It appears to be a foundational/entry-point component. Changes here will have broad impact."
        else:
            return (
                f"This symbol sits in the middle of a dependency chain: "
                f"{down} things depend on it, and it depends on {up} things. "
                f"Changes require careful planning."
            )
