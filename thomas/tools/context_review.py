"""Context-aware agentic code review (CAP-081).

A deterministic, standards-cited reviewer that inspects a *set* of changed
modules together and reports **cross-module invariant violations** — defects
that cannot be seen by looking at any single file in isolation.

Motivation
----------
A per-file linter cannot tell that ``pkg.caller`` still calls
``do_work(a, b)`` after ``pkg.core.do_work`` grew a third required parameter,
nor that ``from pkg.core import helper`` names a symbol that no longer exists.
Those are *relational* facts spanning two or more modules. This module parses
every changed module with :mod:`ast`, builds a cross-module symbol/import/call
index, and evaluates a set of :class:`Invariant` checks against it.

Every finding is **standards-cited**: it names the specific rule it violates
(a stable ``rule_id`` plus a human ``rule_description``) so a reviewer sees
*why* the code is wrong, not merely *where*. Every finding also carries the
two-or-more :class:`Location` objects that constitute the cross-module
evidence (e.g. the call site *and* the definition it disagrees with).

Design goals
------------
* **Deterministic** — identical inputs always yield byte-identical findings,
  sorted by a total order. No wall-clock, randomness, or filesystem reads.
* **Hermetic** — sources are passed in as text; nothing is imported or
  executed. Suitable for unit tests and for reviewing a diff before it lands.
* **Extensible** — the invariant/rule set is *injected*. Callers may supply
  their own :class:`Invariant` implementations or reconfigure the built-ins
  (for example, the dependency-direction rule takes a project-specific set of
  forbidden edges).

Only the Python standard library is used.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable

__all__ = [
    "ModuleSource",
    "Location",
    "Finding",
    "FunctionSignature",
    "ImportBinding",
    "CallSite",
    "ModuleIndex",
    "Invariant",
    "SignatureCallArityInvariant",
    "UndefinedImportInvariant",
    "DependencyDirectionInvariant",
    "ContextAwareReviewer",
    "default_invariants",
    "review_sources",
]

# Severity levels, ordered from most to least severe for deterministic ranking.
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


# ---------------------------------------------------------------------------
# Public value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModuleSource:
    """One changed module presented to the reviewer.

    ``name`` is the dotted import path (e.g. ``"pkg.core"``) and is what
    ``from pkg.core import x`` statements in *other* modules resolve against.
    ``path`` is a display path used for ``file:line`` reporting; it defaults to
    ``name`` when omitted so findings are always locatable.
    """

    name: str
    source: str
    path: str = ""

    def display_path(self) -> str:
        return self.path or self.name


@dataclass(frozen=True)
class Location:
    """A single code location involved in a cross-module finding."""

    module: str
    path: str
    line: int
    symbol: str = ""
    role: str = ""  # e.g. "call-site", "definition", "import", "importer"

    def as_ref(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Finding:
    """A standards-cited, cross-module invariant violation.

    Attributes
    ----------
    invariant_id:
        Stable identifier of the invariant that was violated. Equal to the
        cited ``rule_id`` — the invariant *is* the standard being enforced.
    rule_id / rule_description:
        The standards citation. ``rule_id`` is a short stable slug; the
        description explains the rule in human terms so the reviewer sees why.
    severity:
        One of ``"error"``, ``"warning"``, ``"info"``.
    message:
        Human-readable summary of this specific violation.
    file / line:
        The primary ``file:line`` a reviewer should open first (the location
        that must change to fix the violation).
    locations:
        Two-or-more locations that together constitute the cross-module
        evidence — never fewer than two, because these are *cross-module*
        invariants by construction.
    """

    invariant_id: str
    rule_id: str
    rule_description: str
    severity: str
    message: str
    file: str
    line: int
    locations: tuple[Location, ...]

    @property
    def citation(self) -> str:
        """The standards citation, ready to print: ``<rule_id>: <description>``."""
        return f"{self.rule_id}: {self.rule_description}"

    def sort_key(self) -> tuple:
        return (
            self.file,
            self.line,
            _SEVERITY_ORDER.get(self.severity, 99),
            self.invariant_id,
            self.message,
        )

    def to_dict(self) -> dict:
        return {
            "invariant_id": self.invariant_id,
            "rule_id": self.rule_id,
            "rule_description": self.rule_description,
            "citation": self.citation,
            "severity": self.severity,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "locations": [
                {
                    "module": loc.module,
                    "path": loc.path,
                    "line": loc.line,
                    "symbol": loc.symbol,
                    "role": loc.role,
                    "ref": loc.as_ref(),
                }
                for loc in self.locations
            ],
        }


# ---------------------------------------------------------------------------
# Parsed facts about a single module
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionSignature:
    """Positional/keyword arity facts for a top-level function definition."""

    name: str
    module: str
    path: str
    line: int
    positional: tuple[str, ...]  # posonly + normal, in order
    num_required_positional: int  # positional params with no default
    has_vararg: bool  # def f(*args)
    required_kwonly: tuple[str, ...]  # keyword-only params with no default
    accepts_kwargs: bool  # def f(**kwargs)

    def definition_location(self) -> Location:
        return Location(
            module=self.module,
            path=self.path,
            line=self.line,
            symbol=self.name,
            role="definition",
        )

    def arity_mismatch(self, call: CallSite) -> str | None:
        """Return a human explanation if ``call`` cannot satisfy this signature.

        Returns ``None`` when the call is compatible or when compatibility
        cannot be determined (e.g. the call unpacks ``*args``).
        """
        if call.has_star_args:
            # Unknown number of positional arguments supplied; cannot judge.
            return None

        max_positional = None if self.has_vararg else len(self.positional)
        if max_positional is not None and call.positional_count > max_positional:
            return (
                f"call passes {call.positional_count} positional argument(s) "
                f"but '{self.name}' accepts at most {max_positional}"
            )

        if call.has_kwargs_unpack:
            # A **mapping may supply any missing keyword; do not claim "too few".
            return None

        # A required positional param is satisfied by position or by keyword.
        required_positional = self.positional[: self.num_required_positional]
        missing = [
            name
            for index, name in enumerate(required_positional)
            if index >= call.positional_count and name not in call.keyword_names
        ]
        missing += [name for name in self.required_kwonly if name not in call.keyword_names]
        if missing:
            joined = ", ".join(missing)
            return (
                f"call to '{self.name}' is missing required argument(s): {joined} "
                f"(passed {call.positional_count} positional, "
                f"keywords {{{', '.join(sorted(call.keyword_names))}}})"
            )
        return None


@dataclass(frozen=True)
class ImportBinding:
    """A name brought into a module by an import statement.

    For ``from pkg.core import helper as h`` this records
    ``local_name='h'``, ``source_module='pkg.core'``, ``symbol='helper'``,
    ``is_module_import=False``. For ``import pkg.core as core`` it records the
    module binding with ``is_module_import=True``.
    """

    local_name: str
    source_module: str
    symbol: str
    line: int
    is_module_import: bool


@dataclass(frozen=True)
class CallSite:
    """A function/attribute call observed in a module."""

    line: int
    positional_count: int
    keyword_names: frozenset[str]
    has_star_args: bool
    has_kwargs_unpack: bool
    # Resolution hints (populated during indexing):
    local_name: str = ""  # bare name called, e.g. "helper" for helper(...)
    attr_base: str = ""  # base name for attribute calls, e.g. "core" in core.helper()
    attr_name: str = ""  # attribute called, e.g. "helper" in core.helper()


@dataclass(frozen=True)
class _ModuleFacts:
    module: str
    path: str
    defined_names: frozenset[str]
    functions: Mapping[str, FunctionSignature]
    imports: tuple[ImportBinding, ...]
    calls: tuple[CallSite, ...]
    parse_error: str | None = None


# ---------------------------------------------------------------------------
# Cross-module index
# ---------------------------------------------------------------------------


class ModuleIndex:
    """Immutable index of every reviewed module and their relationships.

    Built once by :meth:`ContextAwareReviewer.build_index` and handed to each
    invariant. Iteration order is deterministic (modules sorted by name).
    """

    def __init__(self, modules: Sequence[_ModuleFacts]) -> None:
        self._modules: tuple[_ModuleFacts, ...] = tuple(sorted(modules, key=lambda m: m.module))
        self._by_name: dict[str, _ModuleFacts] = {m.module: m for m in self._modules}

    @property
    def module_names(self) -> tuple[str, ...]:
        return tuple(m.module for m in self._modules)

    def modules(self) -> tuple[_ModuleFacts, ...]:
        return self._modules

    def has_module(self, name: str) -> bool:
        return name in self._by_name

    def function(self, module: str, name: str) -> FunctionSignature | None:
        facts = self._by_name.get(module)
        if facts is None:
            return None
        return facts.functions.get(name)

    def defines(self, module: str, name: str) -> bool:
        facts = self._by_name.get(module)
        return facts is not None and name in facts.defined_names

    def resolve_call_target(self, facts: _ModuleFacts, call: CallSite) -> tuple[str, str] | None:
        """Resolve a call to ``(source_module, function_name)`` when possible.

        Only calls that resolve to a function *defined in another reviewed
        module* are returned; everything else (local calls, calls into unknown
        third-party modules, builtins) yields ``None`` so no false positives
        arise.
        """
        binding_by_local = {b.local_name: b for b in facts.imports}

        # Case 1: bare call of an imported symbol, e.g. `helper(...)`.
        if call.local_name:
            binding = binding_by_local.get(call.local_name)
            if binding and not binding.is_module_import:
                if binding.source_module != facts.module and self.has_module(binding.source_module):
                    return (binding.source_module, binding.symbol)
            return None

        # Case 2: attribute call on an imported module, e.g. `core.helper(...)`.
        if call.attr_base and call.attr_name:
            binding = binding_by_local.get(call.attr_base)
            if binding and binding.is_module_import:
                if binding.source_module != facts.module and self.has_module(binding.source_module):
                    return (binding.source_module, call.attr_name)
        return None


# ---------------------------------------------------------------------------
# Invariant protocol + built-in invariants
# ---------------------------------------------------------------------------


@runtime_checkable
class Invariant(Protocol):
    """A cross-module rule. Injected into the reviewer; fully extensible.

    Implementations expose the standards citation (``rule_id`` +
    ``rule_description`` + ``severity``) and an :meth:`evaluate` that yields
    :class:`Finding` objects for any violation found in the index.
    """

    rule_id: str
    rule_description: str
    severity: str

    def evaluate(self, index: ModuleIndex) -> list[Finding]: ...


class _BaseInvariant:
    """Shared helper that stamps the citation onto every finding it emits."""

    rule_id: str = ""
    rule_description: str = ""
    severity: str = "error"

    def _finding(
        self,
        *,
        message: str,
        file: str,
        line: int,
        locations: Sequence[Location],
    ) -> Finding:
        if len(locations) < 2:
            raise ValueError("cross-module findings require >= 2 evidence locations")
        return Finding(
            invariant_id=self.rule_id,
            rule_id=self.rule_id,
            rule_description=self.rule_description,
            severity=self.severity,
            message=message,
            file=file,
            line=line,
            locations=tuple(locations),
        )


class SignatureCallArityInvariant(_BaseInvariant):
    """A call must supply the arguments its target function requires.

    Cross-module: the *definition* lives in one module and the *call site* in
    another. When a signature changes but a caller in a different module is not
    updated, the arg count no longer matches and this fires.
    """

    rule_id = "XMOD001"
    rule_description = (
        "A call site must satisfy the arity of the function it invokes; when a "
        "function's signature changes, every caller in every module must be "
        "updated to match (cross-module call/definition consistency)."
    )
    severity = "error"

    def evaluate(self, index: ModuleIndex) -> list[Finding]:
        findings: list[Finding] = []
        for facts in index.modules():
            for call in facts.calls:
                target = index.resolve_call_target(facts, call)
                if target is None:
                    continue
                source_module, func_name = target
                signature = index.function(source_module, func_name)
                if signature is None:
                    continue
                mismatch = signature.arity_mismatch(call)
                if mismatch is None:
                    continue
                call_loc = Location(
                    module=facts.module,
                    path=facts.path,
                    line=call.line,
                    symbol=func_name,
                    role="call-site",
                )
                findings.append(
                    self._finding(
                        message=(
                            f"cross-module arity mismatch: {mismatch}; defined in "
                            f"'{source_module}' ({signature.path}:{signature.line})"
                        ),
                        file=facts.path,
                        line=call.line,
                        locations=(call_loc, signature.definition_location()),
                    )
                )
        return findings


class UndefinedImportInvariant(_BaseInvariant):
    """An imported symbol must exist in the module it is imported from.

    Cross-module: ``from pkg.core import helper`` in one module is only valid
    if ``pkg.core`` (another reviewed module) actually defines ``helper``.
    """

    rule_id = "XMOD002"
    rule_description = (
        "A 'from <module> import <name>' must reference a name that the target "
        "module actually defines or re-exports; importing an undefined symbol "
        "is an ImportError at runtime (cross-module symbol resolution)."
    )
    severity = "error"

    def evaluate(self, index: ModuleIndex) -> list[Finding]:
        findings: list[Finding] = []
        for facts in index.modules():
            for binding in facts.imports:
                if binding.is_module_import:
                    continue
                if not index.has_module(binding.source_module):
                    # Third-party / stdlib target — not part of the review set.
                    continue
                if index.defines(binding.source_module, binding.symbol):
                    continue
                import_loc = Location(
                    module=facts.module,
                    path=facts.path,
                    line=binding.line,
                    symbol=binding.symbol,
                    role="import",
                )
                target_facts = index._by_name[binding.source_module]
                target_loc = Location(
                    module=binding.source_module,
                    path=target_facts.path,
                    line=1,
                    symbol=binding.symbol,
                    role="target-module",
                )
                findings.append(
                    self._finding(
                        message=(
                            f"imports undefined symbol '{binding.symbol}' from "
                            f"'{binding.source_module}' — no such name is defined "
                            f"or re-exported there"
                        ),
                        file=facts.path,
                        line=binding.line,
                        locations=(import_loc, target_loc),
                    )
                )
        return findings


class DependencyDirectionInvariant(_BaseInvariant):
    """Declared dependency-direction rules must not be violated across modules.

    The set of forbidden ``(importer, imported)`` edges is *injected*, keeping
    this hermetic and project-specific. An edge ``(a, b)`` forbids module ``a``
    (or any submodule ``a.*``) from importing module ``b`` (or ``b.*``).
    """

    rule_id = "XMOD003"
    rule_description = (
        "Module imports must respect the declared dependency direction; a "
        "module may not import from a module it is architecturally forbidden "
        "to depend on (cross-module layering / dependency-direction rule)."
    )
    severity = "error"

    def __init__(
        self,
        forbidden_edges: Iterable[tuple[str, str]] = (),
        *,
        rule_description: str | None = None,
    ) -> None:
        self._forbidden: tuple[tuple[str, str], ...] = tuple(forbidden_edges)
        if rule_description is not None:
            # Allow callers to cite their own architecture document verbatim.
            self.rule_description = rule_description

    @staticmethod
    def _matches(module: str, prefix: str) -> bool:
        return module == prefix or module.startswith(prefix + ".")

    def evaluate(self, index: ModuleIndex) -> list[Finding]:
        if not self._forbidden:
            return []
        findings: list[Finding] = []
        for facts in index.modules():
            for binding in facts.imports:
                for importer_prefix, imported_prefix in self._forbidden:
                    if self._matches(facts.module, importer_prefix) and self._matches(
                        binding.source_module, imported_prefix
                    ):
                        importer_loc = Location(
                            module=facts.module,
                            path=facts.path,
                            line=binding.line,
                            symbol=binding.source_module,
                            role="importer",
                        )
                        imported_loc = Location(
                            module=binding.source_module,
                            path=index._by_name[binding.source_module].path
                            if index.has_module(binding.source_module)
                            else binding.source_module,
                            line=1,
                            symbol=binding.source_module,
                            role="imported",
                        )
                        findings.append(
                            self._finding(
                                message=(
                                    f"forbidden dependency: '{facts.module}' must "
                                    f"not import from '{binding.source_module}' "
                                    f"(declared edge "
                                    f"{importer_prefix} -x-> {imported_prefix})"
                                ),
                                file=facts.path,
                                line=binding.line,
                                locations=(importer_loc, imported_loc),
                            )
                        )
                        break  # one finding per import line is enough
        return findings


def default_invariants(
    forbidden_edges: Iterable[tuple[str, str]] = (),
) -> list[Invariant]:
    """The built-in invariant set.

    ``forbidden_edges`` seeds the dependency-direction invariant; pass an empty
    iterable (the default) to leave it inert.
    """
    return [
        SignatureCallArityInvariant(),
        UndefinedImportInvariant(),
        DependencyDirectionInvariant(forbidden_edges),
    ]


# ---------------------------------------------------------------------------
# The reviewer
# ---------------------------------------------------------------------------


class ContextAwareReviewer:
    """Reviews a set of changed modules for cross-module invariant violations.

    Parameters
    ----------
    invariants:
        The injected rule set. Defaults to :func:`default_invariants`. Supply
        your own list to extend or restrict what is checked.
    """

    def __init__(self, invariants: Sequence[Invariant] | None = None) -> None:
        self._invariants: tuple[Invariant, ...] = tuple(invariants if invariants is not None else default_invariants())

    @property
    def invariants(self) -> tuple[Invariant, ...]:
        return self._invariants

    # -- indexing ----------------------------------------------------------

    def build_index(self, sources: Iterable[ModuleSource]) -> ModuleIndex:
        facts = [self._analyze(src) for src in sources]
        return ModuleIndex(facts)

    def _analyze(self, src: ModuleSource) -> _ModuleFacts:
        path = src.display_path()
        try:
            tree = ast.parse(src.source, filename=path)
        except SyntaxError as exc:
            return _ModuleFacts(
                module=src.name,
                path=path,
                defined_names=frozenset(),
                functions={},
                imports=(),
                calls=(),
                parse_error=f"{exc.msg} (line {exc.lineno})",
            )

        defined: set[str] = set()
        functions: dict[str, FunctionSignature] = {}
        imports: list[ImportBinding] = []

        # Top-level definitions and imports establish the module's public
        # surface and its inbound bindings.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
                functions[node.name] = self._signature(node, src.name, path)
            elif isinstance(node, ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    defined.update(self._assign_names(target))
            elif isinstance(node, ast.AnnAssign):
                defined.update(self._assign_names(node.target))
            elif isinstance(node, ast.ImportFrom):
                new_bindings = self._import_from_bindings(node)
                imports.extend(new_bindings)
                for binding in new_bindings:
                    defined.add(binding.local_name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    defined.add(local)
                    imports.append(
                        ImportBinding(
                            local_name=local,
                            source_module=alias.name,
                            symbol="",
                            line=node.lineno,
                            is_module_import=True,
                        )
                    )

        calls = self._collect_calls(tree)

        return _ModuleFacts(
            module=src.name,
            path=path,
            defined_names=frozenset(defined),
            functions=functions,
            imports=tuple(imports),
            calls=tuple(calls),
        )

    @staticmethod
    def _assign_names(target: ast.expr) -> set[str]:
        names: set[str] = set()
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                if isinstance(elt, ast.Name):
                    names.add(elt.id)
        return names

    @staticmethod
    def _import_from_bindings(node: ast.ImportFrom) -> list[ImportBinding]:
        # Only absolute `from module import ...` is resolvable here. Relative
        # imports (node.level > 0) or `import *` cannot be matched against the
        # reviewed module names, so they are recorded but never resolved.
        module = node.module or ""
        bindings: list[ImportBinding] = []
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            bindings.append(
                ImportBinding(
                    local_name=local,
                    source_module=module,
                    symbol=alias.name,
                    line=node.lineno,
                    is_module_import=False,
                )
            )
        return bindings

    @staticmethod
    def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef, module: str, path: str) -> FunctionSignature:
        args = node.args
        positional = [a.arg for a in (*args.posonlyargs, *args.args)]
        num_required = len(positional) - len(args.defaults)
        if num_required < 0:
            num_required = 0
        required_kwonly = [a.arg for a, default in zip(args.kwonlyargs, args.kw_defaults) if default is None]
        return FunctionSignature(
            name=node.name,
            module=module,
            path=path,
            line=node.lineno,
            positional=tuple(positional),
            num_required_positional=num_required,
            has_vararg=args.vararg is not None,
            required_kwonly=tuple(required_kwonly),
            accepts_kwargs=args.kwarg is not None,
        )

    @staticmethod
    def _collect_calls(tree: ast.AST) -> list[CallSite]:
        calls: list[CallSite] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            positional = 0
            has_star = False
            for arg in node.args:
                if isinstance(arg, ast.Starred):
                    has_star = True
                else:
                    positional += 1
            keyword_names: set[str] = set()
            has_kwargs_unpack = False
            for kw in node.keywords:
                if kw.arg is None:
                    has_kwargs_unpack = True
                else:
                    keyword_names.add(kw.arg)

            local_name = ""
            attr_base = ""
            attr_name = ""
            func = node.func
            if isinstance(func, ast.Name):
                local_name = func.id
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                attr_base = func.value.id
                attr_name = func.attr

            calls.append(
                CallSite(
                    line=node.lineno,
                    positional_count=positional,
                    keyword_names=frozenset(keyword_names),
                    has_star_args=has_star,
                    has_kwargs_unpack=has_kwargs_unpack,
                    local_name=local_name,
                    attr_base=attr_base,
                    attr_name=attr_name,
                )
            )
        return calls

    # -- review ------------------------------------------------------------

    def review(self, sources: Iterable[ModuleSource]) -> list[Finding]:
        """Review ``sources`` and return findings in a deterministic order."""
        index = self.build_index(sources)
        findings: list[Finding] = []
        for invariant in self._invariants:
            findings.extend(invariant.evaluate(index))
        findings.sort(key=Finding.sort_key)
        return findings


def review_sources(
    sources: Mapping[str, str] | Iterable[ModuleSource],
    *,
    invariants: Sequence[Invariant] | None = None,
    forbidden_edges: Iterable[tuple[str, str]] = (),
) -> list[Finding]:
    """Convenience entry point.

    ``sources`` may be a ``{module_name: source_text}`` mapping or an iterable
    of :class:`ModuleSource`. When ``invariants`` is not given, the built-in
    set is used and ``forbidden_edges`` seeds its dependency-direction check.
    """
    if isinstance(sources, Mapping):
        module_sources: list[ModuleSource] = [ModuleSource(name=name, source=text) for name, text in sources.items()]
    else:
        module_sources = list(sources)

    if invariants is None:
        invariants = default_invariants(forbidden_edges)
    reviewer = ContextAwareReviewer(invariants)
    return reviewer.review(module_sources)
