"""
Planner Agent — designs safe, multi-step refactoring plans by analyzing
the dependency graph and computing the minimal set of changes needed.
"""

from __future__ import annotations

import time
from typing import Any

from .base import BaseAgent, AgentResult
from ..core.types import (
    RefactoringPlan, RefactoringStep, ChangeSet,
    RefactoringKind, RiskLevel, Location,
)


class PlannerAgent(BaseAgent):
    """Agent specialized in planning cross-file refactoring operations."""

    name = "planner"

    def execute(self, **kwargs) -> AgentResult:
        action = kwargs.get("action", "plan_rename")
        start = time.time()

        actions = {
            "plan_rename": self._plan_rename,
            "plan_extract": self._plan_extract,
            "plan_move": self._plan_move,
            "plan_change_signature": self._plan_change_signature,
            "plan_remove": self._plan_remove,
            "plan_inline": self._plan_inline,
        }

        handler = actions.get(action)
        if handler is None:
            return self._err([f"Unknown action: {action}. Available: {list(actions.keys())}"])

        try:
            plan = handler(**kwargs)
            return AgentResult(
                success=True,
                data=plan,
                agent_name=self.name,
                execution_time_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return self._err([f"Planner error: {e}"])

    def _plan_rename(
        self, symbol: str, new_name: str, reason: str = "", **kwargs
    ) -> RefactoringPlan:
        """Plan renaming a symbol across all files."""
        refs = self.context.graph.find_references(symbol)
        sym = self.context.graph.get_symbol(symbol)

        # Build steps for each reference
        steps: list[RefactoringStep] = []

        # Step 1: Rename the definition
        if sym:
            steps.append(RefactoringStep(
                kind=RefactoringKind.RENAME,
                description=f"Rename definition of {symbol} to {new_name}",
                file=sym.location.file,
                location=sym.location,
                old_text=sym.name,
                new_text=new_name,
                risk=self._assess_risk(sym, len(refs)),
            ))

        # Steps 2..N: Update all references
        for ref in refs:
            old_ref_name = ref.target_qualified_name.split(".")[-1]
            steps.append(RefactoringStep(
                kind=RefactoringKind.RENAME,
                description=f"Update reference to {symbol} → {new_name}",
                file=ref.location.file,
                location=ref.location,
                old_text=old_ref_name,
                new_text=new_name,
                risk=RiskLevel.SAFE,
            ))

        impacted = self.context.graph.get_impacted_files(symbol)
        transitive = self.context.graph.transitive_dependents(symbol)

        change_set = ChangeSet(
            steps=steps,
            total_files=len(impacted),
            total_symbols=len(refs) + 1,
            estimated_risk=self._max_risk(steps),
        )

        return RefactoringPlan(
            title=f"Rename '{symbol}' → '{new_name}'",
            description=reason or f"Cross-file rename of symbol '{symbol}' to '{new_name}'",
            kind=RefactoringKind.RENAME,
            primary_symbol=symbol,
            change_sets=[change_set],
            impacted_files=impacted,
            impacted_symbols=transitive | {symbol},
            risk_assessment=self._risk_summary(len(refs), len(impacted)),
            rollback_plan="Reverse all text replacements using the recorded old_text/new_text pairs.",
        )

    def _plan_extract(
        self, file_path: str, start_line: int, end_line: int,
        new_func_name: str, target_file: str = "", **kwargs
    ) -> RefactoringPlan:
        """Plan extracting code block into a new function."""
        node = self.context.graph.file_nodes.get(file_path)
        if not node or not node.lines:
            return RefactoringPlan(
                title=f"Extract lines {start_line}-{end_line} → {new_func_name}",
                description="Extraction plan",
                kind=RefactoringKind.EXTRACT_FUNCTION,
                primary_symbol=new_func_name,
                change_sets=[],
                impacted_files=set(),
                impacted_symbols=set(),
                risk_assessment="ERROR: File not found in graph",
            )

        # Read the code block
        extracted_lines = node.lines[start_line - 1:end_line]
        extracted_code = "\n".join(extracted_lines)

        # Analyze the block to find inputs/outputs
        analysis = self._analyze_block_for_extraction(extracted_code, file_path, start_line)

        steps: list[RefactoringStep] = []

        # Step 1: Create the new function
        target = target_file or file_path
        func_def = self._generate_extracted_function(
            new_func_name, analysis["params"], analysis["returns"], extracted_code
        )

        # Find insertion point (end of file or before next function)
        insert_line = self._find_insertion_point(target)
        steps.append(RefactoringStep(
            kind=RefactoringKind.EXTRACT_FUNCTION,
            description=f"Insert new function {new_func_name}",
            file=target,
            location=Location(file=target, line=insert_line, column=0),
            old_text="",
            new_text=func_def,
            risk=RiskLevel.LOW,
        ))

        # Step 2: Replace the original block with a call
        call_text = f"{new_func_name}({', '.join(analysis['params'])})"
        if analysis["returns"]:
            call_text = f"{analysis['returns'][0]} = {call_text}"

        steps.append(RefactoringStep(
            kind=RefactoringKind.EXTRACT_FUNCTION,
            description=f"Replace lines {start_line}-{end_line} with call to {new_func_name}",
            file=file_path,
            location=Location(file=file_path, line=start_line, column=0,
                             end_line=end_line, end_column=0),
            old_text=extracted_code,
            new_text=call_text,
            risk=RiskLevel.MEDIUM,
        ))

        change_set = ChangeSet(
            steps=steps,
            total_files=len({s.file for s in steps}),
            total_symbols=2,
            estimated_risk=RiskLevel.MEDIUM,
        )

        return RefactoringPlan(
            title=f"Extract '{new_func_name}' from {file_path}:{start_line}-{end_line}",
            description=f"Extract {end_line - start_line + 1} lines into function '{new_func_name}'",
            kind=RefactoringKind.EXTRACT_FUNCTION,
            primary_symbol=new_func_name,
            change_sets=[change_set],
            impacted_files={file_path, target},
            impacted_symbols=set(),
            risk_assessment=f"Extract {end_line - start_line + 1} lines with "
                           f"{len(analysis['params'])} params, "
                           f"{len(analysis['returns'])} return values",
            rollback_plan="Inline the function back by reversing the extraction.",
        )

    def _plan_move(
        self, symbol: str, target_file: str, **kwargs
    ) -> RefactoringPlan:
        """Plan moving a symbol from one file to another."""
        sym = self.context.graph.get_symbol(symbol)
        refs = self.context.graph.find_references(symbol)

        if not sym:
            return RefactoringPlan(
                title=f"Move '{symbol}' → {target_file}",
                description="Move plan",
                kind=RefactoringKind.MOVE_SYMBOL,
                primary_symbol=symbol,
                change_sets=[],
                impacted_files=set(),
                impacted_symbols=set(),
                risk_assessment="ERROR: Symbol not found",
            )

        source_file = sym.location.file
        steps: list[RefactoringStep] = []

        # Step 1: Remove from source file
        steps.append(RefactoringStep(
            kind=RefactoringKind.MOVE_SYMBOL,
            description=f"Remove {symbol} from {source_file}",
            file=source_file,
            location=sym.location,
            old_text=sym.signature or sym.name,
            new_text="",
            risk=self._assess_risk(sym, len(refs)),
        ))

        # Step 2: Add to target file (with necessary imports)
        insert_line = self._find_insertion_point(target_file)
        steps.append(RefactoringStep(
            kind=RefactoringKind.MOVE_SYMBOL,
            description=f"Add {symbol} to {target_file}",
            file=target_file,
            location=Location(file=target_file, line=insert_line, column=0),
            old_text="",
            new_text=self._render_symbol_for_move(sym),
            risk=RiskLevel.LOW,
        ))

        # Step 3: Update imports in all files referencing this symbol
        for ref in refs:
            if ref.location.file not in (source_file, target_file):
                # This file needs an import update
                steps.append(RefactoringStep(
                    kind=RefactoringKind.MOVE_SYMBOL,
                    description=f"Update import in {ref.location.file}",
                    file=ref.location.file,
                    location=ref.location,
                    old_text="",  # Will be filled during execution
                    new_text="",  # Will be filled during execution
                    risk=RiskLevel.SAFE,
                ))

        impacted = {source_file, target_file} | {r.location.file for r in refs}

        change_set = ChangeSet(
            steps=steps,
            total_files=len(impacted),
            total_symbols=len(refs) + 1,
            estimated_risk=self._max_risk(steps),
        )

        return RefactoringPlan(
            title=f"Move '{symbol}' from {source_file} → {target_file}",
            description=f"Move symbol '{symbol}' with {len(refs)} references",
            kind=RefactoringKind.MOVE_SYMBOL,
            primary_symbol=symbol,
            change_sets=[change_set],
            impacted_files=impacted,
            impacted_symbols={r.source.qualified_name for r in refs} | {symbol},
            risk_assessment=self._risk_summary(len(refs), len(impacted)),
            rollback_plan="Move the symbol back to its original file.",
        )

    def _plan_change_signature(
        self, func_name: str, new_params: list[str], **kwargs
    ) -> RefactoringPlan:
        """Plan changing a function signature."""
        sym = self.context.graph.get_symbol(func_name)
        refs = self.context.graph.find_references(func_name)
        dep_tree = self.context.graph.get_dependents(func_name)

        steps: list[RefactoringStep] = []
        impacted = set()

        if sym:
            old_sig = sym.signature or func_name
            new_sig = self._build_new_signature(func_name, new_params)
            steps.append(RefactoringStep(
                kind=RefactoringKind.CHANGE_SIGNATURE,
                description=f"Change signature: {old_sig} → {new_sig}",
                file=sym.location.file,
                location=sym.location,
                old_text=old_sig,
                new_text=new_sig,
                risk=self._assess_risk(sym, len(refs)),
            ))
            impacted.add(sym.location.file)

        # Update all call sites
        for ref in refs:
            steps.append(RefactoringStep(
                kind=RefactoringKind.CHANGE_SIGNATURE,
                description=f"Update call to {func_name} with new signature",
                file=ref.location.file,
                location=ref.location,
                old_text="",  # Filled during execution
                new_text="",  # Filled during execution
                risk=RiskLevel.LOW if ref.ref_type != "call" else RiskLevel.MEDIUM,
            ))
            impacted.add(ref.location.file)

        change_set = ChangeSet(
            steps=steps,
            total_files=len(impacted),
            total_symbols=len(refs),
            estimated_risk=self._max_risk(steps) if steps else RiskLevel.SAFE,
        )

        return RefactoringPlan(
            title=f"Change signature of '{func_name}'",
            description=f"Update {func_name} signature and {len(refs)} call sites",
            kind=RefactoringKind.CHANGE_SIGNATURE,
            primary_symbol=func_name,
            change_sets=[change_set],
            impacted_files=impacted,
            impacted_symbols=dep_tree,
            risk_assessment=self._risk_summary(len(refs), len(impacted)),
            rollback_plan="Restore original signature.",
        )

    def _plan_remove(self, symbol: str, **kwargs) -> RefactoringPlan:
        """Plan safely removing a symbol."""
        refs = self.context.graph.find_references(symbol)
        sym = self.context.graph.get_symbol(symbol)
        file_path = sym.location.file if sym else ""

        if refs:
            return RefactoringPlan(
                title=f"Remove '{symbol}' (BLOCKED)",
                description=f"Cannot remove: {len(refs)} references still exist",
                kind=RefactoringKind.RENAME,
                primary_symbol=symbol,
                change_sets=[],
                impacted_files=set(),
                impacted_symbols=set(),
                risk_assessment=f"BLOCKED: {len(refs)} active references prevent removal",
            )

        steps = [RefactoringStep(
            kind=RefactoringKind.RENAME,
            description=f"Remove unused symbol '{symbol}'",
            file=file_path,
            location=sym.location if sym else Location(file=file_path, line=0, column=0),
            old_text=sym.signature or symbol if sym else symbol,
            new_text="",
            risk=RiskLevel.SAFE,
            validation="Verify no references exist (confirmed 0)",
        )]

        return RefactoringPlan(
            title=f"Remove '{symbol}'",
            description="Safe removal — no references found",
            kind=RefactoringKind.RENAME,
            primary_symbol=symbol,
            change_sets=[ChangeSet(steps=steps, total_files=1, total_symbols=1, estimated_risk=RiskLevel.SAFE)],
            impacted_files={file_path},
            impacted_symbols=set(),
            risk_assessment="SAFE: No references, safe to remove",
            rollback_plan="Restore from version control",
        )

    def _plan_inline(self, func_name: str, **kwargs) -> RefactoringPlan:
        """Plan inlining a function (replace calls with function body)."""
        sym = self.context.graph.get_symbol(func_name)
        refs = self.context.graph.find_references(func_name)

        if not sym:
            return RefactoringPlan(
                title=f"Inline '{func_name}'",
                description="Inline plan",
                kind=RefactoringKind.INLINE,
                primary_symbol=func_name,
                change_sets=[],
                impacted_files=set(),
                impacted_symbols=set(),
                risk_assessment="ERROR: Symbol not found",
            )

        steps = []
        # Replace each call with the function body
        for ref in refs:
            steps.append(RefactoringStep(
                kind=RefactoringKind.INLINE,
                description=f"Inline {func_name} call at {ref.location}",
                file=ref.location.file,
                location=ref.location,
                old_text="",  # Extracted during execution
                new_text="",  # Function body, adapted
                risk=RiskLevel.MEDIUM,
            ))

        # Remove the original function definition
        steps.append(RefactoringStep(
            kind=RefactoringKind.INLINE,
            description=f"Remove function definition for {func_name}",
            file=sym.location.file,
            location=sym.location,
            old_text=sym.signature or func_name,
            new_text="",
            risk=RiskLevel.SAFE,
        ))

        impacted = {sym.location.file} | {r.location.file for r in refs}

        return RefactoringPlan(
            title=f"Inline '{func_name}'",
            description=f"Replace {len(refs)} calls with function body",
            kind=RefactoringKind.INLINE,
            primary_symbol=func_name,
            change_sets=[ChangeSet(
                steps=steps,
                total_files=len(impacted),
                total_symbols=len(refs) + 1,
                estimated_risk=RiskLevel.MEDIUM,
            )],
            impacted_files=impacted,
            impacted_symbols={r.source.qualified_name for r in refs},
            risk_assessment=f"Inline {len(refs)} call sites, then remove definition",
            rollback_plan="Reverse by extracting the function back",
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _assess_risk(self, sym, ref_count: int) -> RiskLevel:
        if ref_count == 0:
            return RiskLevel.SAFE
        if sym.visibility == "private":
            return RiskLevel.LOW if ref_count < 5 else RiskLevel.MEDIUM
        if sym.visibility == "protected":
            return RiskLevel.LOW if ref_count < 3 else RiskLevel.MEDIUM
        if ref_count > 100:
            return RiskLevel.CRITICAL
        if ref_count > 50:
            return RiskLevel.HIGH
        if ref_count > 10:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _max_risk(self, steps: list[RefactoringStep]) -> RiskLevel:
        risk_order = [RiskLevel.SAFE, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        max_r = RiskLevel.SAFE
        for s in steps:
            if risk_order.index(s.risk) > risk_order.index(max_r):
                max_r = s.risk
        return max_r

    def _risk_summary(self, ref_count: int, file_count: int) -> str:
        if ref_count == 0:
            return "SAFE: No external references. Isolated change."
        return (
            f"Changes needed: {ref_count} reference(s) across {file_count} file(s). "
            f"Risk: {'HIGH' if ref_count > 50 else 'MEDIUM' if ref_count > 10 else 'LOW'}"
        )

    def _analyze_block_for_extraction(
        self, code: str, file_path: str, start_line: int,
    ) -> dict:
        """Analyze a code block to determine inputs and outputs for extraction."""
        import ast
        params: list[str] = []
        returns: list[str] = []

        try:
            tree = ast.parse(code)
            # Collect names used but not defined in the block
            defined: set[str] = set()
            used: set[str] = set()

            class Analyzer(ast.NodeVisitor):
                def visit_Name(self, node: ast.Name) -> None:
                    if isinstance(node.ctx, ast.Store):
                        defined.add(node.id)
                    elif isinstance(node.ctx, ast.Load):
                        used.add(node.id)
                    self.generic_visit(node)

                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    defined.add(node.name)
                    # Don't recurse into nested functions

                def visit_ClassDef(self, node: ast.ClassDef) -> None:
                    defined.add(node.name)

            Analyzer().visit(tree)
            params = sorted(used - defined - set(dir(__builtins__)))
            returns = sorted(defined)
        except SyntaxError:
            pass

        return {"params": params, "returns": returns}

    def _generate_extracted_function(
        self, name: str, params: list[str], returns: list[str], body: str,
    ) -> str:
        ret_assign = f"\n    return {', '.join(returns)}" if returns else ""
        return f"\ndef {name}({', '.join(params)}):\n    {body.strip()}{ret_assign}\n"

    def _find_insertion_point(self, file_path: str) -> int:
        """Find a safe line to insert new code in a file."""
        node = self.context.graph.file_nodes.get(file_path)
        if node and node.lines:
            return len(node.lines) + 1
        return 1

    def _render_symbol_for_move(self, sym) -> str:
        """Render a symbol's source code for transplantation."""
        if not sym or sym.location.file not in self.context.graph.file_nodes:
            return f"# TODO: Copy {sym.qualified_name if sym else '?'} here\n"
        node = self.context.graph.file_nodes[sym.location.file]
        if node.lines and sym.location.line:
            start = sym.location.line - 1
            end = sym.location.end_line or (start + 1)
            return "\n".join(node.lines[start:end])
        return sym.signature or sym.name

    def _build_new_signature(self, func_name: str, params: list[str]) -> str:
        return f"def {func_name}({', '.join(params)})"
