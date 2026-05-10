"""
Executor Agent — applies refactoring plans to the filesystem with
safety mechanisms including backup creation and dry-run capability.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from .base import BaseAgent, AgentResult
from ..core.types import RefactoringPlan, RefactoringStep, ChangeSet


class ExecutorAgent(BaseAgent):
    """Agent that safely executes refactoring plans on the filesystem."""

    name = "executor"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._backup_dir: str = ""
        self._applied_steps: list[RefactoringStep] = []
        self._modified_files: set[str] = set()

    def execute(self, **kwargs) -> AgentResult:
        action = kwargs.get("action", "apply")
        start = time.time()

        actions = {
            "apply": self._apply_plan,
            "dry_run": self._dry_run,
            "rollback": self._rollback,
            "preview": self._preview_changes,
        }

        handler = actions.get(action)
        if handler is None:
            return self._err([f"Unknown action: {action}"])

        try:
            result_data = handler(**kwargs)
            return AgentResult(
                success=True,
                data=result_data,
                agent_name=self.name,
                execution_time_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return self._err([f"Executor error: {e}"])

    def _apply_plan(self, plan: RefactoringPlan, create_backup: bool = True, **kwargs) -> dict:
        """Apply a refactoring plan to the filesystem."""
        if create_backup and not self._backup_dir:
            self._create_backup(plan)

        applied: list[dict] = []
        failed: list[dict] = []

        for change_set in plan.change_sets:
            # Sort steps: within each file, process from bottom to top
            # to preserve line numbers
            file_steps = change_set.file_changes
            for file_path, steps in file_steps.items():
                # Sort by line number descending to preserve positions
                sorted_steps = sorted(steps, key=lambda s: s.location.line, reverse=True)

                for step in sorted_steps:
                    try:
                        self._apply_step(step)
                        self._applied_steps.append(step)
                        self._modified_files.add(file_path)
                        applied.append({
                            "file": file_path,
                            "line": step.location.line,
                            "description": step.description,
                        })
                    except Exception as e:
                        failed.append({
                            "file": file_path,
                            "line": step.location.line,
                            "error": str(e),
                        })
                        # If any step fails, rollback all
                        if failed:
                            self._rollback()
                            return {
                                "status": "ROLLED_BACK",
                                "applied_count": len(applied),
                                "failed_count": len(failed),
                                "applied": applied,
                                "failed": failed,
                                "error": f"Step failed, all changes rolled back: {failed[0]['error']}",
                            }

        return {
            "status": "SUCCESS",
            "applied_count": len(applied),
            "failed_count": len(failed),
            "applied": applied,
            "failed": failed,
            "modified_files": sorted(self._modified_files),
            "backup_location": self._backup_dir,
        }

    def _dry_run(self, plan: RefactoringPlan, **kwargs) -> dict:
        """Simulate applying a plan without making changes."""
        preview: list[dict] = []

        for change_set in plan.change_sets:
            for file_path, steps in change_set.file_changes.items():
                for step in steps:
                    preview.append({
                        "file": file_path,
                        "line": step.location.line,
                        "kind": step.kind.value,
                        "description": step.description,
                        "risk": step.risk.value,
                        "old_preview": step.old_text[:80] if step.old_text else "(from file)",
                        "new_preview": step.new_text[:80] if step.new_text else "(removed)",
                    })

        return {
            "plan_title": plan.title,
            "total_steps": len(preview),
            "impacted_files": sorted(plan.impacted_files),
            "risk_assessment": plan.risk_assessment,
            "preview": preview,
        }

    def _rollback(self, **kwargs) -> dict:
        """Rollback all applied changes using backups."""
        if not self._backup_dir:
            return {"status": "NOTHING_TO_ROLLBACK"}

        restored: list[str] = []
        failed: list[str] = []

        for file_path in self._modified_files:
            backup_path = os.path.join(self._backup_dir, os.path.basename(file_path) + ".bak")
            if os.path.exists(backup_path):
                try:
                    shutil.copy2(backup_path, file_path)
                    restored.append(file_path)
                except Exception as e:
                    failed.append(f"{file_path}: {e}")
            else:
                failed.append(f"{file_path}: no backup found")

        self._applied_steps.clear()
        self._modified_files.clear()

        return {
            "status": "ROLLED_BACK",
            "restored": restored,
            "restored_count": len(restored),
            "failed": failed,
            "failed_count": len(failed),
        }

    def _preview_changes(self, plan: RefactoringPlan, **kwargs) -> dict:
        """Preview the actual diff that would be applied."""
        diffs: list[dict] = []

        for change_set in plan.change_sets:
            for file_path, steps in change_set.file_changes.items():
                original = self._read_file(file_path)
                if original is None:
                    continue
                lines = original.splitlines()

                for step in sorted(steps, key=lambda s: s.location.line, reverse=True):
                    if step.old_text and step.new_text is not None:
                        start = step.location.line - 1
                        end = step.location.end_line or (start + 1)
                        if 0 <= start < len(lines):
                            diffs.append({
                                "file": file_path,
                                "line": step.location.line,
                                "description": step.description,
                                "before": step.old_text[:120],
                                "after": step.new_text[:120],
                            })

        return {
            "plan_title": plan.title,
            "diff_count": len(diffs),
            "diffs": diffs,
        }

    def _apply_step(self, step: RefactoringStep) -> None:
        """Apply a single refactoring step to its file."""
        content = self._read_file(step.file)
        if content is None:
            raise FileNotFoundError(f"Cannot read file: {step.file}")

        lines = content.split("\n")
        target_line = step.location.line - 1

        if step.kind.value == "rename":
            # For renames, we replace the text inline
            if step.old_text and 0 <= target_line < len(lines):
                lines[target_line] = self._safe_replace(
                    lines[target_line], step.old_text, step.new_text,
                )

        elif step.kind.value in ("extract_function", "extract_class"):
            if step.old_text:
                # Remove old text block
                start = step.location.line - 1
                end = step.location.end_line or (start + 1)
                del lines[start:end]
                lines.insert(start, step.new_text)
            elif step.new_text:
                # Insert new block at insertion point
                insert_at = min(target_line, len(lines))
                for new_line in reversed(step.new_text.strip().split("\n")):
                    lines.insert(insert_at, new_line)

        elif step.kind.value == "move_symbol":
            if step.old_text and not step.new_text:
                # Remove from source
                start = step.location.line - 1
                end = step.location.end_line or (start + 1)
                if 0 <= start < len(lines):
                    del lines[start:end]
            elif step.new_text and not step.old_text:
                # Add to destination
                insert_at = min(target_line, len(lines))
                for new_line in reversed(step.new_text.strip().split("\n")):
                    lines.insert(insert_at, new_line)

        elif step.kind.value in ("change_signature", "inline"):
            if step.old_text and step.new_text is not None and 0 <= target_line < len(lines):
                lines[target_line] = self._safe_replace(
                    lines[target_line], step.old_text, step.new_text,
                )

        self._write_file(step.file, "\n".join(lines))

    def _safe_replace(self, line: str, old: str, new: str) -> str:
        """Safely replace text within a line, finding the best match."""
        if old in line:
            return line.replace(old, new, 1)
        # Try fuzzy: replace just the identifier
        words = old.split()
        for word in words:
            if word.isidentifier() and word in line:
                return line.replace(word, new, 1)
        return line

    def _create_backup(self, plan: RefactoringPlan) -> None:
        """Create timestamped backups of all affected files."""
        ts = int(time.time())
        self._backup_dir = os.path.join(
            os.getcwd(), f".refactoring_backup_{ts}",
        )
        os.makedirs(self._backup_dir, exist_ok=True)

        for file_path in plan.impacted_files:
            if os.path.exists(file_path):
                backup = os.path.join(
                    self._backup_dir, os.path.basename(file_path) + ".bak",
                )
                shutil.copy2(file_path, backup)

    def _read_file(self, file_path: str) -> str | None:
        """Read a file from disk, fallback to graph cache."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except (FileNotFoundError, PermissionError):
            return self.context.get_file_content(file_path)

    def _write_file(self, file_path: str, content: str) -> None:
        """Write content to a file."""
        Path(file_path).write_text(content, encoding="utf-8")
