"""MU CLI - Machine Understanding command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from mu.scanner import ScanResult

import click
from rich.table import Table

from mu import __version__
from mu.config import MUConfig, get_default_config_toml
from mu.errors import ExitCode
from mu.logging import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
    setup_logging,
)

VerbosityLevel = Literal["quiet", "normal", "verbose"]


class MUContext:
    """Shared context for CLI commands."""

    def __init__(self) -> None:
        self.config: MUConfig | None = None
        self.verbosity: VerbosityLevel = "normal"


pass_context = click.make_pass_decorator(MUContext, ensure=True)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-error output")
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.version_option(version=__version__, prog_name="mu")
@pass_context
def cli(ctx: MUContext, verbose: bool, quiet: bool, config: Path | None) -> None:
    """MU - Machine Understanding: Semantic compression for AI-native development.

    Translate codebases into token-efficient representations optimized for LLM comprehension.
    """
    # Determine verbosity
    if quiet:
        ctx.verbosity = "quiet"
    elif verbose:
        ctx.verbosity = "verbose"
    else:
        ctx.verbosity = "normal"

    setup_logging(ctx.verbosity)

    # Load configuration
    try:
        ctx.config = MUConfig.load(config)
    except Exception as e:
        if not quiet:
            print_error(f"Failed to load configuration: {e}")
        # Don't fail here - some commands (like init) don't need config


@cli.command()
@click.option("--force", "-f", is_flag=True, help="Overwrite existing .murc.toml")
@pass_context
def init(ctx: MUContext, force: bool) -> None:
    """Initialize a new .murc.toml configuration file.

    Creates a configuration file with sensible defaults in the current directory.
    """
    config_path = Path.cwd() / ".murc.toml"

    if config_path.exists() and not force:
        print_warning(f"Configuration file already exists: {config_path}")
        print_info("Use --force to overwrite")
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        config_path.write_text(get_default_config_toml())
        print_success(f"Created {config_path}")
        print_info("\nNext steps:")
        print_info("  1. Edit .murc.toml to customize settings")
        print_info("  2. Run 'mu scan .' to analyze your codebase")
        print_info("  3. Run 'mu compress .' to generate MU output")
    except PermissionError:
        print_error(f"Permission denied: {config_path}")
        sys.exit(ExitCode.CONFIG_ERROR)
    except Exception as e:
        print_error(f"Failed to create config file: {e}")
        sys.exit(ExitCode.FATAL_ERROR)


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file for manifest (default: stdout)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@pass_context
def scan(ctx: MUContext, path: Path, output: Path | None, format: str) -> None:
    """Analyze codebase structure and output manifest.

    Walks the filesystem, identifies modules, languages, and structure.
    Filters noise directories (node_modules, .git, etc.).
    """
    from mu.scanner import scan_codebase

    if ctx.config is None:
        ctx.config = MUConfig()

    result = scan_codebase(path, ctx.config)

    if format == "json":
        import json

        output_str = json.dumps(result.to_dict(), indent=2)
    else:
        # Text format summary
        output_str = format_scan_result(result)

    if output:
        output.write_text(output_str)
        print_success(f"Manifest written to {output}")
    else:
        console.print(output_str)


def format_scan_result(result: ScanResult) -> str:
    """Format scan result as human-readable text."""
    lines = [
        f"Scanned: {result.root}",
        f"Files found: {result.stats.total_files}",
        f"Total lines: {result.stats.total_lines}",
        "",
        "Languages:",
    ]
    for lang, count in sorted(result.stats.languages.items(), key=lambda x: -x[1]):
        lines.append(f"  {lang}: {count} files")

    if result.skipped:
        lines.append("")
        lines.append(f"Skipped: {len(result.skipped)} items")

    return "\n".join(lines)


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: stdout)",
)
@click.option("--llm", is_flag=True, help="Enable LLM-enhanced summarization")
@click.option("--local", is_flag=True, help="Local-only mode (no external API calls)")
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic", "openai", "ollama", "openrouter"]),
    help="Override LLM provider",
)
@click.option("--llm-model", help="Override LLM model")
@click.option("--no-redact", is_flag=True, help="Disable secret redaction (use with caution)")
@click.option("--shell-safe", is_flag=True, help="Escape sigils for shell piping")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["mu", "json", "markdown"]),
    default="mu",
    help="Output format",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--no-cache", is_flag=True, help="Disable caching (process all files fresh)")
@pass_context
def compress(
    ctx: MUContext,
    path: Path,
    output: Path | None,
    llm: bool,
    local: bool,
    llm_provider: str | None,
    llm_model: str | None,
    no_redact: bool,
    shell_safe: bool,
    format: str,
    yes: bool,
    no_cache: bool,
) -> None:
    """Compress source code into MU format.

    Transforms source code into token-efficient semantic representation.
    """
    if ctx.config is None:
        ctx.config = MUConfig()

    # Apply CLI overrides to config
    if llm:
        ctx.config.llm.enabled = True
    if local:
        # Local-only mode: force Ollama provider, ensure no cloud LLM calls
        ctx.config.llm.provider = "ollama"
        if llm_provider and llm_provider != "ollama":
            print_warning(f"--local mode overrides --llm-provider={llm_provider} to use ollama")
    if llm_provider:
        if local and llm_provider != "ollama":
            print_warning(f"Ignoring --llm-provider={llm_provider} in local mode")
        elif not local:
            ctx.config.llm.provider = cast(Literal["anthropic", "openai", "ollama", "openrouter"], llm_provider)
    if llm_model:
        ctx.config.llm.model = llm_model
    if no_redact:
        ctx.config.security.redact_secrets = False
        if not local:
            print_warning("Secret redaction disabled. Secrets may be sent to cloud LLMs.")
    if shell_safe:
        ctx.config.output.shell_safe = True
    if no_cache:
        ctx.config.cache.enabled = False
    ctx.config.output.format = cast(Literal["mu", "json", "markdown"], format)

    # Local-only mode validation
    if local:
        print_info("Local-only mode: using Ollama, no data sent externally")

    import asyncio

    from mu.assembler import assemble
    from mu.assembler.exporters import export_json, export_markdown, export_mu
    from mu.cache import CacheManager
    from mu.logging import create_progress
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase
    from mu.security import DEFAULT_PATTERNS, SecretScanner, load_custom_patterns

    # Initialize cache manager
    cache_manager = CacheManager(ctx.config.cache, path.resolve())

    # Step 1: Scan codebase
    print_info(f"Scanning {path}...")
    scan_result = scan_codebase(path, ctx.config)

    if scan_result.stats.total_files == 0:
        print_warning("No supported files found")
        return

    print_info(f"Found {scan_result.stats.total_files} files")

    # Step 2: Parse files
    parsed_modules: list[ModuleDef] = []
    failed_files: list[tuple[str, str | None]] = []

    with create_progress() as progress:
        task = progress.add_task("Parsing files...", total=len(scan_result.files))

        for file_info in scan_result.files:
            file_path = path / file_info.path
            result = parse_file(file_path, file_info.language)

            if result.success and result.module is not None:
                parsed_modules.append(result.module)
            else:
                failed_files.append((file_info.path, result.error))

            progress.advance(task)

    print_info(f"Parsed {len(parsed_modules)} files successfully")
    if failed_files:
        print_warning(f"Failed to parse {len(failed_files)} files")

    # Step 2.5: Secret scanning and redaction (if enabled)
    total_secrets_found = 0
    secret_scanner = None
    if ctx.config.security.redact_secrets:
        # Initialize scanner with appropriate patterns
        patterns = DEFAULT_PATTERNS
        if ctx.config.security.secret_patterns != "default":
            try:
                custom_patterns = load_custom_patterns(ctx.config.security.secret_patterns)
                patterns = custom_patterns + DEFAULT_PATTERNS
            except Exception as e:
                print_warning(f"Failed to load custom patterns: {e}")

        secret_scanner = SecretScanner(patterns=patterns)

        # Scan and redact secrets from function/method bodies
        for module in parsed_modules:
            # Scan top-level functions
            for func in module.functions:
                if func.body_source:
                    secret_result = secret_scanner.scan(func.body_source, redact=True)
                    if secret_result.has_secrets:
                        func.body_source = secret_result.redacted_source
                        total_secrets_found += secret_result.total_secrets_found

            # Scan class methods
            for cls in module.classes:
                for method in cls.methods:
                    if method.body_source:
                        secret_result = secret_scanner.scan(method.body_source, redact=True)
                        if secret_result.has_secrets:
                            method.body_source = secret_result.redacted_source
                            total_secrets_found += secret_result.total_secrets_found

        if total_secrets_found > 0:
            print_info(f"Redacted {total_secrets_found} potential secrets")
    elif not no_redact:
        # Redaction is disabled but user didn't explicitly disable it
        pass  # Normal operation

    # Step 3: Apply transformation rules
    rules = TransformationRules(
        strip_stdlib_imports=True,
        strip_relative_imports=False,
        strip_dunder_methods=True,
        strip_property_getters=True,
        strip_empty_methods=True,
        include_docstrings=False,
        include_decorators=True,
        include_type_annotations=True,
        complexity_threshold_for_llm=ctx.config.reducer.complexity_threshold,
    )

    print_info("Applying transformation rules...")
    reduced = reduce_codebase(parsed_modules, path, rules)

    # Report stats
    stats = reduced.stats
    print_info(
        f"Reduced to {stats['total_classes']} classes, "
        f"{stats['total_functions']} functions, "
        f"{stats['total_methods']} methods"
    )

    if stats.get("needs_llm_summary", 0) > 0:
        print_info(f"  {stats['needs_llm_summary']} functions flagged for LLM summarization")

    # Step 4: LLM summarization (if enabled)
    if ctx.config.llm.enabled and stats.get("needs_llm_summary", 0) > 0:
        from mu.llm import (
            LLMPool,
            LLMProvider,
            SummarizationRequest,
            SummarizationResult,
            estimate_cost,
        )

        # Collect functions needing summarization
        requests: list[SummarizationRequest] = []
        for reduced_module in reduced.modules:
            # Top-level functions
            for func in reduced_module.functions:
                if func.name in reduced_module.needs_llm and func.body_source:
                    requests.append(
                        SummarizationRequest(
                            function_name=func.name,
                            body_source=func.body_source,
                            language=reduced_module.language,
                            context=reduced_module.name,
                            file_path=reduced_module.path,
                        )
                    )
            # Class methods
            for cls in reduced_module.classes:
                for method in cls.methods:
                    key = f"{cls.name}.{method.name}"
                    if key in reduced_module.needs_llm and method.body_source:
                        requests.append(
                            SummarizationRequest(
                                function_name=key,
                                body_source=method.body_source,
                                language=reduced_module.language,
                                context=f"{reduced_module.name}.{cls.name}",
                                file_path=reduced_module.path,
                            )
                        )

        if requests:
            # Estimate cost
            provider = LLMProvider(ctx.config.llm.provider)
            cost_estimate = estimate_cost(requests, ctx.config.llm.model, provider)

            print_info("")
            print_info(cost_estimate.format_summary())

            # Confirm unless --yes
            if not yes and provider != LLMProvider.OLLAMA:
                if not click.confirm("\nProceed with LLM summarization?", default=True):
                    print_info("Skipping LLM summarization")
                    requests = []

            if requests:
                print_info("")
                print_info("Running LLM summarization...")

                # Create pool with persistent caching
                pool = LLMPool(
                    ctx.config.llm,
                    cache_config=ctx.config.cache,
                    cache_base_path=path.resolve(),
                )

                async def run_summarization() -> list[SummarizationResult]:
                    with create_progress() as progress:
                        task = progress.add_task(
                            "Summarizing functions...",
                            total=len(requests),
                        )

                        def on_progress(completed: int, total: int) -> None:
                            progress.update(task, completed=completed)

                        return await pool.summarize_batch(requests, on_progress)

                results = asyncio.run(run_summarization())

                # Inject summaries back into reduced modules
                summaries_by_file: dict[str, dict[str, list[str]]] = {}
                for summarize_result in results:
                    if summarize_result.success:
                        # Find the module this function belongs to
                        for req in requests:
                            if req.function_name == summarize_result.function_name and req.file_path is not None:
                                if req.file_path not in summaries_by_file:
                                    summaries_by_file[req.file_path] = {}
                                summaries_by_file[req.file_path][summarize_result.function_name] = (
                                    summarize_result.summary
                                )
                                break

                # Apply summaries to modules
                for reduced_module in reduced.modules:
                    if reduced_module.path in summaries_by_file:
                        reduced_module.summaries.update(summaries_by_file[reduced_module.path])

                # Report results
                successful = sum(1 for r in results if r.success)
                failed = len(results) - successful
                cached_hits = sum(1 for r in results if r.cached)
                print_info(
                    f"Summarized {successful} functions"
                    + (f" ({failed} failed)" if failed else "")
                    + (f" ({cached_hits} from cache)" if cached_hits else "")
                )
                if pool.stats.total_tokens > 0:
                    print_info(f"  Tokens used: {pool.stats.total_tokens:,}")

                # Close pool to persist cache
                pool.close()

    # Step 5: Assemble (resolve cross-file dependencies)
    print_info("Assembling module graph...")
    assembled = assemble(parsed_modules, reduced, path)

    # Report assembly stats
    internal_deps = assembled.codebase.stats.get("internal_dependencies", 0)
    external_pkgs = len(assembled.external_packages)
    print_info(f"  {internal_deps} internal dependencies, {external_pkgs} external packages")

    # Step 6: Generate output
    if format == "json":
        output_str = export_json(assembled, include_full_graph=True, pretty=True)
    elif format == "markdown":
        output_str = export_markdown(assembled)
    else:
        # MU format
        output_str = export_mu(assembled, shell_safe=shell_safe)

    if output:
        output.write_text(output_str)
        print_success(f"Output written to {output}")
    else:
        console.print(output_str)

    # Close cache manager
    cache_manager.close()


@cli.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "-f",
    type=click.Choice(["terminal", "html", "markdown"]),
    default="terminal",
    help="Output format",
)
@click.option(
    "--theme",
    type=click.Choice(["dark", "light"]),
    default="dark",
    help="Color theme for terminal/HTML output",
)
@click.option(
    "--line-numbers",
    "-n",
    is_flag=True,
    help="Show line numbers",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (for html/markdown formats)",
)
@pass_context
def view(
    ctx: MUContext,
    file: Path,
    format: str,
    theme: str,
    line_numbers: bool,
    output: Path | None,
) -> None:
    """Render MU file in human-readable format.

    Supports terminal output with syntax highlighting, HTML export,
    and markdown code fencing.
    """
    from mu.viewer import view_file

    result = view_file(
        file_path=file,
        output_format=format,
        theme=theme,
        line_numbers=line_numbers,
    )

    if output:
        output.write_text(result)
        print_success(f"Output written to {output}")
    else:
        # For terminal, use rich console; for others, print directly
        if format == "terminal":
            # Print raw ANSI - rich console will handle it
            console.print(result, highlight=False)
        else:
            console.print(result)


@cli.command()
@click.argument("base_ref")
@click.argument("target_ref")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: stdout)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["terminal", "json", "markdown"]),
    default="terminal",
    help="Output format",
)
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=Path("."),
    help="Path to compare (default: current directory)",
)
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output",
)
@pass_context
def diff(
    ctx: MUContext,
    base_ref: str,
    target_ref: str,
    output: Path | None,
    format: str,
    path: Path,
    no_color: bool,
) -> None:
    """Show semantic differences between two git refs (branches, commits, or tags).

    Compares the MU representation of your codebase between BASE_REF and TARGET_REF,
    showing added/removed/modified modules, functions, classes, and dependencies.

    \b
    Examples:
        mu diff main feature-branch     # Compare main to feature branch
        mu diff HEAD~5 HEAD             # Compare last 5 commits
        mu diff v1.0.0 v2.0.0           # Compare tagged releases
        mu diff main HEAD -f json       # Output as JSON
    """
    from mu.assembler import AssembledOutput, assemble
    from mu.diff import (
        SemanticDiffer,
        format_diff,
        format_diff_json,
    )
    from mu.diff.formatters import format_diff_markdown
    from mu.diff.git_utils import GitError, compare_refs
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase

    if ctx.config is None:
        ctx.config = MUConfig()

    print_info(f"Comparing {base_ref} → {target_ref}...")

    try:
        with compare_refs(path, base_ref, target_ref) as (
            base_path,
            target_path,
            base_git_ref,
            target_git_ref,
        ):
            # Shared transformation rules
            rules = TransformationRules(
                strip_stdlib_imports=True,
                strip_relative_imports=False,
                strip_dunder_methods=True,
                strip_property_getters=True,
                strip_empty_methods=True,
                include_docstrings=False,
                include_decorators=True,
                include_type_annotations=True,
            )

            def process_version(version_path: Path, label: str) -> tuple[AssembledOutput | None, list[ModuleDef]]:
                """Process a version of the codebase through the MU pipeline."""
                assert ctx.config is not None
                # Scan
                version_scan_result = scan_codebase(version_path, ctx.config)
                if version_scan_result.stats.total_files == 0:
                    return None, []

                # Parse
                version_modules: list[ModuleDef] = []
                for file_info in version_scan_result.files:
                    file_path = version_path / file_info.path
                    parse_result = parse_file(file_path, file_info.language)
                    if parse_result.success and parse_result.module is not None:
                        version_modules.append(parse_result.module)

                # Reduce
                reduced = reduce_codebase(version_modules, version_path, rules)

                # Assemble
                assembled = assemble(version_modules, reduced, version_path)

                return assembled, version_modules

            # Process both versions
            print_info(f"  Processing {base_ref}...")
            base_assembled, _ = process_version(base_path, base_ref)

            print_info(f"  Processing {target_ref}...")
            target_assembled, _ = process_version(target_path, target_ref)

            if base_assembled is None or target_assembled is None:
                print_warning("No supported files found in one or both refs")
                return

            # Compute diff
            print_info("  Computing semantic diff...")
            differ = SemanticDiffer(
                base_assembled,
                target_assembled,
                base_ref,
                target_ref,
            )
            result = differ.diff()

            # Format output
            if format == "json":
                output_str = format_diff_json(result)
            elif format == "markdown":
                output_str = format_diff_markdown(result)
            else:
                output_str = format_diff(result, no_color=no_color)

            # Write output
            if output:
                output.write_text(output_str)
                print_success(f"Diff written to {output}")
            else:
                console.print(output_str)

    except GitError as e:
        print_error(str(e))
        sys.exit(ExitCode.GIT_ERROR)


@cli.group()
def cache() -> None:
    """Manage MU cache."""
    pass


@cache.command("clear")
@click.option("--llm-only", is_flag=True, help="Only clear LLM response cache")
@click.option("--files-only", is_flag=True, help="Only clear file result cache")
@pass_context
def cache_clear(ctx: MUContext, llm_only: bool, files_only: bool) -> None:
    """Clear all cached data."""
    from mu.cache import CacheManager

    if ctx.config is None:
        ctx.config = MUConfig()

    cache_manager = CacheManager(ctx.config.cache)

    if not cache_manager.cache_dir.exists():
        print_info("Cache directory does not exist")
        return

    if llm_only or files_only:
        # Selective clearing using diskcache
        cache_manager._ensure_initialized()
        if llm_only and cache_manager._llm_cache:
            count = len(cache_manager._llm_cache)
            cache_manager._llm_cache.clear()
            print_success(f"Cleared {count} LLM cache entries")
        if files_only and cache_manager._file_cache:
            count = len(cache_manager._file_cache)
            cache_manager._file_cache.clear()
            print_success(f"Cleared {count} file cache entries")
        cache_manager.close()
    else:
        # Full clear
        cleared = cache_manager.clear()
        print_success(
            f"Cleared cache: {cleared['file_entries']} file entries, "
            f"{cleared['llm_entries']} LLM entries"
        )
        cache_manager.close()


@cache.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@pass_context
def cache_stats(ctx: MUContext, as_json: bool) -> None:
    """Show cache statistics."""
    import json as json_module

    from mu.cache import CacheManager

    if ctx.config is None:
        ctx.config = MUConfig()

    cache_manager = CacheManager(ctx.config.cache)
    stats = cache_manager.get_stats()
    cache_manager.close()

    if as_json:
        console.print(json_module.dumps(stats, indent=2))
        return

    if not stats.get("exists"):
        print_info("Cache is empty")
        return

    table = Table(title="Cache Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Location", stats["directory"])
    table.add_row("Enabled", "Yes" if stats["enabled"] else "No")
    table.add_row("File Entries", str(stats.get("file_entries", 0)))
    table.add_row("LLM Entries", str(stats.get("llm_entries", 0)))
    table.add_row("Disk Files", str(stats.get("file_count", 0)))
    table.add_row("Size", f"{stats.get('size_kb', 0):.1f} KB")
    table.add_row("TTL", f"{stats.get('ttl_hours', 168)} hours")
    table.add_row("", "")
    table.add_row("Cache Hits", str(stats.get("hits", 0)))
    table.add_row("Cache Misses", str(stats.get("misses", 0)))
    table.add_row("Hit Rate", f"{stats.get('hit_rate_percent', 0):.1f}%")

    console.print(table)


@cache.command("expire")
@pass_context
def cache_expire(ctx: MUContext) -> None:
    """Force expiration of old cache entries."""
    from mu.cache import CacheManager

    if ctx.config is None:
        ctx.config = MUConfig()

    cache_manager = CacheManager(ctx.config.cache)

    if not cache_manager.cache_dir.exists():
        print_info("Cache directory does not exist")
        return

    expired = cache_manager.expire_old_entries()
    cache_manager.close()

    if expired > 0:
        print_success(f"Expired {expired} cache entries")
    else:
        print_info("No entries to expire")


# =============================================================================
# Kernel Commands - Graph database operations
# =============================================================================


@cli.group()
def kernel() -> None:
    """MU Kernel commands (graph database).

    Build and query a graph representation of your codebase stored in .mubase.
    """
    pass


@kernel.command("init")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing .mubase file")
def kernel_init(path: Path, force: bool) -> None:
    """Initialize a .mubase graph database.

    Creates an empty .mubase file in the specified directory.
    Use 'mu kernel build' to populate it with your codebase.
    """
    from mu.kernel import MUbase

    mubase_path = path.resolve() / ".mubase"

    if mubase_path.exists() and not force:
        print_warning(f"Database already exists: {mubase_path}")
        print_info("Use --force to overwrite")
        sys.exit(ExitCode.CONFIG_ERROR)

    if mubase_path.exists():
        mubase_path.unlink()

    try:
        db = MUbase(mubase_path)
        db.close()
        print_success(f"Created {mubase_path}")
        print_info("\nNext steps:")
        print_info("  1. Run 'mu kernel build .' to populate the graph")
        print_info("  2. Run 'mu kernel stats' to see graph statistics")
    except Exception as e:
        print_error(f"Failed to create database: {e}")
        sys.exit(ExitCode.FATAL_ERROR)


@kernel.command("build")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output .mubase file (default: {path}/.mubase)",
)
@pass_context
def kernel_build(ctx: MUContext, path: Path, output: Path | None) -> None:
    """Build graph database from codebase.

    Scans the directory, parses all supported files, and builds a
    queryable graph of modules, classes, functions, and their relationships.
    """
    from mu.kernel import MUbase
    from mu.parser.base import parse_file
    from mu.scanner import scan_codebase

    if ctx.config is None:
        ctx.config = MUConfig()

    root_path = path.resolve()
    mubase_path = output or (root_path / ".mubase")

    # Scan codebase
    print_info(f"Scanning {root_path}...")
    scan_result = scan_codebase(root_path, ctx.config)

    if not scan_result.files:
        print_warning("No supported files found")
        return

    print_info(f"Found {len(scan_result.files)} files")

    # Parse all files
    print_info("Parsing files...")
    modules = []
    errors = 0

    for file_info in scan_result.files:
        parsed = parse_file(Path(root_path / file_info.path), file_info.language)
        if parsed.success and parsed.module:
            modules.append(parsed.module)
        elif parsed.error:
            errors += 1
            if ctx.verbosity == "verbose":
                print_warning(f"  Parse error in {file_info.path}: {parsed.error}")

    if errors > 0:
        print_warning(f"  {errors} files had parse errors")

    if not modules:
        print_warning("No modules parsed successfully")
        return

    print_info(f"Parsed {len(modules)} modules")

    # Build graph
    print_info("Building graph...")
    db = MUbase(mubase_path)
    db.build(modules, root_path)
    stats = db.stats()
    db.close()

    print_success(f"Built graph: {stats['nodes']} nodes, {stats['edges']} edges")
    print_info(f"Database: {mubase_path}")

    # Show breakdown
    if ctx.verbosity != "quiet":
        for node_type, count in stats.get("nodes_by_type", {}).items():
            print_info(f"  {node_type}: {count}")


@kernel.command("stats")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_stats(path: Path, as_json: bool) -> None:
    """Show graph database statistics."""
    import json as json_module

    from mu.kernel import MUbase

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel init' and 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)
    stats = db.stats()
    db.close()

    if as_json:
        console.print(json_module.dumps(stats, indent=2, default=str))
        return

    table = Table(title="MU Kernel Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Nodes", str(stats["nodes"]))
    table.add_row("Total Edges", str(stats["edges"]))
    table.add_row("", "")

    # Nodes by type
    for node_type, count in stats.get("nodes_by_type", {}).items():
        table.add_row(f"  {node_type.title()}", str(count))

    table.add_row("", "")

    # Edges by type
    for edge_type, count in stats.get("edges_by_type", {}).items():
        table.add_row(f"  {edge_type.title()} edges", str(count))

    table.add_row("", "")
    table.add_row("File Size", f"{stats.get('file_size_kb', 0):.1f} KB")
    table.add_row("Version", stats.get("version", "unknown"))

    if stats.get("built_at"):
        table.add_row("Built At", str(stats["built_at"]))

    console.print(table)


@kernel.command("query")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--type",
    "-t",
    "node_type",
    type=click.Choice(["module", "class", "function", "external"]),
    help="Filter by node type",
)
@click.option(
    "--complexity",
    "-c",
    type=int,
    help="Minimum complexity threshold",
)
@click.option(
    "--name",
    "-n",
    type=str,
    help="Filter by name (supports % wildcard)",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=20,
    help="Maximum results to show",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_query(
    path: Path,
    node_type: str | None,
    complexity: int | None,
    name: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Query the graph database.

    Examples:

        mu kernel query --type function --complexity 20

        mu kernel query --name "test_%"

        mu kernel query --type class --json
    """
    import json as json_module

    from mu.kernel import MUbase, NodeType

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    # Build query based on options
    nodes = []

    if complexity:
        nodes = db.find_by_complexity(complexity)
    elif name:
        nt = NodeType(node_type) if node_type else None
        nodes = db.find_by_name(name, nt)
    elif node_type:
        nodes = db.get_nodes(NodeType(node_type))
    else:
        nodes = db.get_nodes()

    db.close()

    # Apply limit
    nodes = nodes[:limit]

    if as_json:
        console.print(json_module.dumps([n.to_dict() for n in nodes], indent=2))
        return

    if not nodes:
        print_info("No nodes found matching criteria")
        return

    table = Table(title=f"Query Results ({len(nodes)} nodes)")
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Name", style="green")
    table.add_column("File", style="dim")
    table.add_column("Complexity", style="yellow", justify="right")

    for node in nodes:
        file_display = node.file_path or ""
        if len(file_display) > 40:
            file_display = "..." + file_display[-37:]

        table.add_row(
            node.type.value,
            node.name,
            file_display,
            str(node.complexity) if node.complexity else "",
        )

    console.print(table)


