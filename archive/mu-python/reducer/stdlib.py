"""Language-aware standard library detection.

This module provides comprehensive stdlib detection for multiple programming languages.
It maps language identifiers to frozensets of module/package prefixes that should be
considered part of the standard library and typically stripped from MU output.
"""

from __future__ import annotations

import re

# Python standard library modules (comprehensive list based on Python 3.12)
# Reference: https://docs.python.org/3/library/
_PYTHON_STDLIB: frozenset[str] = frozenset({
    # Text Processing
    "string", "re", "difflib", "textwrap", "unicodedata", "stringprep",
    "readline", "rlcompleter",
    # Binary Data
    "struct", "codecs",
    # Data Types
    "datetime", "zoneinfo", "calendar", "collections", "heapq", "bisect",
    "array", "weakref", "types", "copy", "pprint", "reprlib", "enum",
    "graphlib",
    # Numeric and Math
    "numbers", "math", "cmath", "decimal", "fractions", "random", "statistics",
    # Functional Programming
    "itertools", "functools", "operator",
    # File and Directory Access
    "pathlib", "os", "fileinput", "stat", "filecmp", "tempfile", "glob",
    "fnmatch", "linecache", "shutil",
    # Data Persistence
    "pickle", "copyreg", "shelve", "marshal", "dbm", "sqlite3",
    # Data Compression and Archiving
    "zlib", "gzip", "bz2", "lzma", "zipfile", "tarfile",
    # File Formats
    "csv", "configparser", "tomllib", "netrc", "plistlib",
    # Cryptographic Services
    "hashlib", "hmac", "secrets",
    # Generic OS Services
    "sys", "sysconfig", "builtins", "warnings", "dataclasses",
    "contextlib", "abc", "atexit", "traceback", "gc", "inspect", "site",
    # Concurrent Execution
    "threading", "multiprocessing", "concurrent", "subprocess", "sched",
    "queue",
    # Contextvars
    "contextvars",
    # Networking and IPC
    "asyncio", "socket", "ssl", "select", "selectors", "signal", "mmap",
    # Internet Data Handling
    "email", "json", "mailbox", "mimetypes", "base64", "binascii",
    "quopri", "uu",
    # Structured Markup
    "html", "xml",
    # Internet Protocols
    "webbrowser", "wsgiref", "urllib", "http", "ftplib", "poplib",
    "imaplib", "smtplib", "uuid", "socketserver", "xmlrpc", "ipaddress",
    # Multimedia
    "wave", "colorsys",
    # Internationalization
    "gettext", "locale",
    # Program Frameworks
    "turtle", "cmd", "shlex",
    # GUI
    "tkinter", "idlelib",
    # Development Tools
    "typing", "pydoc", "doctest", "unittest", "test",
    # Debugging and Profiling
    "bdb", "faulthandler", "pdb", "timeit", "trace", "tracemalloc",
    # Software Packaging
    "ensurepip", "venv", "zipapp",
    # Runtime Services
    "runpy", "importlib", "ast", "symtable", "token", "keyword",
    "tokenize", "tabnanny", "pyclbr", "py_compile", "compileall", "dis",
    "pickletools",
    # Custom Interpreters
    "code", "codeop",
    # Importing
    "zipimport", "pkgutil", "modulefinder",
    # Python Language Services
    "parser",
    # MS Windows
    "msvcrt", "winreg", "winsound",
    # Unix
    "posix", "pwd", "grp", "termios", "tty", "pty", "fcntl", "resource",
    "syslog",
    # Superseded Modules
    "optparse", "getopt", "imp",
    # IO
    "io",
    # Logging
    "logging",
    # argparse
    "argparse",
    # ctypes
    "ctypes",
    # errno
    "errno",
    # platform
    "platform",
    # time
    "time",
    # _thread (internal but commonly seen)
    "_thread",
})

# Node.js built-in modules (comprehensive list)
# Reference: https://nodejs.org/api/
_NODEJS_STDLIB: frozenset[str] = frozenset({
    # Core modules
    "assert", "async_hooks", "buffer", "child_process", "cluster",
    "console", "constants", "crypto", "dgram", "diagnostics_channel",
    "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl",
    "stream", "string_decoder", "sys", "timers", "tls", "trace_events",
    "tty", "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
    # Node.js prefixed modules (node:fs, etc.)
    "node",
    # Test runner
    "test",
})

