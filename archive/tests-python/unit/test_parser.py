"""Tests for MU parser."""

import pytest
import tempfile
from pathlib import Path

from mu.parser import parse_file, ParsedFile


class TestPythonParser:
    """Test Python AST extraction."""

    def test_parse_simple_function(self):
        """Test parsing a simple function."""
        code = '''
def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            assert result.module is not None
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "greet"
            assert func.return_type == "str"
            assert len(func.parameters) == 1
            assert func.parameters[0].name == "name"
            assert func.parameters[0].type_annotation == "str"
            assert func.docstring == "Say hello."

    def test_parse_class_with_methods(self):
        """Test parsing a class with methods."""
        code = '''
class Calculator:
    """A simple calculator."""

    def __init__(self, initial: int = 0):
        self.value = initial

    def add(self, x: int) -> int:
        """Add x to value."""
        self.value += x
        return self.value

    @staticmethod
    def multiply(a: int, b: int) -> int:
        return a * b
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            assert cls.name == "Calculator"
            assert cls.docstring == "A simple calculator."
            assert len(cls.methods) == 3

            # Check __init__
            init = next(m for m in cls.methods if m.name == "__init__")
            assert len(init.parameters) == 2  # self, initial
            assert init.parameters[1].default_value == "0"

            # Check static method
            multiply = next(m for m in cls.methods if m.name == "multiply")
            assert multiply.is_static

    def test_parse_imports(self):
        """Test parsing import statements."""
        code = '''
import os
import sys as system
from pathlib import Path
from typing import List, Optional
from . import local_module
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            assert len(result.module.imports) >= 4

            # Check regular import
            os_import = next((i for i in result.module.imports if i.module == "os"), None)
            assert os_import is not None
            assert not os_import.is_from

            # Check aliased import
            sys_import = next((i for i in result.module.imports if i.module == "sys"), None)
            assert sys_import is not None
            assert sys_import.alias == "system"

            # Check from import
            pathlib_import = next((i for i in result.module.imports if i.module == "pathlib"), None)
            assert pathlib_import is not None
            assert pathlib_import.is_from
            assert "Path" in pathlib_import.names

    def test_parse_async_function(self):
        """Test parsing async functions."""
        code = '''
async def fetch_data(url: str) -> dict:
    async with session.get(url) as response:
        return await response.json()
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            assert len(result.module.functions) == 1
            assert result.module.functions[0].is_async

    def test_parse_decorated_class(self):
        """Test parsing decorated classes."""
        code = '''
@dataclass
@frozen
class Point:
    x: int
    y: int
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            assert len(result.module.classes) == 1
            cls = result.module.classes[0]
            assert "dataclass" in cls.decorators
            assert "frozen" in cls.decorators


class TestTypeScriptParser:
    """Test TypeScript/JavaScript AST extraction."""

    def test_parse_simple_function(self):
        """Test parsing a simple TypeScript function."""
        code = '''