@kernel.command("muql")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.argument("query", required=False)
@click.option("--interactive", "-i", is_flag=True, help="Start interactive REPL")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv", "tree"]),
    default="table",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--explain", is_flag=True, help="Show execution plan without running")
def kernel_muql(
    path: Path,
    query: str | None,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
) -> None:
    """Execute MUQL queries against the graph database.

    MUQL provides an SQL-like query interface for exploring your codebase.

    \b
    Examples:
        # Single query
        mu kernel muql . "SELECT * FROM functions WHERE complexity > 20"

        # Interactive mode
        mu kernel muql . -i

        # Show execution plan
        mu kernel muql . --explain "SELECT * FROM classes LIMIT 10"

        # Output as JSON
        mu kernel muql . -f json "SELECT name, complexity FROM functions"

    \b
    Query Types:
        SELECT - SQL-like queries on nodes
        SHOW   - Dependency and relationship queries
        FIND   - Pattern matching queries
        PATH   - Path finding between nodes
        ANALYZE - Built-in analysis queries

    \b
    In interactive mode, use these commands:
        .help    - Show help
        .format  - Change output format
        .explain - Explain query
        .exit    - Exit REPL
    """
    from mu.kernel import MUbase
    from mu.kernel.muql import MUQLEngine
    from mu.kernel.muql.repl import run_repl

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel init' and 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    try:
        if interactive:
            # Start REPL
            run_repl(db, no_color)
        elif query:
            # Execute single query
            engine = MUQLEngine(db)

            if explain:
                # Show execution plan
                explanation = engine.explain(query)
                console.print(explanation)
            else:
                # Execute and format
                output = engine.query(query, output_format, no_color)
                console.print(output)
        else:
            # No query provided and not interactive mode
            print_error("Either provide a query or use --interactive/-i flag")
            print_info('Example: mu kernel muql . "SELECT * FROM functions LIMIT 10"')
            print_info("         mu kernel muql . -i")
            sys.exit(ExitCode.CONFIG_ERROR)
    finally:
        db.close()