# TypeScript uses same as Node.js plus some type-only modules
_TYPESCRIPT_STDLIB: frozenset[str] = _NODEJS_STDLIB

# JavaScript (browser) - Web APIs that look like imports
_JAVASCRIPT_STDLIB: frozenset[str] = _NODEJS_STDLIB | frozenset({
    # These are typically available globally but may appear as imports
    "window", "document", "navigator", "location", "history",
    "localStorage", "sessionStorage", "indexedDB", "fetch",
    "XMLHttpRequest", "WebSocket", "Worker", "ServiceWorker",
})

# C# / .NET namespaces (common framework namespaces)
# Reference: https://learn.microsoft.com/en-us/dotnet/api/
_CSHARP_STDLIB: frozenset[str] = frozenset({
    # System namespaces
    "System",
    # Microsoft namespaces
    "Microsoft",
    # Windows namespaces
    "Windows",
    # Mono (Xamarin)
    "Mono",
    # Common internal namespaces
    "Internal",
})

# Go standard library packages
# Reference: https://pkg.go.dev/std
_GO_STDLIB: frozenset[str] = frozenset({
    # Core packages
    "archive", "bufio", "builtin", "bytes", "cmp", "compress",
    "container", "context", "crypto", "database", "debug", "embed",
    "encoding", "errors", "expvar", "flag", "fmt", "go", "hash",
    "html", "image", "index", "io", "iter", "log", "maps", "math",
    "mime", "net", "os", "path", "plugin", "reflect", "regexp",
    "runtime", "slices", "sort", "strconv", "strings", "sync",
    "syscall", "testing", "text", "time", "unicode", "unique",
    "unsafe",
    # Internal (not for general use but seen in imports)
    "internal",
    # Vendor (standard library vendored packages)
    "vendor",
})

# Rust standard library crates
# Reference: https://doc.rust-lang.org/std/
_RUST_STDLIB: frozenset[str] = frozenset({
    # Core crates
    "std",
    "core",
    "alloc",
    # Proc macro
    "proc_macro",
    # Test
    "test",
})

# Java standard library packages
# Reference: https://docs.oracle.com/en/java/javase/21/docs/api/
_JAVA_STDLIB: frozenset[str] = frozenset({
    # Core Java packages
    "java",
    "javax",
    # Sun internal (deprecated but still seen)
    "sun",
    "com.sun",
    # XML and related
    "org.w3c",
    "org.xml",
    "org.ietf",
    # JDK internal
    "jdk",
})

# Kotlin standard library
# Reference: https://kotlinlang.org/api/latest/jvm/stdlib/
_KOTLIN_STDLIB: frozenset[str] = frozenset({
    # Kotlin standard library
    "kotlin",
    # Also inherits Java stdlib
}) | _JAVA_STDLIB

# Swift standard library
# Reference: https://developer.apple.com/documentation/swift/swift-standard-library
_SWIFT_STDLIB: frozenset[str] = frozenset({
    # Swift core
    "Swift",
    # Foundation (core Apple framework)
    "Foundation",
    # Core Foundation
    "CoreFoundation",
    # Dispatch
    "Dispatch",
    # Darwin
    "Darwin",
    # ObjectiveC interop
    "ObjectiveC",
    # Common Apple frameworks (often imported)
    "UIKit",
    "AppKit",
    "SwiftUI",
    "Combine",
    "CoreGraphics",
    "CoreData",
    "CoreLocation",
    "MapKit",
    "AVFoundation",
    "Photos",
    "Contacts",
    "EventKit",
    "HealthKit",
    "HomeKit",
    "CloudKit",
    "StoreKit",
    "GameKit",
    "SpriteKit",
    "SceneKit",
    "Metal",
    "MetalKit",
    "Vision",
    "CoreML",
    "NaturalLanguage",
    "Speech",
    "Intents",
    "NotificationCenter",
    "WatchKit",
    "ClockKit",
})

