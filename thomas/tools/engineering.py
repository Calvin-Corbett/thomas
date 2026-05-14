"""Engineering toolkit tools for Thomas.

Provides system monitoring, code analysis, security scanning,
document parsing, and development utilities using best-in-class
open-source libraries.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System monitoring tools (psutil)
# ---------------------------------------------------------------------------


class SystemInfoTool(Tool):
    name = "eng.system_info"
    category = "engineering"
    description = (
        "Get system resource usage: CPU, memory, disk, and top processes. "
        "Useful for diagnosing performance issues or checking available resources."
    )
    parameters = {
        "type": "object",
        "properties": {
            "include_processes": {
                "type": "boolean",
                "description": "Include top 10 processes by CPU. Default false.",
            },
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import psutil
        except ImportError:
            return ToolResult(ok=False, error="psutil not installed (pip install psutil)")
        info: dict[str, Any] = {}
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        info["cpu_count"] = psutil.cpu_count()
        mem = psutil.virtual_memory()
        info["memory"] = {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": mem.percent,
        }
        disk = psutil.disk_usage("/")
        info["disk"] = {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "percent": disk.percent,
        }
        if args.get("include_processes"):
            procs = []
            for p in sorted(
                psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                key=lambda x: x.info.get("cpu_percent") or 0,
                reverse=True,
            )[:10]:
                procs.append(p.info)
            info["top_processes"] = procs
        return ToolResult(ok=True, data=json.dumps(info, indent=2))


# ---------------------------------------------------------------------------
# Code analysis tools (radon, vulture)
# ---------------------------------------------------------------------------


class CodeComplexityTool(Tool):
    name = "eng.code_complexity"
    category = "engineering"
    description = (
        "Analyze Python code complexity using cyclomatic complexity (CC) scoring. "
        "Returns functions/methods ranked by complexity with letter grades (A-F)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to Python file or directory to analyze.",
            },
            "min_grade": {
                "type": "string",
                "description": "Minimum complexity grade to report (A-F). Default 'B'.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from radon.complexity import cc_rank, cc_visit
        except ImportError:
            return ToolResult(ok=False, error="radon not installed (pip install radon)")
        target = Path(args["path"])
        min_grade = args.get("min_grade", "B").upper()
        grade_order = "ABCDEF"
        min_idx = grade_order.index(min_grade) if min_grade in grade_order else 1
        results = []
        files = [target] if target.is_file() else sorted(target.rglob("*.py"))
        for fpath in files[:100]:  # Cap at 100 files
            try:
                source = fpath.read_text(encoding="utf-8", errors="replace")
                blocks = cc_visit(source)
                for block in blocks:
                    rank = cc_rank(block.complexity)
                    if grade_order.index(rank) >= min_idx:
                        results.append(
                            {
                                "file": str(fpath),
                                "name": block.name,
                                "type": block.classname
                                if hasattr(block, "classname") and block.classname
                                else "function",
                                "line": block.lineno,
                                "complexity": block.complexity,
                                "grade": rank,
                            }
                        )
            except (OSError, SyntaxError) as exc:
                _log.debug("Skipping %s: %s", fpath, exc)
        results.sort(key=lambda r: r["complexity"], reverse=True)
        return ToolResult(ok=True, data=json.dumps(results[:50], indent=2))


class DeadCodeTool(Tool):
    name = "eng.dead_code"
    category = "engineering"
    description = (
        "Find unused code (functions, classes, variables, imports) in Python files. "
        "Returns items with confidence scores to reduce false positives."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to Python file or directory to scan.",
            },
            "min_confidence": {
                "type": "integer",
                "description": "Minimum confidence (60-100). Default 80.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import vulture  # noqa: F401
        except ImportError:
            return ToolResult(ok=False, error="vulture not installed (pip install vulture)")
        target = args["path"]
        min_conf = args.get("min_confidence", 80)
        proc = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            "vulture",
            target,
            f"--min-confidence={min_conf}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output:
            return ToolResult(ok=True, data="No dead code found.")
        return ToolResult(ok=True, data=output)


# ---------------------------------------------------------------------------
# Security scanning (bandit)
# ---------------------------------------------------------------------------


class SecurityScanTool(Tool):
    name = "eng.security_scan"
    category = "engineering"
    description = (
        "Scan Python code for security vulnerabilities using Bandit. "
        "Finds issues like hardcoded passwords, unsafe yaml.load, SQL injection, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to Python file or directory to scan.",
            },
            "severity": {
                "type": "string",
                "description": "Minimum severity: LOW, MEDIUM, HIGH. Default MEDIUM.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import bandit  # noqa: F401
        except ImportError:
            return ToolResult(ok=False, error="bandit not installed (pip install bandit)")
        target = args["path"]
        severity = args.get("severity", "MEDIUM").upper()
        sev_flag = {"LOW": "ll", "MEDIUM": "mm", "HIGH": "hh"}.get(severity, "mm")
        proc = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            "bandit",
            "-r",
            target,
            f"-{sev_flag}",
            "-f",
            "json",
            "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        try:
            data = json.loads(stdout.decode("utf-8", errors="replace"))
            issues = []
            for r in data.get("results", []):
                issues.append(
                    {
                        "file": r.get("filename", ""),
                        "line": r.get("line_number", 0),
                        "severity": r.get("issue_severity", ""),
                        "confidence": r.get("issue_confidence", ""),
                        "issue": r.get("issue_text", ""),
                        "test_id": r.get("test_id", ""),
                    }
                )
            return ToolResult(
                ok=True,
                data=json.dumps(
                    {
                        "total_issues": len(issues),
                        "issues": issues[:30],
                    },
                    indent=2,
                ),
            )
        except json.JSONDecodeError:
            return ToolResult(ok=True, data=stdout.decode("utf-8", errors="replace")[:5000])


# ---------------------------------------------------------------------------
# Document parsing tools
# ---------------------------------------------------------------------------


class ParseDocumentTool(Tool):
    name = "eng.parse_document"
    category = "engineering"
    description = (
        "Extract text content from documents: PDF, DOCX, and plain text files. "
        "Returns structured text with page/section markers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to document file (PDF, DOCX, TXT, MD).",
            },
            "max_pages": {
                "type": "integer",
                "description": "Max pages to extract from PDF. Default 50.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        fpath = Path(args["path"])
        if not fpath.exists():
            return ToolResult(ok=False, error=f"File not found: {fpath}")
        suffix = fpath.suffix.lower()
        max_pages = args.get("max_pages", 50)
        try:
            if suffix == ".pdf":
                return await self._parse_pdf(fpath, max_pages)
            elif suffix == ".docx":
                return await self._parse_docx(fpath)
            elif suffix in (".txt", ".md", ".rst", ".csv", ".log"):
                text = fpath.read_text(encoding="utf-8", errors="replace")
                return ToolResult(ok=True, data=text[:100_000])
            else:
                return ToolResult(ok=False, error=f"Unsupported format: {suffix}")
        except ImportError as ie:
            return ToolResult(ok=False, error=str(ie))

    async def _parse_pdf(self, fpath: Path, max_pages: int) -> ToolResult:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return ToolResult(ok=False, error="PyMuPDF not installed (pip install PyMuPDF)")
        doc = fitz.open(str(fpath))
        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append(f"--- Page {i + 1} ---\n{page.get_text()}")
        doc.close()
        return ToolResult(ok=True, data="\n".join(pages))

    async def _parse_docx(self, fpath: Path) -> ToolResult:
        try:
            import docx
        except ImportError:
            return ToolResult(ok=False, error="python-docx not installed (pip install python-docx)")
        doc = docx.Document(str(fpath))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return ToolResult(ok=True, data="\n\n".join(paragraphs))


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------


class FileTypeTool(Tool):
    name = "eng.file_type"
    category = "engineering"
    description = (
        "Detect the actual type of a file by examining its content headers, "
        "not just its extension. Useful for identifying misnamed or unknown files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to file to identify.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        fpath = Path(args["path"])
        if not fpath.exists():
            return ToolResult(ok=False, error=f"File not found: {fpath}")
        try:
            import magic

            mime = magic.from_file(str(fpath), mime=True)
            desc = magic.from_file(str(fpath))
            return ToolResult(
                ok=True,
                data=json.dumps(
                    {
                        "path": str(fpath),
                        "mime_type": mime,
                        "description": desc,
                        "size_bytes": fpath.stat().st_size,
                        "extension": fpath.suffix,
                    },
                    indent=2,
                ),
            )
        except ImportError:
            # Fallback without python-magic
            import mimetypes

            mime, _ = mimetypes.guess_type(str(fpath))
            return ToolResult(
                ok=True,
                data=json.dumps(
                    {
                        "path": str(fpath),
                        "mime_type": mime or "unknown",
                        "size_bytes": fpath.stat().st_size,
                        "extension": fpath.suffix,
                    },
                    indent=2,
                ),
            )


# ---------------------------------------------------------------------------
# Dependency analysis
# ---------------------------------------------------------------------------


class DependencyTreeTool(Tool):
    name = "eng.dependency_tree"
    category = "engineering"
    description = (
        "Analyze Python import dependencies for a file or module. " "Shows what a file imports and what imports it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to Python file to analyze imports.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        import ast

        fpath = Path(args["path"])
        if not fpath.exists():
            return ToolResult(ok=False, error=f"File not found: {fpath}")
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError as se:
            return ToolResult(ok=False, error=f"Syntax error: {se}")
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({"module": alias.name, "alias": alias.asname, "line": node.lineno})
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(
                        {
                            "module": f"{module}.{alias.name}" if module else alias.name,
                            "from": module,
                            "alias": alias.asname,
                            "line": node.lineno,
                        }
                    )
        stdlib = []
        third_party = []
        local = []
        for imp in imports:
            mod_root = imp["module"].split(".")[0]
            if mod_root == "thomas":
                local.append(imp)
            else:
                try:
                    __import__(mod_root)
                    import sys

                    mod_obj = sys.modules.get(mod_root)
                    if (
                        mod_obj
                        and hasattr(mod_obj, "__file__")
                        and mod_obj.__file__
                        and "site-packages" in (mod_obj.__file__ or "")
                    ):
                        third_party.append(imp)
                    else:
                        stdlib.append(imp)
                except ImportError:
                    third_party.append(imp)
        return ToolResult(
            ok=True,
            data=json.dumps(
                {
                    "file": str(fpath),
                    "total_imports": len(imports),
                    "stdlib": [i["module"] for i in stdlib],
                    "third_party": [i["module"] for i in third_party],
                    "local": [i["module"] for i in local],
                },
                indent=2,
            ),
        )


# ---------------------------------------------------------------------------
# Code formatting
# ---------------------------------------------------------------------------


class CodeFormatTool(Tool):
    name = "eng.format_code"
    category = "engineering"
    description = (
        "Format Python code using ruff (fast, modern formatter). " "Can also fix lint issues and sort imports."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to Python file or directory to format.",
            },
            "check_only": {
                "type": "boolean",
                "description": "Only check, don't modify files. Default false.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        target = args["path"]
        check_only = args.get("check_only", False)
        cmd = ["python", "-m", "ruff", "format"]
        if check_only:
            cmd.append("--check")
        cmd.append(target)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
        if proc.returncode == 0:
            return ToolResult(ok=True, data=output.strip() or "All files formatted correctly.")
        return ToolResult(ok=True, data=output.strip())


class LintTool(Tool):
    name = "eng.lint"
    category = "engineering"
    description = (
        "Lint Python code using ruff. Finds style issues, potential bugs, " "unused imports, and common mistakes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to Python file or directory to lint.",
            },
            "fix": {
                "type": "boolean",
                "description": "Auto-fix safe issues. Default false.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        target = args["path"]
        cmd = ["python", "-m", "ruff", "check"]
        if args.get("fix"):
            cmd.append("--fix")
        cmd.extend(["--output-format", "json", target])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        try:
            issues = json.loads(stdout.decode("utf-8", errors="replace"))
            summary = []
            for issue in issues[:30]:
                summary.append(
                    {
                        "file": issue.get("filename", ""),
                        "line": issue.get("location", {}).get("row", 0),
                        "code": issue.get("code", ""),
                        "message": issue.get("message", ""),
                    }
                )
            return ToolResult(
                ok=True,
                data=json.dumps(
                    {
                        "total_issues": len(issues),
                        "issues": summary,
                    },
                    indent=2,
                ),
            )
        except json.JSONDecodeError:
            return ToolResult(ok=True, data=stdout.decode("utf-8", errors="replace")[:5000])


# ---------------------------------------------------------------------------
# Web content extraction
# ---------------------------------------------------------------------------


class WebExtractTool(Tool):
    name = "eng.web_extract"
    category = "engineering"
    description = (
        "Extract clean text content from a web page URL. "
        "Removes navigation, ads, and boilerplate. Returns main content."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to extract content from.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import httpx
            from bs4 import BeautifulSoup
        except ImportError:
            return ToolResult(ok=False, error="httpx and beautifulsoup4 required")
        url = args["url"]
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Thomas-AI/0.14"})
                resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove scripts and styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Clean up whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean = "\n".join(lines)
            return ToolResult(ok=True, data=clean[:50_000])
        except httpx.HTTPError as he:
            return ToolResult(ok=False, error=f"HTTP error: {he}")


# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------


class DetectEncodingTool(Tool):
    name = "eng.detect_encoding"
    category = "engineering"
    description = (
        "Detect the character encoding of a file. "
        "Useful for fixing corrupted text or handling international content."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to file to detect encoding.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import chardet
        except ImportError:
            return ToolResult(ok=False, error="chardet not installed (pip install chardet)")
        fpath = Path(args["path"])
        if not fpath.exists():
            return ToolResult(ok=False, error=f"File not found: {fpath}")
        raw = fpath.read_bytes()[:100_000]  # Read up to 100KB
        result = chardet.detect(raw)
        return ToolResult(
            ok=True,
            data=json.dumps(
                {
                    "encoding": result.get("encoding"),
                    "confidence": result.get("confidence"),
                    "language": result.get("language"),
                },
                indent=2,
            ),
        )


# ---------------------------------------------------------------------------
# Git advanced analysis
# ---------------------------------------------------------------------------


class GitAnalysisTool(Tool):
    name = "eng.git_analysis"
    category = "engineering"
    description = (
        "Advanced git repository analysis: file change frequency (churn), "
        "contributor stats, and recent activity summary."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Path to git repository. Default '.'.",
            },
            "analysis": {
                "type": "string",
                "description": "Type: 'churn' (most-changed files), 'contributors', 'recent'. Default 'recent'.",
            },
            "days": {
                "type": "integer",
                "description": "Look back N days. Default 30.",
            },
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import git as gitmodule
        except ImportError:
            return ToolResult(ok=False, error="GitPython not installed (pip install gitpython)")
        repo_path = args.get("repo_path", ".")
        analysis = args.get("analysis", "recent")
        days = args.get("days", 30)
        try:
            gitmodule.Repo(repo_path)
        except (gitmodule.InvalidGitRepositoryError, gitmodule.NoSuchPathError) as e:
            return ToolResult(ok=False, error=str(e))
        since = f"--since={days} days ago"
        if analysis == "churn":
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "log",
                since,
                "--name-only",
                "--pretty=format:",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            files: dict[str, int] = {}
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                f = line.strip()
                if f:
                    files[f] = files.get(f, 0) + 1
            top = sorted(files.items(), key=lambda x: x[1], reverse=True)[:20]
            return ToolResult(ok=True, data=json.dumps([{"file": f, "changes": c} for f, c in top], indent=2))
        elif analysis == "contributors":
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "shortlog",
                "-sne",
                since,
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return ToolResult(ok=True, data=stdout.decode("utf-8", errors="replace").strip())
        else:  # recent
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "log",
                since,
                "--oneline",
                "-30",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return ToolResult(ok=True, data=stdout.decode("utf-8", errors="replace").strip())


# ---------------------------------------------------------------------------
# Project health / stats
# ---------------------------------------------------------------------------


class ProjectStatsTool(Tool):
    name = "eng.project_stats"
    category = "engineering"
    description = (
        "Get quick stats about a project: line counts by language, " "file counts, largest files, and directory sizes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to project root. Default '.'.",
            },
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        root = Path(args.get("path", "."))
        if not root.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {root}")
        ext_counts: dict[str, int] = {}
        ext_lines: dict[str, int] = {}
        largest: list = []
        total_files = 0
        skip = {".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache", "venv", ".venv"}
        for fpath in root.rglob("*"):
            if any(p in fpath.parts for p in skip):
                continue
            if not fpath.is_file():
                continue
            total_files += 1
            ext = fpath.suffix.lower() or "(none)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            size = fpath.stat().st_size
            largest.append((str(fpath), size))
            if ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".md"):
                try:
                    lines = len(fpath.read_bytes().split(b"\n"))
                    ext_lines[ext] = ext_lines.get(ext, 0) + lines
                except OSError:
                    pass
        largest.sort(key=lambda x: x[1], reverse=True)
        return ToolResult(
            ok=True,
            data=json.dumps(
                {
                    "total_files": total_files,
                    "files_by_type": dict(sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:15]),
                    "lines_by_type": dict(sorted(ext_lines.items(), key=lambda x: x[1], reverse=True)),
                    "largest_files": [{"path": p, "size_kb": round(s / 1024, 1)} for p, s in largest[:10]],
                },
                indent=2,
            ),
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_engineering_tools(registry) -> None:
    """Register all engineering toolkit tools."""
    tools = [
        SystemInfoTool(),
        CodeComplexityTool(),
        DeadCodeTool(),
        SecurityScanTool(),
        ParseDocumentTool(),
        FileTypeTool(),
        DependencyTreeTool(),
        CodeFormatTool(),
        LintTool(),
        WebExtractTool(),
        DetectEncodingTool(),
        GitAnalysisTool(),
        ProjectStatsTool(),
    ]
    for tool in tools:
        registry.register(tool)
    _log.info("Registered %d engineering tools", len(tools))
