# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for MU binary distribution.

Build with: pyinstaller mu.spec

This creates a one-folder distribution containing the MU CLI and all dependencies.
The one-folder mode provides instant startup (~0.1s) vs single-file (~4s) because
it doesn't need to extract on every run.

Installation:
    sudo mv dist/mu /usr/local/lib/mu_app
    sudo ln -s /usr/local/lib/mu_app/mu /usr/local/bin/mu
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# Get the source root
src_root = Path("src").resolve()

block_cipher = None

# Collect all tiktoken data files, binaries, and hidden imports
# tiktoken requires vocabulary files (e.g., cl100k_base.tiktoken) at runtime
tik_datas, tik_binaries, tik_hiddenimports = collect_all('tiktoken')

# Find and include the Rust extension (_core.abi3.so)
rust_ext_path = src_root / "mu" / "_core.abi3.so"
rust_binaries = []
if rust_ext_path.exists():
    rust_binaries = [(str(rust_ext_path), "mu")]

a = Analysis(
    ["src/mu/cli.py"],
    pathex=[str(src_root)],
    binaries=tik_binaries + rust_binaries,
    datas=[
        # Include MUQL grammar file (required for Lark parser at runtime)
        ("src/mu/kernel/muql/grammar.lark", "mu/kernel/muql"),
        # Include mu.data package (man pages, LLM spec files)
        ("src/mu/data", "mu/data"),
    ] + tik_datas,
    hiddenimports=[
        # MU internal modules
        "mu",
        "mu.cli",
        "mu.config",
        "mu.errors",
        "mu.logging",
        "mu.client",
        "mu.describe",
        # Commands (lazy-loaded modules)
        "mu.commands",
        "mu.commands.lazy",
        "mu.commands.cache",
        "mu.commands.compress",
        "mu.commands.describe",
        "mu.commands.diff",
        "mu.commands.init_cmd",
        "mu.commands.llm_spec",
        "mu.commands.man",
        "mu.commands.query",
        "mu.commands.scan",
        "mu.commands.view",
        # Command subgroups
        "mu.commands.contracts",
        "mu.commands.contracts.init_cmd",
        "mu.commands.contracts.verify",
        "mu.commands.daemon",
        "mu.commands.daemon.run",
        "mu.commands.daemon.start",
        "mu.commands.daemon.status",
        "mu.commands.daemon.stop",
        "mu.commands.kernel",
        "mu.commands.kernel.blame",
        "mu.commands.kernel.build",
        "mu.commands.kernel.context",
        "mu.commands.kernel.deps",
        "mu.commands.kernel.diff",
        "mu.commands.kernel.embed",
        "mu.commands.kernel.export",
        "mu.commands.kernel.history",
        "mu.commands.kernel.init_cmd",
        "mu.commands.kernel.muql",
        "mu.commands.kernel.search",
        "mu.commands.kernel.snapshot",
        "mu.commands.kernel.stats",
        "mu.commands.mcp",
        "mu.commands.mcp.serve",
        "mu.commands.mcp.test",
        "mu.commands.mcp.tools",
        # Parser extractors (correct paths - no 'extractors' subpackage)
        "mu.parser",
        "mu.parser.base",
        "mu.parser.models",
        "mu.parser.python_extractor",
        "mu.parser.typescript_extractor",
        "mu.parser.go_extractor",
        "mu.parser.java_extractor",
        "mu.parser.rust_extractor",
        "mu.parser.csharp_extractor",
        # Kernel modules
        "mu.kernel",
        "mu.kernel.muql",
        "mu.kernel.muql.parser",
        "mu.kernel.muql.engine",
        "mu.kernel.muql.executor",
        "mu.kernel.muql.planner",
        "mu.kernel.muql.formatter",
        "mu.kernel.graph",
        # Diff module
        "mu.diff",
        "mu.diff.differ",
        "mu.diff.models",
        "mu.diff.formatters",
        "mu.diff.git_utils",
        # Scanner module
        "mu.scanner",
        # MCP server
        "mu.mcp",
        "mu.mcp.server",
        # Rust extension (loaded dynamically)
        "mu._core",
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
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        "litellm",
        "yaml",
        "dotenv",
        "pyperclip",
        # FastAPI/uvicorn for daemon
        "fastapi",
        "uvicorn",
        "watchfiles",
        "starlette",
        # MCP server
        "mcp",
        "mcp.server",
        "mcp.server.fastmcp",
        # Async support
        "anyio",
        "sniffio",
        "h11",
    ] + tik_hiddenimports,
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

# One-folder mode: EXE only contains scripts, COLLECT gathers everything
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,  # Binaries go in COLLECT, not EXE
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

# COLLECT gathers all components into a single directory
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mu",
)
