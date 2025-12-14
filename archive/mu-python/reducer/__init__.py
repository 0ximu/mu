"""MU Reducer - Transform parsed AST into semantic MU format."""

from mu.reducer.generator import MUGenerator, reduce_codebase, reduce_module
from mu.reducer.rules import TransformationRules
from mu.reducer.stdlib import (
    STDLIB_BY_LANGUAGE,
    get_stdlib_prefixes,
    get_supported_languages,
    is_stdlib_import,
)

__all__ = [
    "TransformationRules",
    "MUGenerator",
    "reduce_module",
    "reduce_codebase",
    # Stdlib detection utilities
    "is_stdlib_import",
    "get_stdlib_prefixes",
    "get_supported_languages",
    "STDLIB_BY_LANGUAGE",
]
