"""Rename refactoring operation — cross-file symbol renaming."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..core.types import RefactoringPlan, RefactoringStep, RefactoringKind, RiskLevel, Location, ChangeSet


class RenameOperation:
    """Cross-file rename refactoring with reference-aware string replacement."""

    def __init__(self, graph, resolver) -> None:
        self.graph = graph
        self.resolver = resolver

    def plan(self, symbol_name: str, new_name: str) -> RefactoringPlan:
        """Generate a rename plan covering all references."""
        sym = self.graph.get_symbol(symbol_name)
        refs = self.graph.find_references(symbol_name)
        transitives = self.graph.transitive_dependents(symbol_name)

        steps: list[RefactoringStep] = []

        # Rename definition
        if sym:
            steps.append(RefactoringStep(
                kind=RefactoringKind.RENAME,
                description=f"Rename definition '{symbol_name}' -> '{new_name}'",
                file=sym.location.file,
                location=sym.location,
                old_text=sym.name,
                new_text=new_name,
                risk=self._risk(len(refs)),
            ))

        # Rename all references
        for ref in refs:
            short_name = ref.target_qualified_name.split(".")[-1]
            steps.append(RefactoringStep(
                kind=RefactoringKind.RENAME,
                description=f"Update reference to '{symbol_name}' -> '{new_name}'",
                file=ref.location.file,
                location=ref.location,
                old_text=short_name,
                new_text=new_name,
                risk=RiskLevel.SAFE,
            ))

        impacted_files = self.graph.get_impacted_files(symbol_name)

        return RefactoringPlan(
            title=f"Rename: {symbol_name} -> {new_name}",
            description=f"Cross-file rename affecting {len(refs)} references in {len(impacted_files)} files",
            kind=RefactoringKind.RENAME,
            primary_symbol=symbol_name,
            change_sets=[ChangeSet(
                steps=steps,
                total_files=len(impacted_files),
                total_symbols=len(refs) + 1,
                estimated_risk=self._risk(len(refs)),
            )],
            impacted_files=impacted_files,
            impacted_symbols=transitives,
            risk_assessment=self._assessment(sym, len(refs), len(impacted_files)),
            rollback_plan="Reverse all rename operations from backup.",
        )

    def _risk(self, ref_count: int) -> RiskLevel:
        if ref_count == 0:
            return RiskLevel.SAFE
        if ref_count > 100:
            return RiskLevel.CRITICAL
        if ref_count > 50:
            return RiskLevel.HIGH
        if ref_count > 10:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _assessment(self, sym, ref_count: int, file_count: int) -> str:
        if sym and sym.visibility == "private":
            return f"LOW RISK: Private symbol, {ref_count} references in {file_count} files"
        return f"{'HIGH' if ref_count > 50 else 'MEDIUM' if ref_count > 10 else 'LOW'} RISK: {ref_count} references in {file_count} files"