@kernel.command("deps")
@click.argument("node_name", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--depth",
    "-d",
    type=int,
    default=1,
    help="Depth of dependency traversal",
)
@click.option("--reverse", "-r", is_flag=True, help="Show dependents instead of dependencies")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_deps(
    node_name: str,
    path: Path,
    depth: int,
    reverse: bool,
    as_json: bool,
) -> None:
    """Show dependencies or dependents of a node.

    NODE_NAME can be a function, class, or module name.

    Examples:

        mu kernel deps MUbase

        mu kernel deps cli.py --depth 2

        mu kernel deps GraphBuilder --reverse
    """
    import json as json_module

    from mu.kernel import MUbase

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    # Find the node by name
    matching_nodes = db.find_by_name(f"%{node_name}%")

    if not matching_nodes:
        print_error(f"No node found matching '{node_name}'")
        db.close()
        sys.exit(ExitCode.CONFIG_ERROR)

    # Use the first match
    target_node = matching_nodes[0]
    if len(matching_nodes) > 1:
        print_info(
            f"Multiple matches found, using: {target_node.qualified_name or target_node.name}"
        )

    # Get dependencies or dependents
    if reverse:
        related = db.get_dependents(target_node.id, depth=depth)
        relation_type = "Dependents"
    else:
        related = db.get_dependencies(target_node.id, depth=depth)
        relation_type = "Dependencies"

    db.close()

    if as_json:
        result = {
            "node": target_node.to_dict(),
            "relation": "dependents" if reverse else "dependencies",
            "depth": depth,
            "related": [n.to_dict() for n in related],
        }
        console.print(json_module.dumps(result, indent=2))
        return

    print_info(
        f"{relation_type} of {target_node.qualified_name or target_node.name} (depth={depth}):"
    )

    if not related:
        print_info("  (none)")
        return

    for node in related:
        prefix = "  "
        type_str = f"[{node.type.value}]"
        name_str = node.qualified_name or node.name
        print_info(f"{prefix}{type_str} {name_str}")


