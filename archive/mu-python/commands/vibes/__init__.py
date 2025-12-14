"""MU Quick Commands - Developer-friendly CLI with personality.

Quick Commands for common workflows:
- mu grok - Understand code - extract relevant context
- mu omg  - Ship mode - OMEGA compressed context
- mu yolo - Impact check - what breaks if I change this?
- mu sus  - Smell check - warnings before touching code
- mu vibe - Pattern check - does this code fit?
- mu wtf  - Git archaeology - why does this code exist?
- mu zen  - Clean up - clear caches

This module re-exports all vibes commands for backwards compatibility.
Each command is implemented in its own submodule for better organization.
"""

from .grok import grok
from .omg import omg
from .sus import sus
from .vibe import vibe
from .wtf import wtf
from .yolo import yolo
from .zen import zen

__all__ = ["omg", "grok", "wtf", "yolo", "sus", "vibe", "zen"]
