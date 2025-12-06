"""Tests for MU reducer."""

import pytest
from pathlib import Path

from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)
from mu.reducer.rules import (
    TransformationRules,
    DEFAULT_RULES,
    AGGRESSIVE_RULES,
    CONSERVATIVE_RULES,
)
from mu.reducer.generator import (
    reduce_module,
    reduce_codebase,
    MUGenerator,
    generate_mu,
)


class TestTransformationRules:
    """Test transformation rules."""

    def test_should_strip_stdlib_import(self):
        """Test stdlib import stripping."""
        rules = TransformationRules(strip_stdlib_imports=True)

        # Should strip stdlib
        os_import = ImportDef(module="os", names=[], is_from=False)
        assert rules.should_strip_import(os_import)

        sys_import = ImportDef(module="sys", names=[], is_from=False)
        assert rules.should_strip_import(sys_import)

        # Should keep external
        requests_import = ImportDef(module="requests", names=[], is_from=False)
        assert not rules.should_strip_import(requests_import)

    def test_should_keep_external_deps(self):
        """Test external dependency preservation."""
        rules = TransformationRules(keep_external_deps=True)

        flask_import = ImportDef(module="flask", names=["Flask"], is_from=True)
        assert not rules.should_strip_import(flask_import)

        django_import = ImportDef(module="django.db", names=["models"], is_from=True)
        assert not rules.should_strip_import(django_import)

    def test_should_strip_dunder_method(self):
        """Test dunder method stripping."""
        rules = TransformationRules(strip_dunder_methods=True)

        # Should strip __repr__
        repr_method = FunctionDef(name="__repr__", body_complexity=5)
        assert rules.should_strip_method(repr_method)

        # Should keep __init__
        init_method = FunctionDef(name="__init__", body_complexity=10)
        assert not rules.should_strip_method(init_method)

    def test_should_strip_trivial_property(self):
        """Test trivial property stripping."""
        rules = TransformationRules(strip_property_getters=True)

        # Trivial getter (just return self.x)
        getter = FunctionDef(name="name", is_property=True, body_complexity=2)
        assert rules.should_strip_method(getter)

        # Complex property
        complex_prop = FunctionDef(name="computed_value", is_property=True, body_complexity=15)
        assert not rules.should_strip_method(complex_prop)

    def test_filter_self_parameter(self):
        """Test self/cls parameter filtering."""
        rules = TransformationRules(strip_self_parameter=True, strip_cls_parameter=True)

        params = [
            ParameterDef(name="self"),
            ParameterDef(name="x", type_annotation="int"),
            ParameterDef(name="y", type_annotation="int"),
        ]

        filtered = rules.filter_parameters(params, is_method=True)
        assert len(filtered) == 2
        assert filtered[0].name == "x"
        assert filtered[1].name == "y"

    def test_needs_llm_summary(self):
        """Test LLM summary threshold."""
        rules = TransformationRules(complexity_threshold_for_llm=20)

        simple_func = FunctionDef(name="simple", body_complexity=10)
        assert not rules.needs_llm_summary(simple_func)

        complex_func = FunctionDef(name="complex", body_complexity=50)
        assert rules.needs_llm_summary(complex_func)


class TestReduceModule:
    """Test module reduction."""

    def test_reduce_module_filters_imports(self):
        """Test that module reduction filters imports."""
        module = ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[
                ImportDef(module="os", names=[], is_from=False),
                ImportDef(module="requests", names=[], is_from=False),
            ],
        )

        rules = TransformationRules(strip_stdlib_imports=True)
        reduced = reduce_module(module, rules)

        assert len(reduced.imports) == 1
        assert reduced.imports[0].module == "requests"

    def test_reduce_module_filters_methods(self):
        """Test that module reduction filters methods."""
        module = ModuleDef(
            name="test",
            path="test.py",
            language="python",
            classes=[
                ClassDef(
                    name="TestClass",
                    methods=[
                        FunctionDef(name="__init__", body_complexity=10),
                        FunctionDef(name="__repr__", body_complexity=5),
                        FunctionDef(name="process", body_complexity=20),
                    ],
                ),
            ],
        )

        rules = TransformationRules(strip_dunder_methods=True)
        reduced = reduce_module(module, rules)

        assert len(reduced.classes) == 1
        methods = reduced.classes[0].methods
        assert len(methods) == 2
        method_names = [m.name for m in methods]
        assert "__init__" in method_names
        assert "process" in method_names
        assert "__repr__" not in method_names

    def test_reduce_module_tracks_llm_needs(self):
        """Test that complex functions are flagged for LLM."""
        module = ModuleDef(
            name="test",
            path="test.py",
            language="python",
            functions=[
                FunctionDef(name="simple", body_complexity=10),
                FunctionDef(name="complex", body_complexity=50),
            ],
        )

        rules = TransformationRules(complexity_threshold_for_llm=20)
        reduced = reduce_module(module, rules)

        assert "complex" in reduced.needs_llm
        assert "simple" not in reduced.needs_llm


