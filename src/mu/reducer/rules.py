"""Transformation rules for MU reduction."""

from __future__ import annotations

from dataclasses import dataclass, field

from mu.parser.models import FunctionDef, ImportDef, ParameterDef
from mu.reducer.stdlib import (
    get_stdlib_prefixes,
    is_stdlib_import,
)


@dataclass
class TransformationRules:
    """Configuration for what to strip and keep during reduction.

    Based on MU spec:
    - STRIP: imports, boilerplate, defensive code, verbose logging, object mapping, syntax keywords
    - KEEP: signatures, dependencies, state mutations, control flow, external I/O, business rules, transactions

    Args:
        language: Optional language hint for language-aware stdlib detection.
            If provided, only stdlib for that language is used.
            If None, all known stdlib prefixes are used (backwards compatible).
            Supported: python, typescript, javascript, csharp, go, rust, java, kotlin, etc.
    """

    # Import filtering
    strip_stdlib_imports: bool = True
    strip_relative_imports: bool = False
    keep_external_deps: bool = True

    # Language hint for stdlib detection (None = use all known stdlibs)
    language: str | None = None

    # Custom stdlib prefixes (for user overrides or extension)
    # If not provided, uses language-aware detection from stdlib.py
    stdlib_prefixes: list[str] | None = None

    # Method filtering
    strip_dunder_methods: bool = True  # __str__, __repr__, etc.
    keep_dunder_methods: list[str] = field(
        default_factory=lambda: [
            "__init__",
            "__call__",
            "__enter__",
            "__exit__",
            "__aenter__",
            "__aexit__",
            "__iter__",
            "__next__",
        ]
    )
    strip_property_getters: bool = True  # Simple property accessors
    strip_empty_methods: bool = True

    # Parameter filtering
    strip_self_parameter: bool = True
    strip_cls_parameter: bool = True
    strip_this_parameter: bool = True  # TypeScript

    # Complexity thresholds
    complexity_threshold_for_llm: int = 20  # AST nodes before suggesting LLM summary
    min_method_complexity: int = 3  # Skip trivial methods (just return/pass)

    # Annotation preferences
    include_docstrings: bool = False  # Keep docstrings in output
    include_decorators: bool = True
    include_type_annotations: bool = True
    include_default_values: bool = False  # Parameter defaults

    # Special annotations to generate
    annotate_transactions: bool = True  # !transaction: atomic
    annotate_side_effects: bool = True  # DB writes, file ops, API calls
    annotate_complexity_warnings: bool = True  # O(n²), race conditions

    def should_strip_import(self, imp: ImportDef) -> bool:
        """Determine if an import should be stripped."""
        if not imp.module:
            return True

        # Strip relative imports if configured (check first)
        if self.strip_relative_imports and imp.module.startswith("."):
            return True

        # Strip stdlib if configured
        if self.strip_stdlib_imports and self._is_stdlib(imp.module):
            return True

        # Keep external dependencies (non-stdlib, non-relative)
        if self.keep_external_deps:
            if not self._is_stdlib(imp.module) and not imp.module.startswith("."):
                return False

        return False

    def _is_stdlib(self, module: str, language: str | None = None) -> bool:
        """Check if module is part of standard library.

        Args:
            module: The module name to check (e.g., "os", "os.path", "System.IO")
            language: Optional language override. If not provided, uses self.language.

        Returns:
            True if the module is considered part of the standard library.
        """
        # Use custom prefixes if provided (backwards compatibility for explicit overrides)
        if self.stdlib_prefixes is not None:
            base = module.split(".")[0]
            return any(
                base == prefix or base.startswith(prefix + ".")
                for prefix in self.stdlib_prefixes
            )

        # Use language-aware detection from stdlib module
        effective_language = language or self.language
        return is_stdlib_import(module, effective_language)

    def get_stdlib_prefixes(self) -> frozenset[str]:
        """Get the effective stdlib prefixes for the current configuration.

        Returns:
            FrozenSet of stdlib module prefixes.
        """
        if self.stdlib_prefixes is not None:
            return frozenset(self.stdlib_prefixes)
        return get_stdlib_prefixes(self.language)

    def should_strip_method(self, method: FunctionDef) -> bool:
        """Determine if a method should be stripped."""
        # Strip dunder methods (except kept ones)
        if method.name.startswith("__") and method.name.endswith("__"):
            if self.strip_dunder_methods and method.name not in self.keep_dunder_methods:
                return True

        # Strip simple property getters
        if self.strip_property_getters and method.is_property:
            if method.body_complexity <= 3:  # Just return self.x
                return True

        # Strip empty/trivial methods
        if self.strip_empty_methods and method.body_complexity <= self.min_method_complexity:
            return True

        return False

    def should_strip_function(self, func: FunctionDef) -> bool:
        """Determine if a top-level function should be stripped."""
        # Strip trivial functions
        if self.strip_empty_methods and func.body_complexity <= self.min_method_complexity:
            return True
        return False

    def filter_parameters(
        self, params: list[ParameterDef], is_method: bool = False
    ) -> list[ParameterDef]:
        """Filter parameters based on rules."""
        result = []
        for param in params:
            # Strip self/cls/this
            if is_method:
                if self.strip_self_parameter and param.name == "self":
                    continue
                if self.strip_cls_parameter and param.name == "cls":
                    continue
                if self.strip_this_parameter and param.name == "this":
                    continue
            result.append(param)
        return result

    def needs_llm_summary(self, func: FunctionDef) -> bool:
        """Check if function complexity warrants LLM summarization."""
        return func.body_complexity >= self.complexity_threshold_for_llm


# Predefined rule sets
AGGRESSIVE_RULES = TransformationRules(
    strip_stdlib_imports=True,
    strip_relative_imports=True,
    strip_dunder_methods=True,
    strip_property_getters=True,
    strip_empty_methods=True,
    include_docstrings=False,
    include_default_values=False,
    min_method_complexity=5,
)

CONSERVATIVE_RULES = TransformationRules(
    strip_stdlib_imports=False,
    strip_relative_imports=False,
    strip_dunder_methods=False,
    strip_property_getters=False,
    strip_empty_methods=False,
    include_docstrings=True,
    include_default_values=True,
    min_method_complexity=1,
)

DEFAULT_RULES = TransformationRules()
