"""Move refactoring operation — relocate symbols between files."""

from __future__ import annotations

import os

from ..core.types import (
    RefactoringPlan, RefactoringStep, RefactoringKind,
    RiskLevel, Location, ChangeSet,
)


class MoveOperation:
    """Move a symbol (function, class) from one file to another."""

    def __init__(self, graph, resolver) -> None:
        self.graph = graph
        self.resolver = resolver

    def plan(self, symbol_name: str, target_file: str) -> RefactoringPlan:
        """Plan moving a symbol to a new file."""
        sym = self.graph.get_symbol(symbol_name)
        if not sym:
            return RefactoringPlan(
                title=f"Move '{symbol_name}' -> {target_file}",
                description="ERROR: Symbol not found",
                kind=RefactoringKind.MOVE_SYMBOL,
                primary_symbol=symbol_name,
                change_sets=[],
                impacted_files=set(),
                impacted_symbols=set(),
                risk_assessment="ERROR: Symbol not found in graph",
            )

        source_file = sym.location.file
        refs = self.graph.find_references(symbol_name)
        steps: list[RefactoringStep] = []

        # 1. Extract source from origin file
        source_code = self._extract_source(sym)
        steps.append(RefactoringStep(
            kind=RefactoringKind.MOVE_SYMBOL,
            description=f"Remove '{symbol_name}' from {source_file}",
            file=source_file,
            location=Location(
                file=source_file, line=sym.location.line, column=0,
                end_line=sym.location.end_line, end_column=0,
            ),
            old_text=source_code,
            new_text="",
            risk=self._move_risk(sym, len(refs)),
        ))

        # 2. Insert into target file
        insert_line = self._find_insertion_point(target_file)
        new_source = self._add_imports_if_needed(target_file, source_file, source_code)

        steps.append(RefactoringStep(
            kind=RefactoringKind.MOVE_SYMBOL,
            description=f"Insert '{symbol_name}' into {target_file}",
            file=target_file,
            location=Location(file=target_file, line=insert_line, column=0),
            old_text="",
            new_text=f"\n{new_source}\n",
            risk=RiskLevel.LOW,
        ))

        # 3. Update imports in all referencing files
        for ref in refs:
            ref_file = ref.location.file
            if ref_file in (source_file, target_file):
                continue
            # For now, flag that import needs updating
            steps.append(RefactoringStep(
                kind=RefactoringKind.MOVE_SYMBOL,
                description=f"Update import in {ref_file} to point to new location",
                file=ref_file,
                location=Location(file=ref_file, line=1, column=0),
                old_text="",  # Will need manual or AST-based import update
                new_text="",
                risk=RiskLevel.LOW,
                validation=f"Ensure import of '{symbol_name}' references {target_file}",
            ))

        all_impacted = {source_file, target_file} | {r.location.file for r in refs}

        return RefactoringPlan(
            title=f"Move '{symbol_name}': {source_file} -> {target_file}",
            description=f"Move symbol with {len(refs)} references. "
                        f"New import needed in {len(all_impacted) - 2} external files.",
            kind=RefactoringKind.MOVE_SYMBOL,
            primary_symbol=symbol_name,
            change_sets=[ChangeSet(
                steps=steps,
                total_files=len(all_impacted),
                total_symbols=len(refs) + 1,
                estimated_risk=self._move_risk(sym, len(refs)),
            )],
            impacted_files=all_impacted,
            impacted_symbols={r.source.qualified_name for r in refs} | {symbol_name},
            risk_assessment=(
                f"SAFE: no references" if len(refs) == 0
                else f"MEDIUM: {len(refs)} external references need import updates"
            ),
            rollback_plan=f"Move '{symbol_name}' back from {target_file} to {source_file}",
        )

    def _extract_source(self, sym) -> str:
        file_node = self.graph.file_nodes.get(sym.location.file)
        if not file_node or not file_node.lines:
            return f"# {sym.qualified_name} definition (source not available)"
        start = sym.location.line - 1
        end = sym.location.end_line or (start + 1)
        return "\n".join(file_node.lines[start:end])

    def _find_insertion_point(self, file_path: str) -> int:
        if file_path in self.graph.file_nodes:
            node = self.graph.file_nodes[file_path]
            return len(node.lines) + 1 if node.lines else 1
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return len(f.readlines()) + 1
        except Exception:
            return 1

    def _add_imports_if_needed(self, target_file: str, source_file: str, code: str) -> str:
        """Check if target file needs imports from source file's dependencies."""
        # Find imports in source file that the symbol uses
        source_imports: set[str] = set()
        if source_file in self.graph.file_nodes:
            source_imports = self.graph.file_nodes[source_file].imports

        # Check which imports the target already has
        target_imports: set[str] = set()
        if target_file in self.graph.file_nodes:
            target_imports = self.graph.file_nodes[target_file].imports

        missing = source_imports - target_imports
        if missing:
            import_block = "\n".join(f"import {m}" for m in sorted(missing))
            code = f"{import_block}\n{code}"

        return code

    def _move_risk(self, sym, ref_count: int) -> RiskLevel:
        if ref_count == 0:
            return RiskLevel.SAFE
        if ref_count > 50:
            return RiskLevel.HIGH
        if ref_count > 20:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
