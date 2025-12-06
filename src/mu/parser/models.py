"""Data models for parsed AST elements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterDef:
    """A function/method parameter."""

    name: str
    type_annotation: str | None = None
    default_value: str | None = None
    is_variadic: bool = False  # *args
    is_keyword: bool = False   # **kwargs

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_annotation,
            "default": self.default_value,
            "variadic": self.is_variadic,
            "keyword": self.is_keyword,
        }


@dataclass
class FunctionDef:
    """A function or method definition."""

    name: str
    parameters: list[ParameterDef] = field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    is_method: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_property: bool = False
    docstring: str | None = None
    body_complexity: int = 0  # AST node count in body
    body_source: str | None = None  # Raw source code of function body (for LLM summarization)
    start_line: int = 0
    end_line: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "parameters": [p.to_dict() for p in self.parameters],
            "return_type": self.return_type,
            "decorators": self.decorators,
            "is_async": self.is_async,
            "is_method": self.is_method,
            "is_static": self.is_static,
            "is_classmethod": self.is_classmethod,
            "is_property": self.is_property,
            "docstring": self.docstring,
            "body_complexity": self.body_complexity,
            "lines": [self.start_line, self.end_line],
        }
        # Only include body_source if present (avoid bloating JSON output)
        if self.body_source:
            result["body_source"] = self.body_source
        return result


@dataclass
class ClassDef:
    """A class definition."""

    name: str
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    methods: list[FunctionDef] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    docstring: str | None = None
    start_line: int = 0
    end_line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bases": self.bases,
            "decorators": self.decorators,
            "methods": [m.to_dict() for m in self.methods],
            "attributes": self.attributes,
            "docstring": self.docstring,
            "lines": [self.start_line, self.end_line],
        }


@dataclass
class ImportDef:
    """An import statement."""

    module: str
    names: list[str] = field(default_factory=list)  # Empty = import whole module
    alias: str | None = None
    is_from: bool = False  # from x import y vs import x
    is_dynamic: bool = False  # True for runtime imports (importlib, dynamic import())
    dynamic_pattern: str | None = None  # Pattern/expression used (e.g., "f'plugins.{name}'")
    dynamic_source: str | None = None  # Detection method: "importlib", "__import__", "import()", "require()"
    line_number: int = 0  # Source line for reference

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "module": self.module,
            "names": self.names,
            "alias": self.alias,
            "is_from": self.is_from,
        }
        if self.is_dynamic:
            result["is_dynamic"] = True
            if self.dynamic_pattern:
                result["dynamic_pattern"] = self.dynamic_pattern
            if self.dynamic_source:
                result["dynamic_source"] = self.dynamic_source
            if self.line_number:
                result["line"] = self.line_number
        return result


@dataclass
class ModuleDef:
    """A module/file definition."""

    name: str
    path: str
    language: str
    imports: list[ImportDef] = field(default_factory=list)
    classes: list[ClassDef] = field(default_factory=list)
    functions: list[FunctionDef] = field(default_factory=list)
    module_docstring: str | None = None
    total_lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "language": self.language,
            "imports": [i.to_dict() for i in self.imports],
            "classes": [c.to_dict() for c in self.classes],
            "functions": [f.to_dict() for f in self.functions],
            "module_docstring": self.module_docstring,
            "total_lines": self.total_lines,
        }