@kernel.command("embed")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--provider",
    "-p",
    type=click.Choice(["openai", "local"]),
    help="Embedding provider to use (default: from config)",
)
@click.option(
    "--model",
    "-m",
    type=str,
    help="Embedding model to use",
)
@click.option(
    "--batch-size",
    "-b",
    type=int,
    default=100,
    help="Batch size for embedding generation",
)
@click.option(
    "--local",
    is_flag=True,
    help="Force local embeddings (sentence-transformers)",
)
@click.option(
    "--type",
    "-t",
    "node_types",
    type=click.Choice(["module", "class", "function"]),
    multiple=True,
    help="Node types to embed (default: all)",
)
@pass_context
def kernel_embed(
    ctx: MUContext,
    path: Path,
    provider: str | None,
    model: str | None,
    batch_size: int,
    local: bool,
    node_types: tuple[str, ...],
) -> None:
    """Generate embeddings for codebase nodes.

    Creates vector embeddings for code graph nodes to enable semantic search.
    Requires a .mubase file - run 'mu kernel build' first.

    \b
    Examples:
        mu kernel embed .                    # Embed all nodes with OpenAI
        mu kernel embed . --local            # Use local sentence-transformers
        mu kernel embed . --type function    # Only embed functions
        mu kernel embed . --provider openai --model text-embedding-3-large
    """
    import asyncio

    from mu.kernel import MUbase, NodeType
    from mu.kernel.embeddings import EmbeddingService
    from mu.kernel.embeddings.models import NodeEmbedding
    from mu.logging import create_progress

    if ctx.config is None:
        ctx.config = MUConfig()

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Determine provider
    embed_provider = provider
    if local:
        embed_provider = "local"
    elif embed_provider is None:
        embed_provider = ctx.config.embeddings.provider

    # Check for API key if using OpenAI
    if embed_provider == "openai":
        import os

        api_key_env = ctx.config.embeddings.openai.api_key_env
        if not os.environ.get(api_key_env):
            print_error(f"OpenAI API key not found in environment variable {api_key_env}")
            print_info("Set the environment variable or use --local for local embeddings")
            sys.exit(ExitCode.CONFIG_ERROR)

    print_info(f"Using {embed_provider} embedding provider")

    # Open database
    db = MUbase(mubase_path)

    # Get nodes to embed
    nodes = []
    if node_types:
        for nt in node_types:
            nodes.extend(db.get_nodes(NodeType(nt)))
    else:
        # Get all non-external nodes
        for node_type in [NodeType.MODULE, NodeType.CLASS, NodeType.FUNCTION]:
            nodes.extend(db.get_nodes(node_type))

    if not nodes:
        print_warning("No nodes found to embed")
        db.close()
        return

    print_info(f"Found {len(nodes)} nodes to embed")

    # Create embedding service
    service = EmbeddingService(
        config=ctx.config.embeddings,
        provider=embed_provider,
        model=model,
    )

    async def run_embedding() -> list[NodeEmbedding]:
        with create_progress() as progress:
            task = progress.add_task(
                "Generating embeddings...",
                total=len(nodes),
            )

            def on_progress(completed: int, total: int) -> None:
                progress.update(task, completed=completed)

            embeddings = await service.embed_nodes(
                nodes,
                batch_size=batch_size,
                on_progress=on_progress,
            )

            return embeddings

    embeddings = asyncio.run(run_embedding())

    # Store embeddings
    print_info("Storing embeddings...")
    db.add_embeddings_batch(embeddings)

    # Report results
    stats = service.stats
    print_success(f"Generated {stats.successful} embeddings")
    if stats.failed > 0:
        print_warning(f"  {stats.failed} failed")

    # Show embedding stats
    embed_stats = db.embedding_stats()
    print_info(f"  Coverage: {embed_stats['coverage_percent']:.1f}%")

    db.close()

    # Cleanup
    asyncio.run(service.close())