# Ruby standard library
# Reference: https://ruby-doc.org/stdlib/
_RUBY_STDLIB: frozenset[str] = frozenset({
    # Core modules/classes (typically not imported but may appear)
    "abbrev", "base64", "benchmark", "bigdecimal", "cgi", "csv",
    "date", "delegate", "digest", "drb", "english", "erb", "etc",
    "fcntl", "fiddle", "fileutils", "find", "forwardable", "getoptlong",
    "io", "ipaddr", "irb", "json", "logger", "matrix", "minitest",
    "monitor", "mutex_m", "net", "nkf", "objspace", "observer",
    "open3", "open-uri", "openssl", "optparse", "ostruct", "pathname",
    "pp", "prettyprint", "prime", "pstore", "psych", "pty", "racc",
    "rake", "rdoc", "readline", "reline", "resolv", "ripper", "rss",
    "securerandom", "set", "shellwords", "singleton", "socket",
    "stringio", "strscan", "syslog", "tempfile", "test", "time",
    "timeout", "tmpdir", "tracer", "tsort", "un", "uri", "weakref",
    "webrick", "yaml", "zlib",
})

# PHP (common internal/core namespaces)
_PHP_STDLIB: frozenset[str] = frozenset({
    # PHP has no real "import" system for stdlib, but these namespaces are common
    "stdClass",
    "Exception",
    "Error",
    "Throwable",
    # SPL
    "ArrayObject",
    "ArrayIterator",
    "Iterator",
    "IteratorAggregate",
    "Countable",
    "Serializable",
    "Traversable",
})

# C/C++ standard library headers (as module names)
_CPP_STDLIB: frozenset[str] = frozenset({
    # C standard library
    "assert", "complex", "ctype", "errno", "fenv", "float", "inttypes",
    "iso646", "limits", "locale", "math", "setjmp", "signal", "stdalign",
    "stdarg", "stdatomic", "stdbool", "stddef", "stdint", "stdio",
    "stdlib", "stdnoreturn", "string", "tgmath", "threads", "time",
    "uchar", "wchar", "wctype",
    # C++ standard library
    "algorithm", "any", "array", "atomic", "barrier", "bit", "bitset",
    "cassert", "ccomplex", "cctype", "cerrno", "cfenv", "cfloat",
    "charconv", "chrono", "cinttypes", "ciso646", "climits", "clocale",
    "cmath", "codecvt", "compare", "concepts", "condition_variable",
    "coroutine", "csetjmp", "csignal", "cstdarg", "cstddef", "cstdint",
    "cstdio", "cstdlib", "cstring", "ctgmath", "ctime", "cuchar", "cwchar",
    "cwctype", "deque", "exception", "execution", "expected", "filesystem",
    "flat_map", "flat_set", "format", "forward_list", "fstream", "functional",
    "future", "generator", "initializer_list", "iomanip", "ios", "iosfwd",
    "iostream", "istream", "iterator", "latch", "list", "map", "mdspan", "memory", "memory_resource", "mutex", "new", "numbers",
    "numeric", "optional", "ostream", "print", "queue", "random", "ranges",
    "ratio", "regex", "scoped_allocator", "semaphore", "set", "shared_mutex",
    "source_location", "span", "spanstream", "sstream", "stack", "stacktrace",
    "stdexcept", "stdfloat", "stop_token", "streambuf", "string_view",
    "strstream", "syncstream", "system_error", "thread", "tuple", "type_traits",
    "typeindex", "typeinfo", "unordered_map", "unordered_set", "utility",
    "valarray", "variant", "vector", "version",
    # Common system headers
    "sys", "unistd", "fcntl", "dirent", "pthread",
})

# Scala standard library
_SCALA_STDLIB: frozenset[str] = frozenset({
    "scala",
}) | _JAVA_STDLIB

