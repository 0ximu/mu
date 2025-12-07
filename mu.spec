# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for MU binary distribution.

Build with: pyinstaller mu.spec

This creates a single-file executable containing the MU CLI and all dependencies,
including tree-sitter language bindings for multi-language code analysis.
"""

import sys
from pathlib import Path

# Get the source root
src_root = Path("src").resolve()

block_cipher = None

a = Analysis(
    ["src/mu/cli.py"],
    pathex=[str(src_root)],
    binaries=[],
    datas=[
        # Include any data files needed at runtime
        # Tree-sitter language files are compiled bindings, included via hiddenimports
    ],
    hiddenimports=[
        # MU internal modules
        "mu",
        "mu.cli",
        "mu.config",
        "mu.errors",
        "mu.logging",
        "mu.client",
        "mu.describe",
        # Parser extractors
        "mu.parser",
        "mu.parser.extractors",
        "mu.parser.extractors.python_extractor",
        "mu.parser.extractors.javascript_extractor",
        "mu.parser.extractors.typescript_extractor",
        "mu.parser.extractors.go_extractor",
        "mu.parser.extractors.java_extractor",
        "mu.parser.extractors.rust_extractor",
        "mu.parser.extractors.csharp_extractor",
        # Tree-sitter language bindings
        "tree_sitter",
        "tree_sitter_python",
        "tree_sitter_javascript",
        "tree_sitter_typescript",
        "tree_sitter_go",
        "tree_sitter_java",
        "tree_sitter_rust",
        "tree_sitter_c_sharp",
        # Core dependencies
        "click",
        "rich",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "duckdb",
        "lark",
        "tiktoken",
        "litellm",
        "yaml",
        "dotenv",
        "pyperclip",
        # FastAPI/uvicorn for daemon
        "fastapi",
        "uvicorn",
        "watchfiles",
        "starlette",
        # Async support
        "anyio",
        "sniffio",
        "h11",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude test frameworks
        "pytest",
        "hypothesis",
        "coverage",
        # Exclude dev tools
        "mypy",
        "ruff",
        "bandit",
        # Exclude unused heavy packages
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
