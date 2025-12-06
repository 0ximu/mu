"""MU format generator - transforms parsed AST into MU output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mu.parser.models import ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef
from mu.reducer.rules import TransformationRules, DEFAULT_RULES


@dataclass
class ReducedModule:
    """A module after applying transformation rules."""

    name: str
    path: str
    language: str
    imports: list[ImportDef] = field(default_factory=list)
    classes: list[ClassDef] = field(default_factory=list)
    functions: list[FunctionDef] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)  # Special notes
    needs_llm: list[str] = field(default_factory=list)  # Functions needing LLM summary
    summaries: dict[str, list[str]] = field(default_factory=dict)  # LLM-generated summaries: func_name -> bullets


@dataclass
class DynamicDependency:
    """A dynamic/runtime dependency that couldn't be fully resolved."""

    module_name: str  # Module containing the dynamic import
    pattern: str | None = None  # The pattern/expression
    source: str | None = None  # Detection method (importlib, import(), etc.)
    line: int = 0  # Source line number
    resolved_target: str | None = None  # If resolvable, the target module name


@dataclass
class ReducedCodebase:
    """A codebase after applying transformation rules."""

    source: str
    modules: list[ReducedModule] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)  # module_name -> [dep_module_names]
    external_packages: list[str] = field(default_factory=list)  # Third-party packages used
    dynamic_dependencies: list[DynamicDependency] = field(default_factory=list)  # Runtime imports
    stats: dict[str, Any] = field(default_factory=dict)


def reduce_module(module: ModuleDef, rules: TransformationRules) -> ReducedModule:
    """Apply transformation rules to a parsed module."""
    reduced = ReducedModule(
        name=module.name,
        path=module.path,
        language=module.language,
    )

    # Filter imports
    for imp in module.imports:
        if not rules.should_strip_import(imp):
            reduced.imports.append(imp)

    # Filter and transform classes
    for cls in module.classes:
        reduced_cls = _reduce_class(cls, rules)
        if reduced_cls.methods or reduced_cls.attributes:  # Keep non-empty classes
            reduced.classes.append(reduced_cls)

            # Check for methods needing LLM summary
            for method in reduced_cls.methods:
                if rules.needs_llm_summary(method):
                    reduced.needs_llm.append(f"{cls.name}.{method.name}")

    # Filter top-level functions
    for func in module.functions:
        if not rules.should_strip_function(func):
            reduced.functions.append(func)
            if rules.needs_llm_summary(func):
                reduced.needs_llm.append(func.name)

    return reduced


def _reduce_class(cls: ClassDef, rules: TransformationRules) -> ClassDef:
    """Apply transformation rules to a class."""
    reduced = ClassDef(
        name=cls.name,
        bases=cls.bases,
        decorators=cls.decorators if rules.include_decorators else [],
        attributes=cls.attributes,
        docstring=cls.docstring if rules.include_docstrings else None,
        start_line=cls.start_line,
        end_line=cls.end_line,
    )

    # Filter methods
    for method in cls.methods:
        if not rules.should_strip_method(method):
            # Filter parameters
            filtered_params = rules.filter_parameters(method.parameters, is_method=True)
            reduced_method = FunctionDef(
                name=method.name,
                parameters=filtered_params,
                return_type=method.return_type if rules.include_type_annotations else None,
                decorators=method.decorators if rules.include_decorators else [],
                is_async=method.is_async,
                is_method=method.is_method,
                is_static=method.is_static,
                is_classmethod=method.is_classmethod,
                is_property=method.is_property,
                docstring=method.docstring if rules.include_docstrings else None,
                body_complexity=method.body_complexity,
                body_source=method.body_source,  # Preserve for LLM summarization
                start_line=method.start_line,
                end_line=method.end_line,
            )
            reduced.methods.append(reduced_method)

    return reduced


def reduce_codebase(
    modules: list[ModuleDef],
    source_path: Path,
    rules: TransformationRules | None = None,
) -> ReducedCodebase:
    """Apply transformation rules to an entire codebase."""
    if rules is None:
        rules = DEFAULT_RULES

    reduced = ReducedCodebase(source=str(source_path.resolve()))

    # Reduce each module
    for module in modules:
        reduced_module = reduce_module(module, rules)
        reduced.modules.append(reduced_module)

        # Build dependency graph
        deps = [imp.module for imp in reduced_module.imports if imp.module]
        if deps:
            reduced.dependency_graph[reduced_module.name] = deps

    # Calculate stats
    reduced.stats = {
        "total_modules": len(reduced.modules),
        "total_classes": sum(len(m.classes) for m in reduced.modules),
        "total_functions": sum(len(m.functions) for m in reduced.modules),
        "total_methods": sum(
            sum(len(c.methods) for c in m.classes)
            for m in reduced.modules
        ),
        "needs_llm_summary": sum(len(m.needs_llm) for m in reduced.modules),
    }

    return reduced


