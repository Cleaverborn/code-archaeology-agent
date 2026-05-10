"""Python language parser using the built-in ast module."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Optional

from .base import LanguageParser, ParseResult
from ..core.types import Symbol, Reference, SymbolKind, Location, FileNode


class PythonParser(LanguageParser):
    """Parse Python source files into symbols and references."""

    language = "python"
    extensions = [".py", ".pyi", ".pyx"]

    def parse_file(self, file_path: str) -> ParseResult:
        start = time.time()
        try:
            source = Path(file_path).read_text(encoding="utf-8")
            return self.parse_source(source, file_path, start)
        except Exception as e:
            return ParseResult(
                file_node=self._make_file_node(file_path),
                errors=[f"Failed to read {file_path}: {e}"],
            )

    def parse_source(self, source: str, file_path: str = "<string>", start_time: float = 0.0) -> ParseResult:
        if not start_time:
            start_time = time.time()
        file_node = self._make_file_node(file_path)
        file_node.lines = source.splitlines()
        errors: list[str] = []
        warnings: list[str] = []

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as e:
            errors.append(f"Syntax error in {file_path}: {e}")
            return ParseResult(file_node=file_node, errors=errors)

        visitor = _PythonVisitor(file_node, file_path)
        try:
            visitor.visit(tree)
        except Exception as e:
            errors.append(f"AST visit error in {file_path}: {e}")

        parse_time = (time.time() - start_time) * 1000
        return ParseResult(
            file_node=file_node,
            errors=errors + visitor.errors,
            warnings=warnings + visitor.warnings,
            parse_time_ms=parse_time,
        )


class _PythonVisitor(ast.NodeVisitor):
    """AST visitor that extracts symbols and references."""

    def __init__(self, file_node: FileNode, file_path: str) -> None:
        self.file_node = file_node
        self.file_path = file_path
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._scope_stack: list[str] = []       # Track class/function scope
        self._current_class: Optional[str] = None
        self._current_function: Optional[str] = None
        self._import_map: dict[str, str] = {}    # local_name -> qualified_module

    def _loc(self, node: ast.AST) -> Location:
        return Location(
            file=self.file_path,
            line=getattr(node, "lineno", 0),
            column=getattr(node, "col_offset", 0),
            end_line=getattr(node, "end_lineno", 0) or 0,
            end_column=getattr(node, "end_col_offset", 0) or 0,
        )

    def _qualified_name(self, name: str) -> str:
        parts = self._scope_stack + [name]
        return ".".join(parts)

    def _add_symbol(self, name: str, kind: SymbolKind, node: ast.AST, **kwargs) -> Symbol:
        sym = Symbol(
            name=name,
            kind=kind,
            location=self._loc(node),
            qualified_name=self._qualified_name(name),
            **kwargs,
        )
        self.file_node.symbols[sym.qualified_name] = sym
        return sym

    def _add_ref(self, source: Symbol, target: str, node: ast.AST, ref_type: str = "call") -> Reference:
        # Resolve imports
        resolved = target
        if target in self._import_map:
            resolved = self._import_map[target]
        ref = Reference(
            source=source,
            target_qualified_name=resolved,
            location=self._loc(node),
            ref_type=ref_type,
        )
        self.file_node.references.append(ref)
        return ref

    # ── Top-level ────────────────────────────────────────────────────

    def visit_Module(self, node: ast.Module) -> None:
        self.generic_visit(node)

    # ── Imports ──────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name
            local = alias.asname or mod.split(".")[0]
            self.file_node.imports.add(mod)
            self._import_map[local] = mod
            sym = self._add_symbol(
                local, SymbolKind.IMPORT, node,
                qualified_name=mod,
                metadata={"module": mod, "alias": alias.asname},
            )
            # Reference tracking: this module now references the imported module
            self.file_node.references.append(Reference(
                source=sym,
                target_qualified_name=mod,
                location=self._loc(node),
                ref_type="import",
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            full = f"{module}.{alias.name}" if module else alias.name
            local = alias.asname or alias.name
            self.file_node.imports.add(full)
            self._import_map[local] = full
            sym = self._add_symbol(
                local, SymbolKind.IMPORT, node,
                qualified_name=full,
                metadata={"module": module, "name": alias.name, "alias": alias.asname},
            )
            self.file_node.references.append(Reference(
                source=sym,
                target_qualified_name=full,
                location=self._loc(node),
                ref_type="import",
            ))

    # ── Classes ──────────────────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self._scope_stack.append(node.name)

        bases = [ast.unparse(b) for b in node.bases] if node.bases else []
        doc = ast.get_docstring(node)

        sym = self._add_symbol(
            node.name, SymbolKind.CLASS, node,
            docstring=doc,
            metadata={"bases": bases, "decorators": [ast.unparse(d) for d in node.decorator_list]},
        )

        # Track base class references
        for base in node.bases:
            base_name = ast.unparse(base)
            self._add_ref(sym, base_name, base, ref_type="inheritance")

        # Visit body
        for child in node.body:
            self.visit(child)

        self._scope_stack.pop()
        self._current_class = old_class

    # ── Functions / Methods ──────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return self._visit_function(node, is_async=True)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        old_func = self._current_function
        self._current_function = node.name
        self._scope_stack.append(node.name)

        kind = SymbolKind.METHOD if self._current_class else SymbolKind.FUNCTION
        doc = ast.get_docstring(node)

        sym = self._add_symbol(
            node.name, kind, node,
            docstring=doc,
            signature=self._get_signature(node),
            visibility=self._get_visibility(node.name),
            metadata={
                "is_async": is_async,
                "decorators": [ast.unparse(d) for d in node.decorator_list],
                "args": [a.arg for a in node.args.args],
                "returns": ast.unparse(node.returns) if node.returns else None,
            },
        )

        # Track decorator references
        for decorator in node.decorator_list:
            dec_name = ast.unparse(decorator)
            self._add_ref(sym, dec_name, decorator, ref_type="decorator")

        # Track return type annotation reference
        if node.returns:
            ret_str = ast.unparse(node.returns)
            self._add_ref(sym, ret_str, node.returns, ref_type="type_annotation")

        # Track parameter type annotations
        for arg in node.args.args:
            if arg.annotation:
                ann_str = ast.unparse(arg.annotation)
                self._add_ref(sym, ann_str, arg.annotation, ref_type="type_annotation")

        # Visit body to find internal calls
        for child in node.body:
            self.visit(child)

        self._scope_stack.pop()
        self._current_function = old_func

    # ── Calls ────────────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        if self._current_function is not None:
            current_sym = self._add_symbol(
                self._current_function,
                SymbolKind.METHOD if self._current_class else SymbolKind.FUNCTION,
                node,
                qualified_name=self._qualified_name(self._current_function),
            )
            # Get the callee name
            callee = self._get_callee_name(node.func)
            if callee:
                self._add_ref(current_sym, callee, node.func, ref_type="call")
        self.generic_visit(node)

    # ── Variable assignments ─────────────────────────────────────────

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                kind = SymbolKind.VARIABLE
                name = target.id
                if name.isupper():
                    kind = SymbolKind.CONSTANT
                self._add_symbol(name, kind, target, qualified_name=self._qualified_name(name))
            elif isinstance(target, ast.Attribute):
                # self.x = ...  (class attribute)
                if isinstance(target.value, ast.Name) and target.value.id == "self":
                    self._add_symbol(
                        target.attr, SymbolKind.PROPERTY, target,
                        parent=self._current_class,
                        qualified_name=f"{self._current_class}.{target.attr}" if self._current_class else target.attr,
                    )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            kind = SymbolKind.VARIABLE
            if node.target.id.isupper():
                kind = SymbolKind.CONSTANT
            sym = self._add_symbol(
                node.target.id, kind, node,
                qualified_name=self._qualified_name(node.target.id),
            )
            if node.annotation:
                ann_str = ast.unparse(node.annotation)
                self._add_ref(sym, ann_str, node.annotation, ref_type="type_annotation")
        self.generic_visit(node)

    # ── Attribute access ─────────────────────────────────────────────

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._current_function and isinstance(node.value, ast.Name):
            # Track attribute access as a reference
            full = f"{node.value.id}.{node.attr}"
            current_sym = self._add_symbol(
                self._current_function,
                SymbolKind.FUNCTION, node,
                qualified_name=self._qualified_name(self._current_function),
            )
            self._add_ref(current_sym, full, node, ref_type="access")
        self.generic_visit(node)

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_signature(self, node: ast.FunctionDef) -> str:
        """Reconstruct function signature."""
        args = []
        for arg in node.args.args:
            a = arg.arg
            if arg.annotation:
                a += f": {ast.unparse(arg.annotation)}"
            args.append(a)
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwonlyargs:
            for a in node.args.kwonlyargs:
                arg_str = a.arg
                if a.annotation:
                    arg_str += f": {ast.unparse(a.annotation)}"
                args.append(arg_str)
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"def {node.name}({', '.join(args)}){ret}"

    def _get_visibility(self, name: str) -> str:
        if name.startswith("__") and not name.endswith("__"):
            return "private"
        if name.startswith("_"):
            return "protected"
        return "public"

    def _get_callee_name(self, func_node: ast.AST) -> Optional[str]:
        """Extract the callee name from a call expression."""
        match func_node:
            case ast.Name(id=name):
                return name
            case ast.Attribute(value=ast.Name(id=obj), attr=attr):
                return f"{obj}.{attr}"
            case ast.Attribute(value=ast.Attribute() as inner):
                inner_str = self._get_callee_name(inner)
                if inner_str:
                    return f"{inner_str}.{func_node.attr}"
                return func_node.attr
            case ast.Subscript(value=ast.Name(id=name)):
                return name
            case _:
                return None
