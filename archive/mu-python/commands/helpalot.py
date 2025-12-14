"""Help command - show ALL available MU commands."""

import click


@click.command("?")
def helpalot() -> None:
    """Show ALL commands.

    While `mu --help` shows the essentials, this reveals everything.
    """
    help_text = """
\033[1mMU - Machine Understanding for Codebases\033[0m
\033[2mThe complete command reference\033[0m

\033[1;36mVibes (fun aliases):\033[0m
  grok         Extract relevant context for a question
  omg          OMEGA compressed context (ship mode)
  yolo         Impact check - what breaks if I change this?
  sus          Smell check - warnings before touching code
  vibe         Pattern check - does this code fit?
  wtf          Git archaeology - why does this code exist?
  zen          Clean up caches

\033[1;36mCore:\033[0m
  bootstrap    Initialize MU for a codebase (one-step setup)
  status       Show MU status and next recommended action
  compress     Compress code to MU format

\033[1;36mQuery:\033[0m
  q            Execute MUQL queries (short for 'query')
  query        Execute MUQL queries (verbose alias)
  read         Read source code for a specific node
  search       Semantic search for code entities

\033[1;36mGraph:\033[0m
  deps         Show what a node depends on (or reverse with -r)
  impact       What breaks if I change this node?
  ancestors    What does this node depend on?
  cycles       Find circular dependencies
  related      Find files that typically change together

\033[1;36mIntelligence:\033[0m
  patterns     Detect codebase patterns (naming, architecture, etc.)
  diff         Semantic diff between git refs

\033[1;36mHistory (Temporal):\033[0m
  snapshot     Create a temporal snapshot at current commit
  snapshots    List all temporal snapshots
  history      Show change history for a node
  blame        Show who last modified each aspect of a node

\033[1;36mExport:\033[0m
  export       Export graph in various formats (mu, json, mermaid, d2, etc.)
  embed        Generate embeddings for semantic search

\033[1;36mServices:\033[0m
  serve        Start MU daemon (HTTP/WebSocket API)
  mcp          MCP server for AI assistants (Claude Code, etc.)

\033[1;36mUtilities:\033[0m
  cache        Manage MU cache (stats, clear, expire)
  migrate      Migrate legacy MU files to new structure
  view         Render .mu files with syntax highlighting
  describe     CLI introspection for AI agents

\033[1;36mAdvanced:\033[0m
  kernel       Low-level graph database operations
  sigma        Training data generation pipeline

\033[2mUse 'mu <command> --help' for details on any command.\033[0m
"""
    click.echo(help_text)