class MUGenerator:
    """Generate MU format output from reduced codebase."""

    # MU Sigils
    SIGIL_MODULE = "!"
    SIGIL_ENTITY = "$"
    SIGIL_FUNCTION = "#"
    SIGIL_METADATA = "@"
    SIGIL_CONDITIONAL = "?"
    SIGIL_ANNOTATION = "::"

    # MU Operators
    OP_FLOW = "->"      # Pure data flow
    OP_MUTATION = "=>"  # State mutation
    OP_MATCH = "|"      # Match/switch
    OP_ITERATE = "~"    # Iteration

    def __init__(self, shell_safe: bool = False):
        self.shell_safe = shell_safe

    def generate(self, codebase: ReducedCodebase) -> str:
        """Generate complete MU output for a codebase."""
        lines = []

        # Header
        lines.extend(self._generate_header(codebase))
        lines.append("")

        # Dependency graph
        if codebase.dependency_graph:
            lines.extend(self._generate_dependency_graph(codebase))
            lines.append("")

        # Modules
        for module in codebase.modules:
            lines.extend(self._generate_module(module))
            lines.append("")

        return "\n".join(lines)

    def _generate_header(self, codebase: ReducedCodebase) -> list[str]:
        """Generate MU header."""
        now = datetime.now(timezone.utc).isoformat()
        stats = codebase.stats

        return [
            f"{self._sigil('SIGIL_FUNCTION')} MU v1.0",
            f"{self._sigil('SIGIL_FUNCTION')} generated: {now}",
            f"{self._sigil('SIGIL_FUNCTION')} source: {codebase.source}",
            f"{self._sigil('SIGIL_FUNCTION')} modules: {stats.get('total_modules', 0)}",
            f"{self._sigil('SIGIL_FUNCTION')} classes: {stats.get('total_classes', 0)}",
            f"{self._sigil('SIGIL_FUNCTION')} functions: {stats.get('total_functions', 0)} + {stats.get('total_methods', 0)} methods",
        ]

    def _generate_dependency_graph(self, codebase: ReducedCodebase) -> list[str]:
        """Generate dependency graph section."""
        lines = [
            f"{self._sigil('SIGIL_FUNCTION')}{self._sigil('SIGIL_FUNCTION')} Module Graph",
        ]

        # Internal dependencies (module -> module within codebase)
        if codebase.dependency_graph:
            for module_name, deps in sorted(codebase.dependency_graph.items()):
                if deps:
                    # Format dependencies with ! prefix for internal modules
                    deps_formatted = [f"{self._sigil('SIGIL_MODULE')}{d}" for d in deps[:5]]
                    deps_str = ", ".join(deps_formatted)
                    if len(deps) > 5:
                        deps_str += f" (+{len(deps) - 5} more)"
                    lines.append(f"{self._sigil('SIGIL_MODULE')}{module_name} {self.OP_FLOW} {deps_str}")

        # External packages summary
        if codebase.external_packages:
            lines.append("")
            lines.append(f"{self._sigil('SIGIL_METADATA')}external [{', '.join(sorted(codebase.external_packages)[:15])}]")
            if len(codebase.external_packages) > 15:
                lines.append(f"  (+{len(codebase.external_packages) - 15} more packages)")

        # Dynamic dependencies summary
        if codebase.dynamic_dependencies:
            lines.append("")
            lines.append(f"{self._sigil('SIGIL_ANNOTATION')} DYNAMIC IMPORTS ({len(codebase.dynamic_dependencies)} detected)")
            for dyn_dep in codebase.dynamic_dependencies[:10]:
                dep_desc = f"  {self._sigil('SIGIL_MODULE')}{dyn_dep.module_name}"
                if dyn_dep.pattern:
                    dep_desc += f" {self.OP_MUTATION}{self._sigil('SIGIL_CONDITIONAL')} {dyn_dep.pattern}"
                elif dyn_dep.resolved_target:
                    dep_desc += f" {self.OP_MUTATION}{self._sigil('SIGIL_CONDITIONAL')} {self._sigil('SIGIL_MODULE')}{dyn_dep.resolved_target}"
                if dyn_dep.source:
                    dep_desc += f" [{dyn_dep.source}]"
                if dyn_dep.line:
                    dep_desc += f" :L{dyn_dep.line}"
                lines.append(dep_desc)
            if len(codebase.dynamic_dependencies) > 10:
                lines.append(f"  (+{len(codebase.dynamic_dependencies) - 10} more dynamic imports)")

        return lines

    def _generate_module(self, module: ReducedModule) -> list[str]:
        """Generate MU output for a single module."""
        lines = [
            f"{self._sigil('SIGIL_MODULE')}module {module.name}",
        ]

        # External dependencies
        external_deps = list(set(
            imp.module for imp in module.imports
            if imp.module and not imp.module.startswith(".")
        ))
        if external_deps:
            deps_str = ", ".join(sorted(external_deps)[:10])
            lines.append(f"{self._sigil('SIGIL_METADATA')}deps [{deps_str}]")

        # Classes
        for cls in module.classes:
            lines.append("")
            lines.extend(self._generate_class(cls, module.summaries))

        # Top-level functions
        for func in module.functions:
            lines.append("")
            lines.append(self._generate_function(func))
            # Add summary if available
            if func.name in module.summaries:
                for bullet in module.summaries[func.name]:
                    lines.append(f"  {self._sigil('SIGIL_ANNOTATION')} {bullet}")

        # Annotations for complex functions that still need LLM summary
        pending_llm = [f for f in module.needs_llm if f not in module.summaries]
        if pending_llm:
            lines.append("")
            lines.append(f"{self._sigil('SIGIL_ANNOTATION')} NOTE: Complex functions needing review: {', '.join(pending_llm)}")

        return lines

    def _generate_class(
        self,
        cls: ClassDef,
        summaries: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """Generate MU output for a class."""
        summaries = summaries or {}
        lines = []

        # Class declaration
        parts = [self._sigil('SIGIL_ENTITY')]

        # Decorators
        if cls.decorators:
            # Filter out visibility modifiers for cleaner output
            visible_decorators = [d for d in cls.decorators if d not in ("public", "private", "protected", "internal")]
            if visible_decorators:
                parts.append(f"{self._sigil('SIGIL_METADATA')}{', '.join(visible_decorators)} ")

        parts.append(cls.name)

        # Inheritance
        if cls.bases:
            parts.append(f" < {', '.join(cls.bases)}")

        lines.append("".join(parts))

        # Attributes (if any significant ones)
        if cls.attributes:
            attrs = ", ".join(cls.attributes[:10])  # Limit to 10
            if len(cls.attributes) > 10:
                attrs += f" (+{len(cls.attributes) - 10} more)"
            lines.append(f"  {self._sigil('SIGIL_METADATA')}attrs [{attrs}]")

        # Methods
        for method in cls.methods:
            method_line = self._generate_function(method, indent=2)
            lines.append(method_line)
            # Add summary if available (keyed as ClassName.method_name)
            summary_key = f"{cls.name}.{method.name}"
            if summary_key in summaries:
                for bullet in summaries[summary_key]:
                    lines.append(f"    {self._sigil('SIGIL_ANNOTATION')} {bullet}")

        return lines

    def _generate_function(self, func: FunctionDef, indent: int = 0) -> str:
        """Generate MU output for a function/method."""
        prefix = " " * indent
        parts = [prefix, self._sigil('SIGIL_FUNCTION')]

        # Modifiers
        if func.is_async:
            parts.append("async ")
        if func.is_static:
            parts.append("static ")
        if func.is_classmethod:
            parts.append("classmethod ")

        # Name
        parts.append(func.name)

        # Parameters
        params = self._format_parameters(func.parameters)
        parts.append(f"({params})")

        # Return type
        if func.return_type:
            parts.append(f" {self.OP_FLOW} {func.return_type}")

        # Complexity annotation for very complex functions
        if func.body_complexity >= 50:
            parts.append(f" {self._sigil('SIGIL_ANNOTATION')} complexity:{func.body_complexity}")

        return "".join(parts)

    def _format_parameters(self, params: list[ParameterDef]) -> str:
        """Format parameter list."""
        formatted = []
        for p in params:
            if p.type_annotation:
                formatted.append(f"{p.name}: {p.type_annotation}")
            else:
                formatted.append(p.name)

            # Add variadic/keyword indicators
            if p.is_variadic:
                formatted[-1] = "*" + formatted[-1]
            elif p.is_keyword:
                formatted[-1] = "**" + formatted[-1]

        return ", ".join(formatted)

    def _sigil(self, sigil_name: str) -> str:
        """Get sigil, optionally escaped for shell safety."""
        sigil = getattr(self, sigil_name, "")
        if self.shell_safe and sigil in ("#", "$", "!", "?"):
            return "\\" + sigil
        return sigil


def generate_mu(
    modules: list[ModuleDef],
    source_path: Path,
    rules: TransformationRules | None = None,
    shell_safe: bool = False,
) -> str:
    """Convenience function to reduce and generate MU in one step."""
    reduced = reduce_codebase(modules, source_path, rules)
    generator = MUGenerator(shell_safe=shell_safe)
    return generator.generate(reduced)
