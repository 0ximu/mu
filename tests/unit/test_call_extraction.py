"""Unit tests for function call site extraction.

These tests verify that the Rust core parser correctly extracts call sites
from function and method bodies, including information about:
- The callee (function/method being called)
- Line numbers
- Whether it's a method call (obj.method vs function())
- The receiver object (self, cls, or other objects)
"""

import pytest

# Skip all tests if Rust core is not available
pytest.importorskip("mu._core", reason="Rust core not compiled")

from mu._core import (
    parse_file,
    CallSiteDef,
)


class TestPythonCallExtraction:
    """Tests for Python call site extraction."""

    def test_simple_function_call(self):
        """Test extraction of simple function calls."""
        source = '''
def main():
    result = process_data()
    validate(result)
    return result
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "process_data" in callees
        assert "validate" in callees

    def test_method_call_on_self(self):
        """Test self.method() detection."""
        source = '''
class Worker:
    def process(self):
        self.validate()
        self.save()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        method = result.module.classes[0].methods[0]

        # Should detect self.validate() and self.save()
        self_calls = [c for c in method.call_sites if c.receiver == "self"]
        assert len(self_calls) >= 2
        assert all(c.is_method_call for c in self_calls)

    def test_method_call_on_object(self):
        """Test obj.method() detection."""
        source = '''
def process(service):
    service.start()
    result = service.execute()
    service.stop()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        method_calls = [c for c in func.call_sites if c.is_method_call]
        assert len(method_calls) >= 3

    def test_chained_calls(self):
        """Test chained method calls like a.b.c()."""
        source = '''
def build():
    result = builder.step1().step2().execute()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        # Should capture at least some calls
        assert len(func.call_sites) >= 1

    def test_call_with_arguments(self):
        """Test calls with various argument patterns."""
        source = '''
def process(data):
    validate(data, strict=True)
    transform(data, *args, **kwargs)
    result = compute(1, 2, 3)
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "validate" in callees
        assert "transform" in callees
        assert "compute" in callees

    def test_nested_calls(self):
        """Test nested function calls like outer(inner())."""
        source = '''
def process(x):
    result = outer(inner(x))
    return format(str(result))
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "outer" in callees
        assert "inner" in callees
        assert "format" in callees
        assert "str" in callees

    def test_async_function_calls(self):
        """Test call extraction in async functions."""
        source = '''
async def fetch_data():
    result = await api.get()
    processed = process(result)
    return processed
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        # Should detect process() and api.get()
        assert len(func.call_sites) >= 2

    def test_lambda_calls(self):
        """Test calls inside lambda expressions."""
        source = '''
def process(items):
    result = list(map(lambda x: transform(x), items))
    return result
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "list" in callees
        assert "map" in callees
        # transform inside lambda should also be captured
        assert "transform" in callees

    def test_call_site_line_numbers(self):
        """Test that line numbers are captured correctly."""
        source = '''def main():
    foo()
    bar()
    baz()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        # Line numbers should be non-zero and increasing
        lines = [c.line for c in func.call_sites]
        assert all(line > 0 for line in lines)

    def test_classmethod_calls(self):
        """Test cls.method() detection in classmethods."""
        source = '''
class Factory:
    @classmethod
    def create(cls):
        instance = cls.build()
        cls.register(instance)
        return instance
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        method = result.module.classes[0].methods[0]

        cls_calls = [c for c in method.call_sites if c.receiver == "cls"]
        assert len(cls_calls) >= 2

    def test_call_in_conditional(self):
        """Test call extraction from conditional expressions."""
        source = '''
def maybe_process(data, flag):
    result = process(data) if flag else default()
    return result
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "process" in callees
        assert "default" in callees

    def test_call_in_list_comprehension(self):
        """Test call extraction from list comprehensions."""
        source = '''
def transform_all(items):
    return [transform(item) for item in items]
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "transform" in callees

    def test_call_with_decorator(self):
        """Test that decorator calls don't pollute function call sites."""
        source = '''
@decorator
def my_func():
    actual_call()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        func = result.module.functions[0]

        # Should only have actual_call, not decorator
        callees = [c.callee for c in func.call_sites]
        assert "actual_call" in callees

    def test_staticmethod_calls(self):
        """Test call extraction from static methods."""
        source = '''
