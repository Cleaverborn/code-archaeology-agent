"""Extract refactoring operation — extract code block to function/class."""

from __future__ import annotations

import ast

from ..core.types import (
    RefactoringPlan, RefactoringStep, RefactoringKind,
    RiskLevel, Location, ChangeSet,
)


class ExtractOperation:
    """Extract a code block into a new function or method."""

    def __init__(self, graph, resolver) -> None:
        self.graph = graph
        self.resolver = resolver

    def plan(
        self, file_path: str, start_line: int, end_line: int,
        new_name: str, target_file: str = "",
    ) -> RefactoringPlan:
        """Plan extraction of a code block into a new function."""
        node = self.graph.file_nodes.get(file_path)
        if not node or not node.lines:
            return self._error_plan(f"File {file_path} not in graph", new_name)

        if start_line < 1 or end_line > len(node.lines) or start_line > end_line:
            return self._error_plan(
                f"Invalid line range {start_line}-{end_line} (file has {len(node.lines)} lines)",
                new_name,
            )

        extracted_lines = node.lines[start_line - 1:end_line]
        extracted_code = "\n".join(extracted_lines)

        # Analyze the block
        inputs, outputs = self._analyze_block(extracted_code)

        steps: list[RefactoringStep] = []
        target = target_file or file_path

        # Step 1: Create new function
        func_def = self._build_function(new_name, inputs, outputs, extracted_code)
        insert_at = len(node.lines) if target == file_path else self._find_insertion(target)

        steps.append(RefactoringStep(
            kind=RefactoringKind.EXTRACT_FUNCTION,
            description=f"Insert new function '{new_name}' in {target}",
            file=target,
            location=Location(file=target, line=insert_at, column=0),
            old_text="",
            new_text=func_def,
            risk=RiskLevel.LOW,
        ))

        # Step 2: Replace block with call
        ret_part = f"{outputs[0]} = " if outputs else ""
        call = f"{ret_part}{new_name}({', '.join(inputs)})"
        indent = self._detect_indent(node.lines[start_line - 1])
        call_line = indent + call

        steps.append(RefactoringStep(
            kind=RefactoringKind.EXTRACT_FUNCTION,
            description=f"Replace lines {start_line}-{end_line} with call",
            file=file_path,
            location=Location(file=file_path, line=start_line, column=0,
                             end_line=end_line, end_column=0),
            old_text=extracted_code,
            new_text=call_line,
            risk=RiskLevel.MEDIUM,
            dependencies=[],
            validation="Verify parameter count matches call site",
        ))

        return RefactoringPlan(
            title=f"Extract '{new_name}' from {file_path}:{start_line}-{end_line}",
            description=f"Extract {end_line - start_line + 1} lines to function '{new_name}'",
            kind=RefactoringKind.EXTRACT_FUNCTION,
            primary_symbol=new_name,
            change_sets=[ChangeSet(
                steps=steps,
                total_files=len({target, file_path}),
                total_symbols=1,
                estimated_risk=RiskLevel.MEDIUM,
            )],
            impacted_files={file_path, target},
            impacted_symbols=set(),
            risk_assessment=f"Extract with {len(inputs)} inputs, {len(outputs)} outputs",
            rollback_plan="Inline the function back",
        )

    def _analyze_block(self, code: str) -> tuple[list[str], list[str]]:
        """Analyze a code block to find inputs and outputs."""
        defined: set[str] = set()
        used: set[str] = set()
        try:
            tree = ast.parse(code)

            class Analyzer(ast.NodeVisitor):
                def visit_Name(self, node: ast.Name) -> None:
                    if isinstance(node.ctx, ast.Store):
                        defined.add(node.id)
                    elif isinstance(node.ctx, ast.Load):
                        used.add(node.id)

                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    defined.add(node.name)

            Analyzer().visit(tree)
        except SyntaxError:
            pass

        # Heuristic: filter out builtins and common names
        builtins_set = set(dir(__builtins__)) if hasattr(__builtins__, '__dict__') else {
            'print', 'len', 'range', 'int', 'str', 'list', 'dict', 'set', 'tuple',
            'bool', 'float', 'type', 'isinstance', 'hasattr', 'getattr', 'setattr',
            'open', 'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
            'min', 'max', 'sum', 'any', 'all', 'abs', 'round', 'id', 'input',
            'Exception', 'ValueError', 'TypeError', 'KeyError', 'True', 'False', 'None',
            'super', 'self', 'cls',
        }
        inputs = sorted(used - defined - builtins_set)
        outputs = sorted(defined)
        return inputs, outputs

    def _build_function(
        self, name: str, inputs: list[str], outputs: list[str], body: str,
    ) -> str:
        ret = f"\n    return {', '.join(outputs)}" if outputs else ""
        lines = body.strip().split("\n")
        indented = "\n".join(f"    {line}" for line in lines)
        return f"\ndef {name}({', '.join(inputs)}):\n{indented}{ret}\n"

    def _detect_indent(self, line: str) -> str:
        return line[:len(line) - len(line.lstrip())]

    def _find_insertion(self, file_path: str) -> int:
        node = self.graph.file_nodes.get(file_path)
        return len(node.lines) + 1 if node else 1

    def _error_plan(self, msg: str, name: str) -> RefactoringPlan:
        return RefactoringPlan(
            title=f"Extract '{name}'",
            description=f"ERROR: {msg}",
            kind=RefactoringKind.EXTRACT_FUNCTION,
            primary_symbol=name,
            change_sets=[],
            impacted_files=set(),
            impacted_symbols=set(),
            risk_assessment=f"ERROR: {msg}",
        )