function greet(name: string): string {
    return `Hello, ${name}!`;
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "greet"
            assert func.return_type == "string"
            assert len(func.parameters) == 1
            assert func.parameters[0].name == "name"

    def test_parse_class(self):
        """Test parsing a TypeScript class."""
        code = '''
class Calculator {
    private value: number;

    constructor(initial: number = 0) {
        this.value = initial;
    }

    add(x: number): number {
        this.value += x;
        return this.value;
    }

    static multiply(a: number, b: number): number {
        return a * b;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            assert cls.name == "Calculator"
            assert len(cls.methods) >= 2  # constructor, add, multiply

    def test_parse_arrow_function(self):
        """Test parsing arrow functions."""
        code = '''
const add = (a: number, b: number): number => a + b;

const greet = async (name: string): Promise<string> => {
    return `Hello, ${name}!`;
};
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            assert len(result.module.functions) == 2

            add_func = next(f for f in result.module.functions if f.name == "add")
            assert add_func is not None
            assert len(add_func.parameters) == 2

    def test_parse_imports(self):
        """Test parsing import statements."""
        code = '''
import React from 'react';
import { useState, useEffect } from 'react';
import * as utils from './utils';
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            assert len(result.module.imports) == 3

    def test_parse_javascript(self):
        """Test parsing JavaScript (without types)."""
        code = '''
function add(a, b) {
    return a + b;
}

class Counter {
    constructor() {
        this.count = 0;
    }

    increment() {
        this.count++;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "javascript")

            assert result.success
            assert len(result.module.functions) == 1
            assert len(result.module.classes) == 1


class TestCSharpParser:
    """Test C# AST extraction."""

    def test_parse_simple_class(self):
        """Test parsing a simple C# class."""
        code = '''
using System;

namespace MyApp
{
    public class Calculator
    {
        private int _value;

        public Calculator(int initial = 0)
        {
            _value = initial;
        }

        public int Add(int x)
        {
            _value += x;
            return _value;
        }

        public static int Multiply(int a, int b)
        {
            return a * b;
        }
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "csharp")

            assert result.success
            assert len(result.module.imports) >= 1
            assert result.module.imports[0].module == "System"

            assert len(result.module.classes) == 1
            cls = result.module.classes[0]
            assert cls.name == "Calculator"
            assert "public" in cls.decorators
            assert len(cls.methods) >= 3  # constructor, Add, Multiply

    def test_parse_interface(self):
        """Test parsing C# interface."""
        code = '''
public interface ICalculator
{
    int Add(int x);
    int Subtract(int x);
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "csharp")

            assert result.success
            assert len(result.module.classes) == 1
            cls = result.module.classes[0]
            assert cls.name == "ICalculator"
            assert "interface" in cls.decorators

    def test_parse_async_method(self):
        """Test parsing async methods."""
        code = '''
public class ApiClient
{
    public async Task<string> FetchDataAsync(string url)
    {
        using var client = new HttpClient();
        return await client.GetStringAsync(url);
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "csharp")

            assert result.success
            assert len(result.module.classes) == 1
            cls = result.module.classes[0]
            method = next(m for m in cls.methods if m.name == "FetchDataAsync")
            assert method.is_async


class TestGoParser:
    """Test Go AST extraction."""

    def test_parse_simple_function(self):
        """Test parsing a simple Go function."""
        code = '''
package main

func greet(name string) string {
    return "Hello, " + name + "!"
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert result.module is not None
            assert result.module.name == "main"
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "greet"
            assert func.return_type == "string"
            assert len(func.parameters) == 1
            assert func.parameters[0].name == "name"
            assert func.parameters[0].type_annotation == "string"

    def test_parse_exported_function(self):
        """Test that exported functions are marked."""
        code = '''
package utils

func ExportedFunc() {}
func privateFunc() {}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.functions) == 2

            exported = next(f for f in result.module.functions if f.name == "ExportedFunc")
            assert "exported" in exported.decorators

            private = next(f for f in result.module.functions if f.name == "privateFunc")
            assert "exported" not in private.decorators

    def test_parse_struct(self):
        """Test parsing Go struct type."""
        code = '''
package models

type User struct {
    ID        int
    Name      string
    Email     string
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.classes) == 1

            struct = result.module.classes[0]
            assert struct.name == "User"
            assert "struct" in struct.decorators
            assert "exported" in struct.decorators
            assert "ID" in struct.attributes
            assert "Name" in struct.attributes
            assert "Email" in struct.attributes

    def test_parse_interface(self):
        """Test parsing Go interface type."""
        code = '''
package io

type Reader interface {
    Read(p []byte) (n int, err error)
}

type ReadWriter interface {
    Reader
    Write(p []byte) (n int, err error)
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.classes) == 2

            reader = next(c for c in result.module.classes if c.name == "Reader")
            assert "interface" in reader.decorators
            assert len(reader.methods) == 1
            assert reader.methods[0].name == "Read"

            read_writer = next(c for c in result.module.classes if c.name == "ReadWriter")
            assert "interface" in read_writer.decorators
            assert "Reader" in read_writer.bases  # Embedded interface

    def test_parse_method(self):
        """Test parsing methods with receivers."""
        code = '''
package main

type Counter struct {
    value int
}

func (c *Counter) Increment() {
    c.value++
}

func (c Counter) Value() int {
    return c.value
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            # Methods are extracted as functions with is_method=True
            methods = [f for f in result.module.functions if f.is_method]
            assert len(methods) == 2

            increment = next(m for m in methods if m.name == "Increment")
            assert any("receiver:*Counter" in d for d in increment.decorators)

            value = next(m for m in methods if m.name == "Value")
            assert any("receiver:Counter" in d for d in value.decorators)
            assert value.return_type == "int"

    def test_parse_imports(self):
        """Test parsing Go import statements."""
        code = '''
package main

import (
    "fmt"
    "os"
    myio "io"
    _ "net/http/pprof"
)

import "strings"
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.imports) == 5

            # Check regular import
            fmt_import = next((i for i in result.module.imports if i.module == "fmt"), None)
            assert fmt_import is not None
            assert fmt_import.alias is None

            # Check aliased import
            io_import = next((i for i in result.module.imports if i.module == "io"), None)
            assert io_import is not None
            assert io_import.alias == "myio"

            # Check blank import (side-effect only)
            pprof_import = next((i for i in result.module.imports if "pprof" in i.module), None)
            assert pprof_import is not None
            assert pprof_import.alias == "_"

    def test_parse_multiple_return_values(self):
        """Test parsing functions with multiple return values."""
        code = '''
package main

func divide(a, b int) (int, error) {
    if b == 0 {
        return 0, errors.New("division by zero")
    }
    return a / b, nil
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "divide"
            # Parameters a and b share type int
            assert len(func.parameters) == 2
            assert func.return_type is not None  # Multiple returns

    def test_parse_variadic_function(self):
        """Test parsing variadic functions."""
        code = '''
package main

func sum(nums ...int) int {
    total := 0
    for _, n := range nums {
        total += n
    }
    return total
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "sum"
            assert len(func.parameters) == 1
            assert func.parameters[0].is_variadic
            assert func.parameters[0].name == "nums"

    def test_parse_embedded_struct(self):
        """Test parsing struct with embedded types."""
        code = '''
package models

type Base struct {
    ID int
}

type User struct {
    Base
    Name string
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            assert len(result.module.classes) == 2

            user = next(c for c in result.module.classes if c.name == "User")
            assert "Base" in user.bases  # Embedded type
            assert "Name" in user.attributes


class TestRustParser:
    """Test Rust AST extraction."""

    def test_parse_simple_function(self):
        """Test parsing a simple Rust function."""
        code = '''
fn greet(name: &str) -> String {
    format!("Hello, {}!", name)
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert result.module is not None
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "greet"
            assert func.return_type == "String"
            assert len(func.parameters) == 1
            assert func.parameters[0].name == "name"
            assert func.parameters[0].type_annotation == "&str"

    def test_parse_pub_function(self):
        """Test that pub functions are marked."""
        code = '''
pub fn exported_func() -> i32 {
    42
}

fn private_func() {}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.functions) == 2

            exported = next(f for f in result.module.functions if f.name == "exported_func")
            assert "pub" in exported.decorators

            private = next(f for f in result.module.functions if f.name == "private_func")
            assert "pub" not in private.decorators

    def test_parse_async_function(self):
        """Test parsing async functions."""
        code = '''
pub async fn fetch_data(url: &str) -> Result<String, Error> {
    todo!()
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.functions) == 1
            assert result.module.functions[0].is_async

    def test_parse_struct(self):
        """Test parsing Rust struct."""
        code = '''
pub struct User {
    pub name: String,
    age: u32,
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.classes) == 1

            struct = result.module.classes[0]
            assert struct.name == "User"
            assert "struct" in struct.decorators
            assert "pub" in struct.decorators
            assert any("name" in attr for attr in struct.attributes)
            assert any("age" in attr for attr in struct.attributes)

    def test_parse_enum(self):
        """Test parsing Rust enum."""
        code = '''
pub enum Status {
    Active,
    Inactive,
    Pending,
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.classes) == 1

            enum = result.module.classes[0]
            assert enum.name == "Status"
            assert "enum" in enum.decorators
            assert "pub" in enum.decorators
            assert "Active" in enum.attributes
            assert "Inactive" in enum.attributes
            assert "Pending" in enum.attributes

    def test_parse_trait(self):
        """Test parsing Rust trait."""
        code = '''
pub trait Greet {
    fn greet(&self) -> String;
    fn wave(&self) {
        println!("Wave!");
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.classes) == 1

            trait = result.module.classes[0]
            assert trait.name == "Greet"
            assert "trait" in trait.decorators
            assert "pub" in trait.decorators
            assert len(trait.methods) == 2

            greet = next(m for m in trait.methods if m.name == "greet")
            assert greet.return_type == "String"

    def test_parse_impl_block(self):
        """Test parsing impl blocks."""
        code = '''
pub struct Counter {
    value: i32,
}

impl Counter {
    pub fn new() -> Self {
        Self { value: 0 }
    }

    pub fn increment(&mut self) {
        self.value += 1;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.classes) == 1

            struct = result.module.classes[0]
            assert struct.name == "Counter"
            assert len(struct.methods) == 2

            new_method = next(m for m in struct.methods if m.name == "new")
            assert new_method is not None
            assert new_method.return_type == "Self"

            increment = next(m for m in struct.methods if m.name == "increment")
            assert increment is not None

    def test_parse_use_statements(self):
        """Test parsing use statements."""
        code = '''
use std::io::{self, Read, Write};
use std::collections::HashMap;
use crate::parser::models;
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.imports) >= 2

            # Check std::io import with names
            io_import = next((i for i in result.module.imports if "std.io" in i.module), None)
            assert io_import is not None

            # Check HashMap import
            hashmap_import = next((i for i in result.module.imports if "HashMap" in i.module or "collections" in i.module), None)
            assert hashmap_import is not None

    def test_parse_generic_function(self):
        """Test parsing generic functions."""
        code = '''
pub fn identity<T>(value: T) -> T {
    value
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            assert len(result.module.functions) == 1

            func = result.module.functions[0]
            assert func.name == "identity"
            assert any("generic" in d for d in func.decorators)


class TestJavaParser:
    """Test Java AST extraction."""

    def test_parse_simple_class(self):
        """Test parsing a simple Java class."""
        code = '''
package com.example;

public class Calculator {
    private int value;

    public Calculator(int initial) {
        this.value = initial;
    }

    public int add(int x) {
        this.value += x;
        return this.value;
    }

    public static int multiply(int a, int b) {
        return a * b;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert result.module is not None
            assert result.module.name == "com.example"
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            assert cls.name == "Calculator"
            assert "public" in cls.decorators
            assert len(cls.methods) >= 3  # constructor, add, multiply

            # Check static method
            multiply = next((m for m in cls.methods if m.name == "multiply"), None)
            assert multiply is not None
            assert multiply.is_static

    def test_parse_interface(self):
        """Test parsing Java interface."""
        code = '''
public interface Calculator {
    int add(int x);
    int subtract(int x);

    default void reset() {
        // default implementation
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.classes) == 1

            iface = result.module.classes[0]
            assert iface.name == "Calculator"
            assert "interface" in iface.decorators
            assert len(iface.methods) >= 2

    def test_parse_enum(self):
        """Test parsing Java enum."""
        code = '''
public enum Status {
    ACTIVE,
    INACTIVE,
    PENDING
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.classes) == 1

            enum = result.module.classes[0]
            assert enum.name == "Status"
            assert "enum" in enum.decorators
            assert "ACTIVE" in enum.attributes
            assert "INACTIVE" in enum.attributes
            assert "PENDING" in enum.attributes

    def test_parse_imports(self):
        """Test parsing import statements."""
        code = '''
package com.example;

import java.util.List;
import java.util.Map;
import static java.lang.Math.PI;

public class App {}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.imports) >= 2

            # Check List import
            list_import = next((i for i in result.module.imports if "List" in i.module), None)
            assert list_import is not None

            # Check static import
            static_import = next((i for i in result.module.imports if "Math" in i.module), None)
            assert static_import is not None
            assert static_import.alias == "static"

    def test_parse_annotations(self):
        """Test parsing annotated classes."""
        code = '''
@Service
@Transactional
public class UserService {
    @Autowired
    private UserRepository repo;

    public User findById(Long id) {
        return repo.findById(id);
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            assert cls.name == "UserService"
            assert any("@Service" in d for d in cls.decorators)
            assert any("@Transactional" in d for d in cls.decorators)

    def test_parse_generics(self):
        """Test parsing generic classes."""
        code = '''
public class Container<T> {
    private T value;

    public Container(T value) {
        this.value = value;
    }

    public T getValue() {
        return value;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            assert cls.name == "Container"
            assert any("generic" in d for d in cls.decorators)

    def test_parse_extends_implements(self):
        """Test parsing inheritance."""
        code = '''
public class ArrayList<E> extends AbstractList<E> implements List<E>, RandomAccess {
    public E get(int index) {
        return null;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            assert cls.name == "ArrayList"
            assert any("AbstractList" in base for base in cls.bases)
            assert any("List" in base for base in cls.bases)

    def test_parse_varargs(self):
        """Test parsing varargs methods."""
        code = '''
public class Formatter {
    public String format(String pattern, Object... args) {
        return String.format(pattern, args);
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            assert len(result.module.classes) == 1

            cls = result.module.classes[0]
            format_method = next(m for m in cls.methods if m.name == "format")
            assert len(format_method.parameters) == 2

            vararg_param = format_method.parameters[1]
            assert vararg_param.is_variadic
            assert vararg_param.name == "args"


class TestParserErrors:
    """Test parser error handling."""

    def test_file_not_found(self):
        """Test handling of non-existent file."""
        result = parse_file(Path("/nonexistent/file.py"), "python")
        assert not result.success
        assert "not found" in result.error.lower()

    def test_unsupported_language(self):
        """Test handling of unsupported language."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rb", delete=False) as f:
            f.write("puts 'hello'")
            f.flush()

            result = parse_file(Path(f.name), "ruby")
            assert not result.success
            assert "unsupported" in result.error.lower()

    def test_syntax_error_partial_parse(self):
        """Test that syntax errors don't crash the parser."""
        code = '''
def valid_function():
    return 42

def broken_function(
    # Missing closing paren
    pass

def another_valid():
    return 100
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            # Should still parse what it can
            assert result.module is not None
            # At least some functions should be extracted
            assert len(result.module.functions) >= 1


class TestPythonDynamicImports:
    """Test Python dynamic import detection."""

    def test_detect_importlib_import_module_static(self):
        """Test detection of importlib.import_module with static string."""
        code = '''
import importlib

def load_plugin():
    module = importlib.import_module("plugins.auth")
    return module
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "plugins.auth"
            assert dyn.dynamic_source == "importlib"
            assert dyn.line_number > 0

    def test_detect_importlib_import_module_dynamic(self):
        """Test detection of importlib.import_module with dynamic pattern."""
        code = '''
import importlib

def load_plugin(name: str):
    module = importlib.import_module(f"plugins.{name}")
    return module
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            # The f-string is detected but appears as the extracted string value
            # since tree-sitter parses f-string content, not the full f-string expression
            assert "plugins" in dyn.module or (dyn.dynamic_pattern and "plugins" in dyn.dynamic_pattern)
            assert dyn.dynamic_source == "importlib"

    def test_detect_builtin_import(self):
        """Test detection of __import__() calls."""
        code = '''
def load_module(name):
    module = __import__(name)
    return module
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "<dynamic>"
            assert dyn.dynamic_pattern == "name"
            assert dyn.dynamic_source == "__import__"

    def test_detect_builtin_import_static(self):
        """Test detection of __import__() with static string."""
        code = '''
module = __import__("json")
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "json"
            assert dyn.dynamic_source == "__import__"

    def test_detect_multiple_dynamic_imports(self):
        """Test detection of multiple dynamic imports in a file."""
        code = '''
import importlib

def load_plugins():
    auth = importlib.import_module("plugins.auth")
    db = __import__("database")
    handler = importlib.import_module(f"handlers.{handler_type}")
    return auth, db, handler
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 3

            # Check sources
            sources = [d.dynamic_source for d in dynamic_imports]
            assert sources.count("importlib") == 2
            assert sources.count("__import__") == 1

    def test_no_false_positives_regular_imports(self):
        """Test that regular imports are not marked as dynamic."""
        code = '''
import json
from pathlib import Path
from . import utils
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 0


class TestTypeScriptDynamicImports:
    """Test TypeScript/JavaScript dynamic import detection."""

    def test_detect_dynamic_import_static(self):
        """Test detection of dynamic import() with static string."""
        code = '''
async function loadModule() {
    const mod = await import("./utils");
    return mod;
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "./utils"
            assert dyn.dynamic_source == "import()"

    def test_detect_dynamic_import_template_literal(self):
        """Test detection of dynamic import() with template literal."""
        code = '''
async function loadHandler(type) {
    const handler = await import(`./handlers/${type}.js`);
    return handler;
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "<dynamic>"
            assert dyn.dynamic_pattern is not None
            assert "handlers" in dyn.dynamic_pattern
            assert dyn.dynamic_source == "import()"

    def test_detect_dynamic_import_variable(self):
        """Test detection of dynamic import() with variable."""
        code = '''
async function loadPlugin(modulePath) {
    const plugin = await import(modulePath);
    return plugin;
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "<dynamic>"
            assert dyn.dynamic_pattern == "modulePath"
            assert dyn.dynamic_source == "import()"

    def test_detect_require_dynamic(self):
        """Test detection of require() with dynamic argument."""
        code = '''
function loadModule(name) {
    return require(name);
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "javascript")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 1

            dyn = dynamic_imports[0]
            assert dyn.module == "<dynamic>"
            assert dyn.dynamic_pattern == "name"
            assert dyn.dynamic_source == "require()"

    def test_no_false_positives_static_imports(self):
        """Test that static imports are not marked as dynamic."""
        code = '''
import React from 'react';
import { useState } from 'react';
import * as utils from './utils';
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 0

    def test_detect_multiple_dynamic_imports(self):
        """Test detection of multiple dynamic imports."""
        code = '''
async function loadModules(type) {
    const a = await import("./static-module");
    const b = await import(`./dynamic/${type}`);
    const c = require(getModuleName());
    return { a, b, c };
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            dynamic_imports = [i for i in result.module.imports if i.is_dynamic]
            assert len(dynamic_imports) == 3


class TestCyclomaticComplexity:
    """Test cyclomatic complexity calculation across all languages."""

    def test_python_simple_if(self):
        """Test Python: simple if statement has complexity 2."""
        code = '''
def check(x):
    if x:
        pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 2  # base 1 + if 1

    def test_python_if_and_condition(self):
        """Test Python: if with 'and' has complexity 3."""
        code = '''
def check(x, y):
    if x and y:
        pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 3  # base 1 + if 1 + and 1

    def test_python_for_loop(self):
        """Test Python: for loop has complexity 2."""
        code = '''
def iterate(items):
    for item in items:
        pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 2  # base 1 + for 1

    def test_python_nested_if(self):
        """Test Python: nested if has complexity 3."""
        code = '''
def check(x, y):
    if x:
        if y:
            pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 3  # base 1 + if 1 + if 1

    def test_python_comprehension_with_if(self):
        """Test Python: list comprehension with filter has complexity 3."""
        code = '''
def filter_items(items):
    return [x for x in items if x > 0]
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            # base 1 + for_in_clause 1 + if_clause 1
            assert func.body_complexity == 3

    def test_python_try_except(self):
        """Test Python: try/except adds complexity per except clause."""
        code = '''
def risky():
    try:
        pass
    except ValueError:
        pass
    except TypeError:
        pass
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 3  # base 1 + except 1 + except 1

    def test_typescript_if_ternary(self):
        """Test TypeScript: if + ternary has complexity 3."""
        code = '''
function check(x: boolean, y: boolean): number {
    if (x) {
        return y ? 1 : 0;
    }
    return -1;
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 3  # base 1 + if 1 + ternary 1

    def test_typescript_logical_operators(self):
        """Test TypeScript: && and || count as decision points."""
        code = '''
function validate(a: boolean, b: boolean, c: boolean): boolean {
    return a && b || c;
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ts", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "typescript")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 3  # base 1 + && 1 + || 1

    def test_go_if_for(self):
        """Test Go: if + for has complexity 3."""
        code = '''
package main

func process(items []int) int {
    sum := 0
    if len(items) > 0 {
        for _, item := range items {
            sum += item
        }
    }
    return sum
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "go")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 3  # base 1 + if 1 + for 1

    def test_java_switch_cases(self):
        """Test Java: switch with cases adds complexity per case."""
        code = '''
public class Calc {
    public int eval(int op, int a, int b) {
        switch (op) {
            case 1:
                return a + b;
            case 2:
                return a - b;
        }
        return 0;
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "java")

            assert result.success
            cls = result.module.classes[0]
            method = next(m for m in cls.methods if m.name == "eval")
            # base 1 + case 1 + case 1
            assert method.body_complexity == 3

    def test_rust_match_arms(self):
        """Test Rust: match expression adds complexity per arm."""
        code = '''
fn classify(n: i32) -> &'static str {
    match n {
        0 => "zero",
        1 => "one",
        _ => "other",
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "rust")

            assert result.success
            func = result.module.functions[0]
            # base 1 + match 1 + arm 1 + arm 1 + arm 1 = 5
            assert func.body_complexity == 5

    def test_csharp_null_coalescing(self):
        """Test C#: ?? operator counts as decision point."""
        code = '''
public class Helper {
    public string GetName(string? name) {
        return name ?? "default";
    }
}
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cs", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "csharp")

            assert result.success
            cls = result.module.classes[0]
            method = next(m for m in cls.methods if m.name == "GetName")
            assert method.body_complexity == 2  # base 1 + ?? 1

    def test_simple_function_baseline(self):
        """Test that a function with no decision points has complexity 1."""
        code = '''
def simple():
    return 42
'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()

            result = parse_file(Path(f.name), "python")

            assert result.success
            func = result.module.functions[0]
            assert func.body_complexity == 1  # just base complexity
