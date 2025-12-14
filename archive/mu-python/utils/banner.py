"""MU CLI Banner - ASCII art banner for the MU CLI."""

# ANSI escape codes
RED = "\x1b[31m"
RESET = "\x1b[0m"

BANNER = """\
┌─────────────────────────────────────────┐
│                                         │
│        ███╗   ███╗ ██╗   ██╗            │
│        ████╗ ████║ ██║   ██║            │
│        ██╔████╔██║ ██║   ██║            │
│        ██║╚██╔╝██║ ██║   ██║            │
│        ██║ ╚═╝ ██║ ╚██████╔╝            │
│        ╚═╝     ╚═╝  ╚═════╝             │
│                                         │
│      Machine Understanding Format       │
│      Semantic compression for LLMs      │
│                                         │
└─────────────────────────────────────────┘"""


def print_banner() -> None:
    """Print the MU CLI banner in red."""
    print(f"{RED}{BANNER}{RESET}")
