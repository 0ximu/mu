"""MU Parser - Tree-sitter based AST extraction.

Uses Rust core for parsing when available (2-5x faster).
Set MU_DISABLE_RUST_CORE=1 to force Python implementation.
"""

from mu.parser.base import ParsedFile, parse_file, use_rust_core
from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)

__all__ = [
    "parse_file",
    "ParsedFile",
    "ClassDef",
    "FunctionDef",
    "ImportDef",
    "ParameterDef",
    "ModuleDef",
    "use_rust_core",
]