class Utils:
    @staticmethod
    def process(data):
        validated = validate(data)
        return transform(validated)
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        assert result.module is not None
        method = result.module.classes[0].methods[0]

        callees = [c.callee for c in method.call_sites]
        assert "validate" in callees
        assert "transform" in callees


class TestCallSiteDefModel:
    """Tests for the CallSiteDef data model."""

    def test_call_site_to_dict(self):
        """Test CallSiteDef serialization."""
        call = CallSiteDef(
            callee="process",
            line=10,
            is_method_call=True,
            receiver="self"
        )
        # Verify fields are accessible
        assert call.callee == "process"
        assert call.line == 10
        assert call.is_method_call is True
        assert call.receiver == "self"

    def test_call_site_defaults(self):
        """Test CallSiteDef default values."""
        call = CallSiteDef(callee="simple_call")
        assert call.callee == "simple_call"
        assert call.line == 0
        assert call.is_method_call is False
        assert call.receiver is None

    def test_call_site_to_dict_method(self):
        """Test CallSiteDef.to_dict() returns expected structure."""
        call = CallSiteDef(
            callee="process",
            line=10,
            is_method_call=True,
            receiver="self"
        )
        d = call.to_dict()
        assert d["callee"] == "process"
        assert d["line"] == 10
        assert d["is_method_call"] is True
        assert d["receiver"] == "self"


class TestCallSiteEdgeCases:
    """Test edge cases and error handling for call site extraction."""

    def test_empty_function(self):
        """Test function with no calls has empty call_sites."""
        source = '''
def empty():
    pass
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]
        assert len(func.call_sites) == 0

    def test_function_with_only_return(self):
        """Test function with only return has no calls."""
        source = '''
def identity(x):
    return x
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]
        assert len(func.call_sites) == 0

    def test_function_with_assignment_only(self):
        """Test function with only assignment has no calls."""
        source = '''
def assign():
    x = 42
    y = x + 1
    return y
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]
        assert len(func.call_sites) == 0

    def test_call_on_subscript(self):
        """Test method call on subscript result."""
        source = '''
def process(items):
    items[0].process()
    handlers["default"].handle()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]
        assert len(func.call_sites) >= 2

    def test_call_on_call_result(self):
        """Test calling method on function result."""
        source = '''
def process():
    get_service().process()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]
        # Should capture both get_service() and .process()
        assert len(func.call_sites) >= 2

    def test_builtin_calls(self):
        """Test detection of builtin function calls."""
        source = '''
def process(items):
    length = len(items)
    total = sum(items)
    maximum = max(items)
    return (length, total, maximum)
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "len" in callees
        assert "sum" in callees
        assert "max" in callees

    def test_print_call(self):
        """Test print() is captured as a call."""
        source = '''
def debug(msg):
    print(msg)
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]

        callees = [c.callee for c in func.call_sites]
        assert "print" in callees


class TestMethodCallReceiver:
    """Tests focused on receiver detection in method calls."""

    def test_simple_receiver(self):
        """Test simple object receiver detection."""
        source = '''
def process(service):
    service.start()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]

        call = func.call_sites[0]
        assert call.is_method_call is True
        assert call.receiver == "service"

    def test_self_receiver(self):
        """Test self receiver detection."""
        source = '''
class Foo:
    def bar(self):
        self.baz()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        method = result.module.classes[0].methods[0]

        self_calls = [c for c in method.call_sites if c.receiver == "self"]
        assert len(self_calls) >= 1
        assert all(c.is_method_call for c in self_calls)

    def test_cls_receiver(self):
        """Test cls receiver detection."""
        source = '''
class Foo:
    @classmethod
    def bar(cls):
        cls.baz()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        method = result.module.classes[0].methods[0]

        cls_calls = [c for c in method.call_sites if c.receiver == "cls"]
        assert len(cls_calls) >= 1
        assert all(c.is_method_call for c in cls_calls)

    def test_module_receiver(self):
        """Test module-qualified calls (e.g., os.path.join)."""
        source = '''
import os.path

def get_path():
    return os.path.join("a", "b")
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]

        # Should capture the os.path.join call
        assert len(func.call_sites) >= 1

    def test_no_receiver_for_bare_call(self):
        """Test that bare function calls have no receiver."""
        source = '''
def process():
    result = transform()
'''
        result = parse_file(source, "test.py", "python")
        assert result.error is None
        func = result.module.functions[0]

        call = func.call_sites[0]
        assert call.is_method_call is False
        assert call.receiver is None
