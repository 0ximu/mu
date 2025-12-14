"""MU compress command - Compress source code into MU format."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command()
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
    type=click.Choice(["mu", "json", "markdown", "lisp", "omega"]),
    default="mu",
    help="Output format (omega = macro-compressed S-expressions)",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--no-cache", is_flag=True, help="Disable caching (process all files fresh)")
@click.option(
    "--detail",
    "-d",
    type=click.Choice(["low", "medium", "high"]),
    default="medium",
    help="Output detail level: low (minimal), medium (balanced), high (verbose with deps)",
)
@click.pass_obj
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
    detail: str,
) -> None:
    """Compress source code into MU format.

    Transforms source code into token-efficient semantic representation.

    \b
    Detail levels:
      low    - Function signatures only
      medium - Signatures + types + key dependencies (default)
      high   - Full context including docstrings and all dependencies
    """
    import asyncio

    from mu.assembler import assemble
    from mu.assembler.exporters import export_json, export_lisp, export_markdown, export_mu
    from mu.cache import CacheManager
    from mu.config import MUConfig
    from mu.logging import (
        console,
        create_progress,
        print_info,
        print_success,
        print_warning,
    )
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase_auto
    from mu.security import DEFAULT_PATTERNS, SecretScanner, load_custom_patterns

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
            ctx.config.llm.provider = cast(
                Literal["anthropic", "openai", "ollama", "openrouter"], llm_provider
            )
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
    ctx.config.output.format = cast(Literal["mu", "json", "markdown", "lisp", "omega"], format)

    # Local-only mode validation
    if local:
        print_info("Local-only mode: using Ollama, no data sent externally")

    # Initialize cache manager
    # Use parent directory for cache when compressing a single file
    cache_base = path.resolve().parent if path.is_file() else path.resolve()
    cache_manager = CacheManager(ctx.config.cache, cache_base)

    # Step 1: Scan codebase
    print_info(f"Scanning {path}...")
    scan_result = scan_codebase_auto(path, ctx.config)

    if scan_result.stats.total_files == 0:
        print_warning("No supported files found")
        return

    print_info(f"Found {scan_result.stats.total_files} files")

    # Check codebase cache (skip expensive work if output is already cached)
    # Cache key includes: file hashes + all flags that affect output
    file_hashes = [f.hash for f in scan_result.files if f.hash]
    codebase_hash = CacheManager.compute_codebase_hash(file_hashes)
    # Include all flags that affect output in the cache key
    cache_format_key = (
        f"{format}:llm={ctx.config.llm.enabled}"
        f":redact={ctx.config.security.redact_secrets}"
        f":shell_safe={shell_safe}"
        f":detail={detail}"
    )

    cached = cache_manager.get_codebase_result(codebase_hash, cache_format_key)
    if cached:
        print_info(f"Using cached result ({cached.file_count} files)")
        if output:
            output.write_text(cached.output)
            print_success(f"Output written to {output}")
        else:
            # Use markup=False to prevent Rich from interpreting [...] as tags
            console.print(cached.output, markup=False)
        cache_manager.close()
        return

    # Step 2: Parse files
    parsed_modules: list[ModuleDef] = []
    skipped_files: dict[str, list[str]] = {}  # language -> [paths]
    failed_files: list[tuple[str, str]] = []  # (path, error)

    # Determine base path for constructing file paths
    # When compressing a single file, path.is_file() is True and file_info.path is just the filename
    is_single_file = path.is_file()

    with create_progress() as progress:
        task = progress.add_task("Parsing files...", total=len(scan_result.files))

        for file_info in scan_result.files:
            # For single file, use the original path directly; for directories, join with relative path
            file_path = path if is_single_file else path / file_info.path
            result = parse_file(file_path, file_info.language)

            if result.success and result.module is not None:
                parsed_modules.append(result.module)
            elif result.error and "Unsupported language" in result.error:
                # Non-code files (markdown, json, etc.) - group by language
                lang = file_info.language
                if lang not in skipped_files:
                    skipped_files[lang] = []
                skipped_files[lang].append(file_info.path)
            else:
                # Actual parse error
                failed_files.append((file_info.path, result.error or "Unknown error"))

            progress.advance(task)

    print_info(f"Parsed {len(parsed_modules)} files successfully")
    if skipped_files:
        total_skipped = sum(len(paths) for paths in skipped_files.values())
        langs = ", ".join(f"{lang} ({len(paths)})" for lang, paths in sorted(skipped_files.items()))
        print_info(f"Skipped {total_skipped} non-code files: {langs}")
    if failed_files:
        print_warning(f"Failed to parse {len(failed_files)} files:")
        for filepath, error in failed_files[:5]:  # Show first 5 errors
            print_warning(f"  {filepath}: {error}")
        if len(failed_files) > 5:
            print_warning(f"  ... and {len(failed_files) - 5} more")

    # Step 2.5: Secret scanning and redaction (if enabled)
    total_secrets_found = 0
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

    # Step 3: Apply transformation rules based on detail level
    if detail == "low":
        # Minimal output - signatures only
        rules = TransformationRules(
            strip_stdlib_imports=True,
            strip_relative_imports=True,
            strip_dunder_methods=True,
            strip_property_getters=True,
            strip_empty_methods=True,
            include_docstrings=False,
            include_decorators=False,
            include_type_annotations=False,
            complexity_threshold_for_llm=ctx.config.reducer.complexity_threshold,
        )
    elif detail == "high":
        # Verbose output - include everything
        rules = TransformationRules(
            strip_stdlib_imports=False,
            strip_relative_imports=False,
            strip_dunder_methods=False,
            strip_property_getters=False,
            strip_empty_methods=False,
            include_docstrings=True,
            include_decorators=True,
            include_type_annotations=True,
            complexity_threshold_for_llm=ctx.config.reducer.complexity_threshold,
        )
    else:
        # Medium (default) - balanced
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
        from mu.extras.llm import (
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
                            if (
                                req.function_name == summarize_result.function_name
                                and req.file_path is not None
                            ):
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
    if format == "omega":
        # OMEGA requires graph intelligence - build in-memory MUbase
        from mu.kernel.export.omega import OmegaExporter, OmegaExportOptions
        from mu.kernel.mubase import MUbase

        print_info("Building intelligence graph...")
        mubase = MUbase(":memory:")
        mubase.build(parsed_modules, path.resolve())

        print_info("Synthesizing macros and compressing...")
        exporter = OmegaExporter()
        export_result = exporter.export(
            mubase,
            OmegaExportOptions(
                include_synthesized=True,
                max_synthesized_macros=5,
                include_header=True,
                pretty_print=True,
            ),
        )

        output_str = export_result.output

        # Report node/edge counts
        print_info(f"  {export_result.node_count} nodes exported")

        mubase.close()

    elif format == "json":
        output_str = export_json(assembled, include_full_graph=True, pretty=True)
    elif format == "markdown":
        output_str = export_markdown(assembled)
    elif format == "lisp":
        output_str = export_lisp(assembled, pretty=True)
    else:
        # MU format
        output_str = export_mu(assembled, shell_safe=shell_safe)

    # Cache the result for future runs
    cache_manager.set_codebase_result(
        codebase_hash=codebase_hash,
        output=output_str,
        output_format=cache_format_key,
        file_count=len(scan_result.files),
    )

    if output:
        output.write_text(output_str)
        print_success(f"Output written to {output}")
    else:
        # Use markup=False to prevent Rich from interpreting [...] as tags
        console.print(output_str, markup=False)

    # Close cache manager
    cache_manager.close()


__all__ = ["compress"]
