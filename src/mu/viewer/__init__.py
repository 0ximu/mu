"""MU Viewer - Terminal and HTML rendering for MU format files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator


class TokenType(Enum):
    """Token types for MU format syntax highlighting."""

    HEADER = "header"
    SIGIL_MODULE = "sigil_module"       # !
    SIGIL_ENTITY = "sigil_entity"       # $
    SIGIL_FUNCTION = "sigil_function"   # #
    SIGIL_METADATA = "sigil_metadata"   # @
    SIGIL_CONDITIONAL = "sigil_cond"    # ?
    ANNOTATION = "annotation"           # ::
    OPERATOR = "operator"               # ->, =>, |, ~
    KEYWORD = "keyword"                 # module, async, static, etc.
    TYPE = "type"                       # Type annotations
    NAME = "name"                       # Identifiers
    PARAMETER = "parameter"             # Function parameters
    COMMENT = "comment"                 # Comments
    STRING = "string"                   # String literals
    NUMBER = "number"                   # Numbers
    PUNCTUATION = "punctuation"         # Brackets, commas, etc.
    WHITESPACE = "whitespace"
    TEXT = "text"                       # Plain text


@dataclass
class Token:
    """A single token from MU format parsing."""

    type: TokenType
    value: str
    line: int = 0
    column: int = 0


@dataclass
class MUDocument:
    """Parsed MU document for rendering."""

    source: str
    lines: list[str] = field(default_factory=list)
    tokens: list[list[Token]] = field(default_factory=list)  # tokens per line
    header: dict[str, str] = field(default_factory=dict)
    modules: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, source: str) -> "MUDocument":
        """Parse MU source into a document."""
        doc = cls(source=source)
        doc.lines = source.splitlines()
        doc.tokens = [list(tokenize_line(line, i)) for i, line in enumerate(doc.lines)]

        # Extract header info
        for line in doc.lines[:10]:
            if line.startswith("# "):
                parts = line[2:].split(": ", 1)
                if len(parts) == 2:
                    doc.header[parts[0].strip()] = parts[1].strip()
            elif line.startswith("!module "):
                doc.modules.append(line[8:].strip())

        return doc


# Keywords in MU format
MU_KEYWORDS = {
    "module", "async", "static", "classmethod", "property",
    "class", "interface", "struct", "enum",
}


def tokenize_line(line: str, line_num: int = 0) -> Iterator[Token]:
    """Tokenize a single line of MU format."""
    if not line:
        return

    pos = 0
    length = len(line)

    while pos < length:
        # Leading whitespace
        if line[pos].isspace():
            start = pos
            while pos < length and line[pos].isspace():
                pos += 1
            yield Token(TokenType.WHITESPACE, line[start:pos], line_num, start)
            continue

        # Header comment lines
        if pos == 0 and line.startswith("# "):
            yield Token(TokenType.HEADER, line, line_num, 0)
            return

        # Annotation (::)
        if line[pos:pos + 2] == "::":
            # Find the rest of the annotation
            yield Token(TokenType.ANNOTATION, "::", line_num, pos)
            pos += 2
            if pos < length:
                # Rest of line is annotation content
                rest = line[pos:]
                yield Token(TokenType.COMMENT, rest, line_num, pos)
                return
            continue

        # Operators (check multi-char first)
        if line[pos:pos + 2] == "->":
            yield Token(TokenType.OPERATOR, "->", line_num, pos)
            pos += 2
            continue

        if line[pos:pos + 2] == "=>":
            yield Token(TokenType.OPERATOR, "=>", line_num, pos)
            pos += 2
            continue

        # Single-char operators
        if line[pos] == "|":
            yield Token(TokenType.OPERATOR, "|", line_num, pos)
            pos += 1
            continue

        if line[pos] == "~":
            yield Token(TokenType.OPERATOR, "~", line_num, pos)
            pos += 1
            continue

        # Sigils
        if line[pos] == "!":
            yield Token(TokenType.SIGIL_MODULE, "!", line_num, pos)
            pos += 1
            continue

        if line[pos] == "$":
            yield Token(TokenType.SIGIL_ENTITY, "$", line_num, pos)
            pos += 1
            continue

        if line[pos] == "#":
            yield Token(TokenType.SIGIL_FUNCTION, "#", line_num, pos)
            pos += 1
            continue

        if line[pos] == "@":
            yield Token(TokenType.SIGIL_METADATA, "@", line_num, pos)
            pos += 1
            continue

        if line[pos] == "?":
            yield Token(TokenType.SIGIL_CONDITIONAL, "?", line_num, pos)
            pos += 1
            continue

        # Punctuation
        if line[pos] in "()[]{},:<>":
            yield Token(TokenType.PUNCTUATION, line[pos], line_num, pos)
            pos += 1
            continue

        # Strings
        if line[pos] in "\"'":
            quote = line[pos]
            start = pos
            pos += 1
            while pos < length and line[pos] != quote:
                if line[pos] == "\\" and pos + 1 < length:
                    pos += 2
                else:
                    pos += 1
            if pos < length:
                pos += 1
            yield Token(TokenType.STRING, line[start:pos], line_num, start)
            continue

        # Numbers
        if line[pos].isdigit() or (line[pos] == "-" and pos + 1 < length and line[pos + 1].isdigit()):
            start = pos
            if line[pos] == "-":
                pos += 1
            while pos < length and (line[pos].isdigit() or line[pos] == "."):
                pos += 1
            yield Token(TokenType.NUMBER, line[start:pos], line_num, start)
            continue

        # Identifiers (keywords, names, types)
        if line[pos].isalpha() or line[pos] == "_":
            start = pos
            while pos < length and (line[pos].isalnum() or line[pos] in "_.*"):
                pos += 1
            word = line[start:pos]

            # Determine token type
            if word.lower() in MU_KEYWORDS:
                yield Token(TokenType.KEYWORD, word, line_num, start)
            # Type annotations often come after -> or :
            elif start > 0 and line[start - 1] == ":":
                yield Token(TokenType.TYPE, word, line_num, start)
            elif start > 1 and line[start - 2:start] == "->":
                yield Token(TokenType.TYPE, word, line_num, start)
            elif start > 1 and line[start - 3:start] == "-> ":
                yield Token(TokenType.TYPE, word, line_num, start)
            else:
                yield Token(TokenType.NAME, word, line_num, start)
            continue

        # Default: single character as text
        yield Token(TokenType.TEXT, line[pos], line_num, pos)
        pos += 1


class TerminalRenderer:
    """Render MU format with rich terminal colors."""

    # ANSI color codes for different themes
    DARK_THEME = {
        TokenType.HEADER: "\033[1;36m",       # Bold cyan
        TokenType.SIGIL_MODULE: "\033[1;35m",  # Bold magenta
        TokenType.SIGIL_ENTITY: "\033[1;33m",  # Bold yellow
        TokenType.SIGIL_FUNCTION: "\033[1;32m",  # Bold green
        TokenType.SIGIL_METADATA: "\033[1;34m",  # Bold blue
        TokenType.SIGIL_CONDITIONAL: "\033[1;31m",  # Bold red
        TokenType.ANNOTATION: "\033[2;37m",   # Dim white
        TokenType.OPERATOR: "\033[1;37m",     # Bold white
        TokenType.KEYWORD: "\033[1;35m",      # Bold magenta
        TokenType.TYPE: "\033[0;33m",         # Yellow
        TokenType.NAME: "\033[0;37m",         # White
        TokenType.PARAMETER: "\033[0;36m",    # Cyan
        TokenType.COMMENT: "\033[2;32m",      # Dim green
        TokenType.STRING: "\033[0;32m",       # Green
        TokenType.NUMBER: "\033[0;34m",       # Blue
        TokenType.PUNCTUATION: "\033[2;37m",  # Dim white
        TokenType.WHITESPACE: "",
        TokenType.TEXT: "\033[0m",
    }

    LIGHT_THEME = {
        TokenType.HEADER: "\033[1;34m",       # Bold blue
        TokenType.SIGIL_MODULE: "\033[1;35m",  # Bold magenta
        TokenType.SIGIL_ENTITY: "\033[1;33m",  # Bold yellow/orange
        TokenType.SIGIL_FUNCTION: "\033[1;32m",  # Bold green
        TokenType.SIGIL_METADATA: "\033[1;34m",  # Bold blue
        TokenType.SIGIL_CONDITIONAL: "\033[1;31m",  # Bold red
        TokenType.ANNOTATION: "\033[0;90m",   # Gray
        TokenType.OPERATOR: "\033[1;30m",     # Bold black
        TokenType.KEYWORD: "\033[1;35m",      # Bold magenta
        TokenType.TYPE: "\033[0;34m",         # Blue
        TokenType.NAME: "\033[0;30m",         # Black
        TokenType.PARAMETER: "\033[0;36m",    # Cyan
        TokenType.COMMENT: "\033[0;32m",      # Green
        TokenType.STRING: "\033[0;32m",       # Green
        TokenType.NUMBER: "\033[0;34m",       # Blue
        TokenType.PUNCTUATION: "\033[0;90m",  # Gray
        TokenType.WHITESPACE: "",
        TokenType.TEXT: "\033[0m",
    }

    RESET = "\033[0m"

    def __init__(self, theme: str = "dark"):
        self.theme = self.DARK_THEME if theme == "dark" else self.LIGHT_THEME

    def render(self, doc: MUDocument) -> str:
        """Render document with ANSI colors."""
        output = []

        for line_tokens in doc.tokens:
            line_parts = []
            for token in line_tokens:
                color = self.theme.get(token.type, "")
                if color:
                    line_parts.append(f"{color}{token.value}{self.RESET}")
                else:
                    line_parts.append(token.value)
            output.append("".join(line_parts))

        return "\n".join(output)

    def render_with_line_numbers(self, doc: MUDocument) -> str:
        """Render document with line numbers."""
        output = []
        width = len(str(len(doc.lines)))

        for i, line_tokens in enumerate(doc.tokens, 1):
            line_num = f"\033[2;37m{i:>{width}}\033[0m │ "
            line_parts = [line_num]

            for token in line_tokens:
                color = self.theme.get(token.type, "")
                if color:
                    line_parts.append(f"{color}{token.value}{self.RESET}")
                else:
                    line_parts.append(token.value)
            output.append("".join(line_parts))

        return "\n".join(output)


class HTMLRenderer:
    """Render MU format as styled HTML."""

    CSS_STYLES = """
    <style>
        .mu-container {
            font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Consolas', monospace;
            font-size: 14px;
            line-height: 1.5;
            padding: 20px;
            background: #1e1e2e;
            color: #cdd6f4;
            border-radius: 8px;
            overflow-x: auto;
        }
        .mu-container.light {
            background: #eff1f5;
            color: #4c4f69;
        }
        .mu-line {
            display: block;
            white-space: pre;
        }
        .mu-line-num {
            display: inline-block;
            width: 3em;
            text-align: right;
            padding-right: 1em;
            margin-right: 1em;
            border-right: 1px solid #45475a;
            color: #6c7086;
            user-select: none;
        }
        .mu-container.light .mu-line-num { border-right-color: #9ca0b0; color: #9ca0b0; }

        /* Token colors - Dark theme (Catppuccin Mocha) */
        .mu-header { color: #89dceb; font-weight: bold; }
        .mu-sigil-module { color: #cba6f7; font-weight: bold; }
        .mu-sigil-entity { color: #f9e2af; font-weight: bold; }
        .mu-sigil-function { color: #a6e3a1; font-weight: bold; }
        .mu-sigil-metadata { color: #89b4fa; font-weight: bold; }
        .mu-sigil-cond { color: #f38ba8; font-weight: bold; }
        .mu-annotation { color: #6c7086; }
        .mu-operator { color: #cdd6f4; font-weight: bold; }
        .mu-keyword { color: #cba6f7; font-weight: bold; }
        .mu-type { color: #f9e2af; }
        .mu-name { color: #cdd6f4; }
        .mu-parameter { color: #94e2d5; }
        .mu-comment { color: #a6e3a1; font-style: italic; }
        .mu-string { color: #a6e3a1; }
        .mu-number { color: #fab387; }
        .mu-punctuation { color: #6c7086; }

        /* Light theme (Catppuccin Latte) */
        .mu-container.light .mu-header { color: #209fb5; }
        .mu-container.light .mu-sigil-module { color: #8839ef; }
        .mu-container.light .mu-sigil-entity { color: #df8e1d; }
        .mu-container.light .mu-sigil-function { color: #40a02b; }
        .mu-container.light .mu-sigil-metadata { color: #1e66f5; }
        .mu-container.light .mu-sigil-cond { color: #d20f39; }
        .mu-container.light .mu-annotation { color: #9ca0b0; }
        .mu-container.light .mu-operator { color: #4c4f69; }
        .mu-container.light .mu-keyword { color: #8839ef; }
        .mu-container.light .mu-type { color: #df8e1d; }
        .mu-container.light .mu-name { color: #4c4f69; }
        .mu-container.light .mu-parameter { color: #179299; }
        .mu-container.light .mu-comment { color: #40a02b; font-style: italic; }
        .mu-container.light .mu-string { color: #40a02b; }
        .mu-container.light .mu-number { color: #fe640b; }
        .mu-container.light .mu-punctuation { color: #9ca0b0; }
    </style>
    """

    TOKEN_CLASSES = {
        TokenType.HEADER: "mu-header",
        TokenType.SIGIL_MODULE: "mu-sigil-module",
        TokenType.SIGIL_ENTITY: "mu-sigil-entity",
        TokenType.SIGIL_FUNCTION: "mu-sigil-function",
        TokenType.SIGIL_METADATA: "mu-sigil-metadata",
        TokenType.SIGIL_CONDITIONAL: "mu-sigil-cond",
        TokenType.ANNOTATION: "mu-annotation",
        TokenType.OPERATOR: "mu-operator",
        TokenType.KEYWORD: "mu-keyword",
        TokenType.TYPE: "mu-type",
        TokenType.NAME: "mu-name",
        TokenType.PARAMETER: "mu-parameter",
        TokenType.COMMENT: "mu-comment",
        TokenType.STRING: "mu-string",
        TokenType.NUMBER: "mu-number",
        TokenType.PUNCTUATION: "mu-punctuation",
        TokenType.WHITESPACE: "",
        TokenType.TEXT: "",
    }

    def __init__(self, theme: str = "dark", show_line_numbers: bool = True):
        self.theme = theme
        self.show_line_numbers = show_line_numbers

    def escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def render(self, doc: MUDocument) -> str:
        """Render document as HTML fragment (for embedding)."""
        theme_class = "light" if self.theme == "light" else ""

        lines_html = []
        for i, line_tokens in enumerate(doc.tokens, 1):
            line_parts = []

            if self.show_line_numbers:
                line_parts.append(f'<span class="mu-line-num">{i}</span>')

            for token in line_tokens:
                css_class = self.TOKEN_CLASSES.get(token.type, "")
                escaped = self.escape_html(token.value)
                if css_class:
                    line_parts.append(f'<span class="{css_class}">{escaped}</span>')
                else:
                    line_parts.append(escaped)

            lines_html.append(f'<span class="mu-line">{"".join(line_parts)}</span>')

        content = "\n".join(lines_html)
        return f'<div class="mu-container {theme_class}">\n{content}\n</div>'

    def render_full_page(
        self,
        doc: MUDocument,
        title: str = "MU Output",
    ) -> str:
        """Render document as complete HTML page."""
        content = self.render(doc)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.escape_html(title)}</title>
    {self.CSS_STYLES}
</head>
<body style="margin: 0; padding: 20px; background: {'#eff1f5' if self.theme == 'light' else '#11111b'};">
    <h1 style="font-family: sans-serif; color: {'#4c4f69' if self.theme == 'light' else '#cdd6f4'}; margin-bottom: 20px;">
        {self.escape_html(title)}
    </h1>
    {content}
</body>
</html>
"""


def render_terminal(
    source: str,
    theme: str = "dark",
    line_numbers: bool = False,
) -> str:
    """Convenience function to render MU to terminal with colors.

    Args:
        source: MU format source text
        theme: Color theme ("dark" or "light")
        line_numbers: Include line numbers

    Returns:
        ANSI-colored string for terminal output
    """
    doc = MUDocument.parse(source)
    renderer = TerminalRenderer(theme=theme)

    if line_numbers:
        return renderer.render_with_line_numbers(doc)
    return renderer.render(doc)


def render_html(
    source: str,
    theme: str = "dark",
    full_page: bool = False,
    title: str = "MU Output",
    line_numbers: bool = True,
) -> str:
    """Convenience function to render MU to HTML.

    Args:
        source: MU format source text
        theme: Color theme ("dark" or "light")
        full_page: Generate complete HTML document
        title: Page title (for full_page mode)
        line_numbers: Include line numbers

    Returns:
        HTML string
    """
    doc = MUDocument.parse(source)
    renderer = HTMLRenderer(theme=theme, show_line_numbers=line_numbers)

    if full_page:
        return renderer.render_full_page(doc, title=title)
    return renderer.render(doc)


def view_file(
    file_path: Path,
    output_format: str = "terminal",
    theme: str = "dark",
    line_numbers: bool = False,
) -> str:
    """View a MU file in specified format.

    Args:
        file_path: Path to .mu file
        output_format: "terminal", "html", or "markdown"
        theme: Color theme ("dark" or "light")
        line_numbers: Include line numbers

    Returns:
        Rendered output string
    """
    source = file_path.read_text()

    if output_format == "terminal":
        return render_terminal(source, theme=theme, line_numbers=line_numbers)
    elif output_format == "html":
        title = file_path.stem
        return render_html(
            source,
            theme=theme,
            full_page=True,
            title=title,
            line_numbers=line_numbers,
        )
    elif output_format == "markdown":
        # Wrap in code fence
        return f"```mu\n{source}\n```"
    else:
        return source


__all__ = [
    "TokenType",
    "Token",
    "MUDocument",
    "tokenize_line",
    "TerminalRenderer",
    "HTMLRenderer",
    "render_terminal",
    "render_html",
    "view_file",
]