@kernel.command("search")
@click.argument("query", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--limit",
    "-l",
    type=int,
    default=10,
    help="Maximum number of results",
)
@click.option(
    "--type",
    "-t",
    "node_type",
    type=click.Choice(["module", "class", "function"]),
    help="Filter by node type",
)
@click.option(
    "--embedding",
    "-e",
    type=click.Choice(["code", "docstring", "name"]),
    default="code",
    help="Which embedding to search",
)
@click.option(
    "--provider",
    "-p",
    type=click.Choice(["openai", "local"]),
    help="Provider for query embedding (default: from config)",
)
@click.option(
    "--local",
    is_flag=True,
    help="Force local embeddings for query",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
@pass_context
def kernel_search(
    ctx: MUContext,
    query: str,
    path: Path,
    limit: int,
    node_type: str | None,
    embedding: str,
    provider: str | None,
    local: bool,
    as_json: bool,
) -> None:
    """Semantic search for code nodes.

    Search the codebase using natural language queries. Finds nodes
    semantically similar to the query, even if they don't contain
    the exact words.

    \b
    Examples:
        mu kernel search "authentication logic"
        mu kernel search "database connection" --type function
        mu kernel search "error handling" --limit 20 --json
    """
    import asyncio
    import json as json_module

    from mu.kernel import MUbase, NodeType
    from mu.kernel.embeddings import EmbeddingService

    if ctx.config is None:
        ctx.config = MUConfig()

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' and 'mu kernel embed' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Determine provider
    embed_provider = provider
    if local:
        embed_provider = "local"
    elif embed_provider is None:
        embed_provider = ctx.config.embeddings.provider

    # Check for API key if using OpenAI
    if embed_provider == "openai":
        import os

        api_key_env = ctx.config.embeddings.openai.api_key_env
        if not os.environ.get(api_key_env):
            print_error("OpenAI API key not found")
            print_info(f"Set {api_key_env} or use --local for local embeddings")
            sys.exit(ExitCode.CONFIG_ERROR)

    # Open database
    db = MUbase(mubase_path)

    # Check if embeddings exist
    embed_stats = db.embedding_stats()
    if embed_stats["nodes_with_embeddings"] == 0:
        print_error("No embeddings found in database")
        print_info("Run 'mu kernel embed' first to generate embeddings")
        db.close()
        sys.exit(ExitCode.CONFIG_ERROR)

    # Create embedding service for query
    service = EmbeddingService(
        config=ctx.config.embeddings,
        provider=embed_provider,
    )

    # Embed the query
    async def get_query_embedding() -> list[float] | None:
        return await service.embed_query(query)

    print_info(f"Searching for: {query}")
    query_embedding = asyncio.run(get_query_embedding())

    if query_embedding is None:
        print_error("Failed to generate query embedding")
        db.close()
        asyncio.run(service.close())
        sys.exit(ExitCode.FATAL_ERROR)

    # Perform vector search
    nt = NodeType(node_type) if node_type else None
    results = db.vector_search(
        query_embedding=query_embedding,
        embedding_type=embedding,
        limit=limit,
        node_type=nt,
    )

    db.close()
    asyncio.run(service.close())

    if not results:
        print_info("No results found")
        return

    if as_json:
        output = {
            "query": query,
            "results": [
                {
                    "node": node.to_dict(),
                    "similarity": round(score, 4),
                }
                for node, score in results
            ],
        }
        console.print(json_module.dumps(output, indent=2))
        return

    # Display results as table
    table = Table(title=f"Search Results for: {query}")
    table.add_column("Score", style="yellow", width=8)
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Name", style="green")
    table.add_column("File", style="dim")

    for node, score in results:
        file_display = node.file_path or ""
        if len(file_display) > 35:
            file_display = "..." + file_display[-32:]

        table.add_row(
            f"{score:.3f}",
            node.type.value,
            node.name,
            file_display,
        )

    console.print(table)


def _register_doc_commands() -> None:
    """Register documentation commands (lazy import to avoid E402)."""
    from mu.commands.llm_spec import llm_command
    from mu.commands.man import man_command

    cli.add_command(man_command, name="man")
    cli.add_command(llm_command, name="llm")


# Register documentation commands
_register_doc_commands()


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