# Elixir standard library
_ELIXIR_STDLIB: frozenset[str] = frozenset({
    # Elixir core modules
    "Kernel", "Enum", "List", "Map", "String", "IO", "File", "Path",
    "System", "Process", "Agent", "Task", "GenServer", "Supervisor",
    "Application", "Logger", "Macro", "Module", "Code", "Atom",
    "Integer", "Float", "Tuple", "Keyword", "MapSet", "Range",
    "Regex", "Stream", "DateTime", "Date", "Time", "Calendar",
    "NaiveDateTime", "Duration", "URI", "Base", "Bitwise", "Exception",
    "Protocol", "Behaviour", "Access", "Collectable", "Enumerable",
    "Inspect", "OptionParser", "Port", "Registry", "StringIO",
    "EEx", "ExUnit", "IEx", "Mix",
    # Erlang stdlib (commonly used from Elixir)
    "erlang",
    ":erlang",
    "ets",
    ":ets",
    "gen_server",
    ":gen_server",
})

# Haskell standard library (Prelude and base)
_HASKELL_STDLIB: frozenset[str] = frozenset({
    # Base package modules
    "Prelude", "Control", "Data", "Debug", "Foreign", "GHC", "Numeric",
    "System", "Text", "Type", "Unsafe",
})

# Master mapping of language to stdlib prefixes
STDLIB_BY_LANGUAGE: dict[str, frozenset[str]] = {
    "python": _PYTHON_STDLIB,
    "typescript": _TYPESCRIPT_STDLIB,
    "javascript": _JAVASCRIPT_STDLIB,
    "csharp": _CSHARP_STDLIB,
    "go": _GO_STDLIB,
    "rust": _RUST_STDLIB,
    "java": _JAVA_STDLIB,
    "kotlin": _KOTLIN_STDLIB,
    "swift": _SWIFT_STDLIB,
    "ruby": _RUBY_STDLIB,
    "php": _PHP_STDLIB,
    "cpp": _CPP_STDLIB,
    "c": _CPP_STDLIB,  # C uses same set
    "scala": _SCALA_STDLIB,
    "elixir": _ELIXIR_STDLIB,
    "haskell": _HASKELL_STDLIB,
}

# Combined set of all stdlib prefixes (for backwards compatibility)
ALL_STDLIB_PREFIXES: frozenset[str] = frozenset().union(*STDLIB_BY_LANGUAGE.values())


def is_stdlib_import(module_name: str, language: str | None = None) -> bool:
    """Check if a module is part of the standard library for the given language.

    Args:
        module_name: The module name to check (e.g., "os", "os.path", "System.IO")
        language: The programming language. If None, checks against all known stdlibs.

    Returns:
        True if the module is considered part of the standard library.

    Examples:
        >>> is_stdlib_import("os", "python")
        True
        >>> is_stdlib_import("requests", "python")
        False
        >>> is_stdlib_import("System.IO", "csharp")
        True
        >>> is_stdlib_import("fs", "typescript")
        True
        >>> is_stdlib_import("net/http", "go")
        True
        >>> is_stdlib_import("std::collections", "rust")
        True
    """
    if not module_name:
        return False

    # Get the base module - handle different separators:
    # - Python/JS/C#: dots (os.path, System.IO)
    # - Go: slashes (net/http)
    # - Rust: double colons (std::collections)
    # - C++: angle brackets for includes are typically just names
    base_module = re.split(r'[./:]', module_name)[0]

    # Get prefixes for the language, or all prefixes if no language specified
    if language:
        prefixes = STDLIB_BY_LANGUAGE.get(language.lower(), frozenset())
    else:
        prefixes = ALL_STDLIB_PREFIXES

    # Check if base module matches any prefix
    return base_module in prefixes


def get_stdlib_prefixes(language: str | None = None) -> frozenset[str]:
    """Get stdlib prefixes for a language.

    Args:
        language: The programming language. If None, returns all known prefixes.

    Returns:
        A frozenset of stdlib module prefixes.

    Examples:
        >>> "os" in get_stdlib_prefixes("python")
        True
        >>> "System" in get_stdlib_prefixes("csharp")
        True
        >>> get_stdlib_prefixes() == ALL_STDLIB_PREFIXES
        True
    """
    if language:
        return STDLIB_BY_LANGUAGE.get(language.lower(), frozenset())
    return ALL_STDLIB_PREFIXES


def get_supported_languages() -> list[str]:
    """Get list of languages with stdlib detection support.

    Returns:
        List of supported language identifiers.
    """
    return sorted(STDLIB_BY_LANGUAGE.keys())