class TestMUGenerator:
    """Test MU output generation."""

    def test_generate_header(self):
        """Test MU header generation."""
        from mu.reducer.generator import ReducedCodebase, ReducedModule

        codebase = ReducedCodebase(
            source="/path/to/code",
            modules=[ReducedModule(name="test", path="test.py", language="python")],
            stats={"total_modules": 1, "total_classes": 0, "total_functions": 0, "total_methods": 0},
        )

        generator = MUGenerator()
        output = generator.generate(codebase)

        assert "# MU v1.0" in output
        assert "source: /path/to/code" in output
        assert "modules: 1" in output

    def test_generate_class(self):
        """Test class generation."""
        from mu.reducer.generator import ReducedCodebase, ReducedModule

        module = ReducedModule(
            name="test",
            path="test.py",
            language="python",
            classes=[
                ClassDef(
                    name="Calculator",
                    bases=["BaseCalculator"],
                    decorators=["dataclass"],
                    methods=[
                        FunctionDef(
                            name="add",
                            parameters=[
                                ParameterDef(name="x", type_annotation="int"),
                                ParameterDef(name="y", type_annotation="int"),
                            ],
                            return_type="int",
                        ),
                    ],
                ),
            ],
        )

        codebase = ReducedCodebase(source="/test", modules=[module])
        generator = MUGenerator()
        output = generator.generate(codebase)

        assert "$@dataclass Calculator < BaseCalculator" in output
        assert "#add(x: int, y: int) -> int" in output

    def test_generate_async_function(self):
        """Test async function generation."""
        from mu.reducer.generator import ReducedCodebase, ReducedModule

        module = ReducedModule(
            name="test",
            path="test.py",
            language="python",
            functions=[
                FunctionDef(
                    name="fetch_data",
                    is_async=True,
                    parameters=[ParameterDef(name="url", type_annotation="str")],
                    return_type="dict",
                ),
            ],
        )

        codebase = ReducedCodebase(source="/test", modules=[module])
        generator = MUGenerator()
        output = generator.generate(codebase)

        assert "#async fetch_data(url: str) -> dict" in output

    def test_shell_safe_mode(self):
        """Test shell-safe sigil escaping."""
        from mu.reducer.generator import ReducedCodebase, ReducedModule

        module = ReducedModule(name="test", path="test.py", language="python")
        codebase = ReducedCodebase(source="/test", modules=[module])

        generator = MUGenerator(shell_safe=True)
        output = generator.generate(codebase)

        # Shell-safe mode escapes # and $
        assert "\\#" in output or "\\$" in output


class TestGenerateMU:
    """Test the convenience generate_mu function."""

    def test_generate_mu_end_to_end(self):
        """Test full MU generation pipeline."""
        modules = [
            ModuleDef(
                name="auth",
                path="auth.py",
                language="python",
                imports=[
                    ImportDef(module="os", is_from=False),
                    ImportDef(module="jwt", is_from=False),
                ],
                classes=[
                    ClassDef(
                        name="AuthService",
                        methods=[
                            FunctionDef(
                                name="__init__",
                                parameters=[
                                    ParameterDef(name="self"),
                                    ParameterDef(name="secret", type_annotation="str"),
                                ],
                                body_complexity=5,
                            ),
                            FunctionDef(
                                name="authenticate",
                                parameters=[
                                    ParameterDef(name="self"),
                                    ParameterDef(name="token", type_annotation="str"),
                                ],
                                return_type="User",
                                body_complexity=25,
                            ),
                        ],
                    ),
                ],
            ),
        ]

        output = generate_mu(modules, Path("/project"))

        # Check structure
        assert "# MU v1.0" in output
        assert "!module auth" in output
        assert "@deps [jwt]" in output  # os stripped as stdlib
        assert "$AuthService" in output
        assert "#__init__(secret: str)" in output  # self stripped
        assert "#authenticate(token: str) -> User" in output


class TestRulePresets:
    """Test predefined rule presets."""

    def test_aggressive_rules(self):
        """Test aggressive rules strip more."""
        module = ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[
                ImportDef(module="os", is_from=False),
                ImportDef(module=".utils", is_from=True),
            ],
            functions=[
                FunctionDef(name="trivial", body_complexity=3),
                FunctionDef(name="important", body_complexity=20),
            ],
        )

        reduced = reduce_module(module, AGGRESSIVE_RULES)

        # Both imports stripped
        assert len(reduced.imports) == 0
        # Only important function kept
        assert len(reduced.functions) == 1
        assert reduced.functions[0].name == "important"

    def test_conservative_rules(self):
        """Test conservative rules keep more."""
        module = ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[
                ImportDef(module="os", is_from=False),
                ImportDef(module=".utils", is_from=True),
            ],
            classes=[
                ClassDef(
                    name="Test",
                    methods=[
                        FunctionDef(name="__repr__", body_complexity=5),
                    ],
                ),
            ],
        )

        reduced = reduce_module(module, CONSERVATIVE_RULES)

        # Imports kept
        assert len(reduced.imports) == 2
        # Dunder method kept
        assert len(reduced.classes[0].methods) == 1
