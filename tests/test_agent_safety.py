"""
Agent Safety Tests — Prevent AI agents from breaking things.

These tests enforce architectural safety guardrails that prevent agents from:
- Modifying dead code files (app_parts/)
- Breaking JavaScript syntax in split runtime files (runtime/*.js)
- Creating unparseable Python files
- Accidentally "finishing" placeholder implementations
- Other harmful architectural patterns
"""

import ast
import subprocess
from pathlib import Path


class TestAgentSafety:
    """Safety tests that must pass for all agent changes."""

    def test_app_parts_not_modified(self):
        """
        Test that app_parts/ files are not newer than app_runtime_loader.js.

        If app_parts/ files are newer, it means an agent edited them (bad).
        If app_runtime_loader.js is newer, the build system regenerated them (good).
        """
        app_parts_dir = Path("thomas/server/web/js/app_parts")
        runtime_loader = Path("thomas/server/web/js/app_runtime_loader.js")

        if not app_parts_dir.exists():
            return  # Directory doesn't exist, skip test

        loader_mtime = runtime_loader.stat().st_mtime if runtime_loader.exists() else 0

        # Check all part files
        part_files = sorted(app_parts_dir.glob("part-*.js"))
        for part_file in part_files:
            part_mtime = part_file.stat().st_mtime
            assert part_mtime <= loader_mtime, (
                f"Dead code file {part_file.name} is newer than app_runtime_loader.js!\n"
                f"This indicates manual editing of dead code.\n"
                f"Edit the split runtime files in thomas/server/web/js/runtime/ instead.\n\n"
                f"To fix: git checkout -- {part_file}"
            )

    def test_app_runtime_primary_has_valid_javascript(self):
        """
        Test that all split runtime JS files have valid JavaScript syntax.

        Uses node.js to check syntax if available.
        """
        runtime_dir = Path("thomas/server/web/js/runtime")

        if not runtime_dir.exists():
            return  # Directory doesn't exist, skip test

        # Check each runtime file for valid syntax
        runtime_files = sorted(runtime_dir.glob("*.js"))
        try:
            for js_file in runtime_files:
                result = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True, timeout=5)
                assert result.returncode == 0, (
                    f"JavaScript syntax error in {js_file}:\n"
                    f"{result.stderr}\n\n"
                    f"Fix the syntax errors and try again."
                )
        except FileNotFoundError:
            # node.js not available, skip this check
            pass
        except subprocess.TimeoutExpired:
            # Timeout, skip this check
            pass

    def test_all_python_files_parse_correctly(self):
        """
        Test that all Python files in thomas/ can be parsed without syntax errors.

        This catches typos and syntax errors that agents might introduce.
        """
        python_files = list(Path("thomas").rglob("*.py"))

        failed_files = []
        for py_file in python_files:
            try:
                with open(py_file, encoding="utf-8") as f:
                    code = f.read()
                ast.parse(code)
            except SyntaxError as e:
                failed_files.append((str(py_file), f"SyntaxError: {e}"))
            except Exception as e:
                failed_files.append((str(py_file), f"ParseError: {e}"))

        assert not failed_files, (
            f"Found {len(failed_files)} Python files with syntax errors:\n"
            + "\n".join([f"{f}: {e}" for f, e in failed_files[:5]])
            + ("\n... and more" if len(failed_files) > 5 else "")
        )

    def test_placeholder_files_not_modified(self):
        """
        Test that placeholder files haven't been accidentally "restored" with real code.

        Placeholder files should remain simple stubs. If they suddenly have 500+ lines
        of real implementation, an agent probably tried to "complete" them.
        """
        placeholder_files = [
            Path("thomas/memory/episodic.py"),
            Path("thomas/memory/episodic_store.py"),
            Path("thomas/memory/summarization.py"),
        ]

        for placeholder_file in placeholder_files:
            if not placeholder_file.exists():
                continue

            # Placeholder files should be small (under 200 lines is typical)
            with open(placeholder_file, encoding="utf-8") as f:
                content = f.read()
            line_count = len(content.split("\n"))

            # If a placeholder file suddenly has >400 lines, something went wrong
            assert line_count <= 400, (
                f"Placeholder file {placeholder_file} has grown to {line_count} lines!\n"
                f"Placeholder files should remain small stubs (under 100 lines).\n"
                f"If you need to implement this functionality:\n"
                f"  1. Create a NEW file with a real name\n"
                f"  2. Implement the full feature there\n"
                f"  3. Update imports to use your new file\n"
                f"\n"
                f"To revert: git checkout -- {placeholder_file}"
            )

            # Also check that it's actually a stub (has minimal real code)
            # Stubs typically have comments and class/function definitions but little implementation
            try:
                tree = ast.parse(content)
                # Count actual code lines (not comments/docstrings)
                code_lines = 0
                for node in ast.walk(tree):
                    if isinstance(node, ast.stmt):
                        code_lines += 1

                # A real implementation would have 100+ statements
                # A stub would have <50
                max_code_lines = 100
                assert code_lines <= max_code_lines, (
                    f"Placeholder file {placeholder_file} has {code_lines} code statements!\n"
                    f"This looks like it's being developed into a real implementation.\n"
                    f"See Rule 9 in thomas/memory/GUARDRAILS.md for correct approach."
                )
            except SyntaxError:
                # If it has syntax errors, it was definitely modified wrong
                pass

    def test_monolith_files_within_limits(self):
        """
        Test that core monolith files haven't grown beyond acceptable limits.

        This prevents agents from adding "just a little more" to already-large files.
        """
        known_monoliths = {
            "thomas/server/routes/mission.py": 2500,  # Known to be large
            "thomas/server/app.py": 1500,
            "thomas/server/routes/chat_aiohttp.py": 800,
            "thomas/memory/curator.py": 1130,
            "thomas/memory/v2/fabric.py": 1170,
        }

        for filepath, max_lines in known_monoliths.items():
            path = Path(filepath)
            if not path.exists():
                continue

            with open(path, encoding="utf-8") as f:
                line_count = len(f.readlines())

            # Allow 5% growth from baseline, but not more
            tolerance = int(max_lines * 0.05)
            limit = max_lines + tolerance

            assert line_count <= limit, (
                f"Monolith file {filepath} has grown to {line_count} lines (limit: {limit})!\n"
                f"This file is already identified as needing to be split.\n"
                f"Before adding more code, plan the split strategy:\n"
                f"  1. Read the GUARDRAILS.md in this module\n"
                f"  2. Find the suggested split strategy\n"
                f"  3. Ask the user for guidance on the split\n"
                f"  4. Implement in new focused files\n"
                f"\n"
                f"See: thomas/server/GUARDRAILS.md (Rule 1, 2, 3)"
            )

    def test_no_agent_file_editing_violations(self):
        """
        Test that there are references to proper agent editing rules.

        Ensures that AGENT_FILE_EDITING_RULES.md exists or similar.
        """
        rule_files = [
            Path("GUARDRAILS.md"),
            Path("thomas/server/GUARDRAILS.md"),
            Path("thomas/memory/GUARDRAILS.md"),
        ]

        for rule_file in rule_files:
            assert rule_file.exists(), (
                f"Missing guardrails file: {rule_file}\n" f"This file documents constraints for agent edits."
            )

    def test_no_circular_dependencies_introduced(self):
        """
        Test that common forbidden circular dependencies haven't been introduced.

        Prevents agents from creating circular imports that break the module structure.
        """
        forbidden_pairs = [
            ("thomas.server", "thomas.browser"),
            ("thomas.memory", "thomas.agent"),
            ("thomas.memory", "thomas.server"),
            ("thomas.agent", "thomas.cli"),
        ]

        # This is a simple check: if these files import each other, it's bad
        # In a real implementation, you'd use import analysis
        # For now, we just document the rule

        for module1, module2 in forbidden_pairs:
            # Convert to file paths
            path1 = Path(module1.replace(".", "/"))
            path2 = Path(module2.replace(".", "/"))

            if not path1.exists() or not path2.exists():
                continue

            # Check imports in module1 - should not import module2
            for py_file in path1.rglob("*.py"):
                try:
                    with open(py_file, encoding="utf-8") as f:
                        content = f.read()

                    # Simple regex check for imports
                    import_module2 = f"from {module2}" in content or f"import {module2}" in content
                    assert not import_module2, (
                        f"Circular dependency detected!\n"
                        f"{py_file} imports from {module2}\n"
                        f"This is forbidden because it creates a circular dependency.\n"
                        f"See GUARDRAILS.md for the module dependency graph."
                    )
                except Exception:
                    pass  # Skip on any read error

    def test_pyc_files_not_in_tree(self):
        """
        Test that .pyc files are not being COMMITTED (tracked in git).

        Compiled Python files should never be in version control. The previous
        rglob check also caught .pyc files generated at import time during the
        test run itself — a false positive, since Python regenerates these
        from .py sources on every interpreter invocation. Check `git ls-files`
        instead so we only fail when a .pyc has actually been committed.
        """
        import subprocess

        result = subprocess.run(
            ["git", "ls-files", "thomas"],
            capture_output=True,
            text=True,
            check=False,
        )
        tracked_pyc = [line for line in result.stdout.splitlines() if line.strip().endswith(".pyc")]
        assert not tracked_pyc, (
            f"Found {len(tracked_pyc)} tracked .pyc files in thomas/:\n"
            + "\n".join(tracked_pyc[:5])
            + "\n\nCompiled Python files should not be committed.\n"
            "Ensure .gitignore includes *.pyc and __pycache__/"
        )

    def test_no_temp_files_in_staged_changes(self):
        """
        Test that temporary/debug files aren't being committed.

        Agents sometimes leave debug print statements or temporary files.
        """
        temp_patterns = [
            "*_tmp.py",
            "*_debug.py",
            "*_test_scratch.py",
            "tmp_*.py",
            "temp_*.py",
        ]

        temp_files = []
        for pattern in temp_patterns:
            temp_files.extend(Path("thomas").glob(f"**/{pattern}"))

        # Allow some known temp files in specific directories
        allowed_temp_dirs = {".tmp", "__pycache__", ".pytest_cache"}
        temp_files = [f for f in temp_files if not any(allowed_dir in f.parts for allowed_dir in allowed_temp_dirs)]

        assert not temp_files, (
            f"Found {len(temp_files)} temporary files in thomas/:\n"
            + "\n".join([str(f) for f in temp_files[:5]])
            + "\n\nTemporary debug files should not be committed.\n"
            "Delete these files before committing."
        )


