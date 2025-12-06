"""MUQL REPL - Interactive query shell.

Provides an interactive shell for executing MUQL queries.
"""

from __future__ import annotations

import readline
from typing import TYPE_CHECKING

from mu.kernel.muql.engine import MUQLEngine
from mu.kernel.muql.formatter import OutputFormat
from mu.kernel.muql.parser import MUQLSyntaxError

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


# =============================================================================
# REPL Commands
# =============================================================================


HELP_TEXT = """
MUQL Interactive Shell

Commands:
  .help              Show this help message
  .exit, .quit       Exit the shell
  .format <fmt>      Set output format (table, json, csv, tree)
  .explain <query>   Show execution plan without running
  .history           Show query history
  .clear             Clear screen

Query Examples:
  SELECT * FROM functions WHERE complexity > 20
  SELECT COUNT(*) FROM classes
  SHOW dependencies OF MUbase DEPTH 2
  FIND functions MATCHING "test_%"
  PATH FROM cli TO parser MAX DEPTH 5
  ANALYZE complexity
  ANALYZE hotspots FOR kernel
"""


# =============================================================================
# REPL Class
# =============================================================================


class MUQLREPL:
    """Interactive MUQL query shell."""

    def __init__(self, db: MUbase, no_color: bool = False) -> None:
        """Initialize the REPL.

        Args:
            db: The MUbase database to query.
            no_color: If True, disable ANSI colors.
        """
        self._engine = MUQLEngine(db)
        self._format = OutputFormat.TABLE
        self._no_color = no_color
        self._history: list[str] = []

        # Setup readline
        try:
            readline.parse_and_bind("tab: complete")
            readline.set_history_length(100)
        except Exception:
            pass  # readline not available

    def run(self) -> None:
        """Start the interactive REPL."""
        self._print_banner()

        while True:
            try:
                line = input("muql> ").strip()
                if not line:
                    continue

                # Handle special commands
                if line.startswith("."):
                    if self._handle_command(line):
                        continue
                    else:
                        break  # Exit command

                # Execute query
                self._execute_query(line)

            except KeyboardInterrupt:
                print("\n(Use .exit to quit)")
            except EOFError:
                print()
                break

        print("Goodbye!")

    def _print_banner(self) -> None:
        """Print the REPL banner."""
        print("MUQL Interactive Shell")
        print("Type .help for help, .exit to quit")
        print()

    def _handle_command(self, line: str) -> bool:
        """Handle a dot command.

        Returns:
            True to continue REPL, False to exit.
        """
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in (".exit", ".quit", ".q"):
            return False

        elif cmd in (".help", ".h", ".?"):
            print(HELP_TEXT)

        elif cmd == ".format":
            self._set_format(arg)

        elif cmd == ".explain":
            self._explain_query(arg)

        elif cmd == ".history":
            self._show_history()

        elif cmd == ".clear":
            print("\033[2J\033[H")  # ANSI clear screen

        else:
            print(f"Unknown command: {cmd}")
            print("Type .help for available commands")

        return True

    def _set_format(self, fmt: str) -> None:
        """Set the output format."""
        fmt = fmt.lower().strip()
        try:
            self._format = OutputFormat(fmt)
            print(f"Output format set to: {fmt}")
        except ValueError:
            print(f"Unknown format: {fmt}")
            print("Available formats: table, json, csv, tree")

    def _explain_query(self, query: str) -> None:
        """Explain a query's execution plan."""
        if not query:
            print("Usage: .explain <query>")
            return

        explanation = self._engine.explain(query)
        print(explanation)

    def _show_history(self) -> None:
        """Show query history."""
        if not self._history:
            print("No query history")
            return

        for i, query in enumerate(self._history[-10:], 1):
            print(f"  {i}. {query}")

    def _execute_query(self, query: str) -> None:
        """Execute a MUQL query."""
        self._history.append(query)

        try:
            output = self._engine.query(query, self._format, self._no_color)
            print(output)
        except MUQLSyntaxError as e:
            print(f"Syntax error: {e}")
        except Exception as e:
            print(f"Error: {e}")


# =============================================================================
# Main Function
# =============================================================================


def run_repl(db: MUbase, no_color: bool = False) -> None:
    """Run the MUQL REPL.

    Args:
        db: The MUbase database to query.
        no_color: If True, disable ANSI colors.
    """
    repl = MUQLREPL(db, no_color)
    repl.run()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "MUQLREPL",
    "run_repl",
]
