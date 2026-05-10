"""Change Signature refactoring — safely modify function signatures across all call sites."""

from __future__ import annotations

from ..core.types import (
    RefactoringPlan, RefactoringStep, RefactoringKind,
    RiskLevel, Location, ChangeSet, SymbolKind,
)


class SignatureOperation:
    """Change a function's signature across all definitions and call sites."""

    def __init__(self, graph, resolver) -> None:
        self.graph = graph
        self.resolver = resolver

    def plan(
        self,
        func_name: str,
        new_params: list[str],
        param_mapping: dict[str, str] | None = None,
    ) -> RefactoringPlan:
        """Plan a signature change.

        Args:
            func_name: Qualified name of the function
            new_params: New parameter list, e.g. ['self', 'name', 'age', 'email']
            param_mapping: Mapping of old param names to new param names
        """
        sym = self.graph.get_symbol(func_name)
        if not sym:
            return RefactoringPlan(
                title=f"Change signature: {func_name}",
                description="ERROR: Function not found",
                kind=RefactoringKind.CHANGE_SIGNATURE,
                primary_symbol=func_name,
                change_sets=[],
                impacted_files=set(),
                impacted_symbols=set(),
                risk_assessment="ERROR: Function not found in graph",
            )

        refs = self.graph.find_references(func_name)
        steps: list[RefactoringStep] = []
        impacted: set[str] = set()

        # 1. Change the function definition
        old_sig = sym.signature or f"def {sym.name}(...)"
        new_sig = self._build_signature(func_name.split(".")[-1], new_params)

        steps.append(RefactoringStep(
            kind=RefactoringKind.CHANGE_SIGNATURE,
            description=f"Change signature: {old_sig} -> {new_sig}",
            file=sym.location.file,
            location=sym.location,
            old_text=old_sig,
            new_text=new_sig,
            risk=self._risk(sym, len(refs)),
        ))
        impacted.add(sym.location.file)

        # 2. Update call sites
        call_refs = [r for r in refs if r.ref_type == "call"]
        for ref in call_refs:
            # Extract current call text from the file
            current_call = self._get_call_text(ref)
            new_call = self._adapt_call(current_call, new_params, param_mapping or {})

            steps.append(RefactoringStep(
                kind=RefactoringKind.CHANGE_SIGNATURE,
                description=f"Update call at {ref.location}",
                file=ref.location.file,
                location=ref.location,
                old_text=current_call,
                new_text=new_call,
                risk=RiskLevel.LOW if ref.ref_type == "call" else RiskLevel.MEDIUM,
                validation="Verify argument count and keyword names",
            ))
            impacted.add(ref.location.file)

        dep_tree = self.graph.get_dependents(func_name)

        return RefactoringPlan(
            title=f"Change signature: {func_name}",
            description=f"Update signature ({len(new_params)} params) "
                        f"and {len(call_refs)} call sites",
            kind=RefactoringKind.CHANGE_SIGNATURE,
            primary_symbol=func_name,
            change_sets=[ChangeSet(
                steps=steps,
                total_files=len(impacted),
                total_symbols=len(call_refs) + 1,
                estimated_risk=self._risk(sym, len(refs)),
            )],
            impacted_files=impacted,
            impacted_symbols=dep_tree,
            risk_assessment=(
                f"SAFE: no call sites" if len(call_refs) == 0
                else f"MEDIUM: {len(call_refs)} call sites need updating"
            ),
            rollback_plan="Restore original signature and call sites from backup",
        )

    def _build_signature(self, func_name: str, params: list[str]) -> str:
        return f"def {func_name}({', '.join(params)})"

    def _get_call_text(self, ref) -> str:
        """Get the text of a call site."""
        file_node = self.graph.file_nodes.get(ref.location.file)
        if not file_node or not file_node.lines:
            return ref.target_qualified_name + "(...)"
        line_idx = ref.location.line - 1
        if 0 <= line_idx < len(file_node.lines):
            return file_node.lines[line_idx].strip()
        return ref.target_qualified_name + "(...)"

    def _adapt_call(
        self, current_call: str, new_params: list[str], mapping: dict[str, str],
    ) -> str:
        """Adapt a call to match the new signature. Simple heuristic approach."""
        # Extract the argument part
        func_name = current_call.split("(")[0] if "(" in current_call else current_call
        arg_part = ""
        if "(" in current_call:
            arg_part = current_call[current_call.index("(") + 1:]
            if ")" in arg_part:
                arg_part = arg_part[:arg_part.rindex(")")]

        new_args = ", ".join(new_params) if new_params else ""
        return f"{func_name}({new_args})"

    def _risk(self, sym, ref_count: int) -> RiskLevel:
        if ref_count == 0:
            return RiskLevel.SAFE
        if sym.kind == SymbolKind.METHOD and sym.visibility == "private":
            return RiskLevel.LOW
        if ref_count > 50:
            return RiskLevel.HIGH
        if ref_count > 10:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