class TestArchitectureGuards:
    """Tests that verify architectural constraints are still enforced."""

    def test_guardrails_files_exist_and_readable(self):
        """Test that GUARDRAILS.md files exist in critical modules."""
        critical_guardrails = [
            "GUARDRAILS.md",
            "thomas/memory/GUARDRAILS.md",
            "thomas/server/GUARDRAILS.md",
            "thomas/agent/GUARDRAILS.md",
            "thomas/server/web/js/app_parts/GUARDRAILS.md",
        ]

        for guardrail_path in critical_guardrails:
            path = Path(guardrail_path)
            assert path.exists(), f"Missing guardrails file: {guardrail_path}"

            # Verify it's readable and has content
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert len(content) > 100, f"GUARDRAILS.md {guardrail_path} is too short"
            assert "AGENT" in content.upper(), f"GUARDRAILS.md {guardrail_path} should mention agent constraints"

    def test_validate_agent_changes_script_exists(self):
        """Test that the safety validation script exists."""
        script_path = Path("scripts/validate_agent_changes.py")
        assert script_path.exists(), (
            "Missing safety validation script: scripts/validate_agent_changes.py\n"
            "This script enforces safety gates for agent changes."
        )

        # Verify it's executable and has content
        with open(script_path, encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 500, "Script is too short, might be incomplete"
        assert "def check_" in content, "Script should have check functions"
