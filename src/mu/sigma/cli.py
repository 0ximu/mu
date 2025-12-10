"""CLI commands for MU-SIGMA.

Provides commands for running the training data pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click

from mu.sigma.config import SigmaConfig, get_default_config_toml

logger = logging.getLogger(__name__)


@click.group()
@click.option("--config", "-c", type=click.Path(path_type=Path), help="Config file path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def sigma(ctx: click.Context, config: Path | None, verbose: bool) -> None:
    """MU-SIGMA: Training data pipeline for structure-aware embeddings.

    Generate synthetic training pairs from code graphs to fine-tune
    embeddings that understand code structure, not just text.
    """
    ctx.ensure_object(dict)

    # Configure logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load config
    ctx.obj["config"] = SigmaConfig.load(config)
    ctx.obj["verbose"] = verbose


@sigma.command()
@click.option(
    "--languages",
    "-l",
    multiple=True,
    default=None,
    help="Languages to fetch (can specify multiple)",
)
@click.option("--count", "-n", default=None, type=int, help="Repos per language")
@click.option("--min-stars", default=None, type=int, help="Minimum stars")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: data/sigma/repos.json)",
)
@click.option("--force", "-f", is_flag=True, help="Overwrite existing repos file")
@click.pass_context
def fetch(
    ctx: click.Context,
    languages: tuple[str, ...],
    count: int | None,
    min_stars: int | None,
    output: Path | None,
    force: bool,
) -> None:
    """Fetch top GitHub repositories by stars.

    Fetches repositories for specified languages, sorted by stars.
    Results are saved to repos.json for use by the pipeline.

    Examples:
        mu sigma fetch
        mu sigma fetch -l python -l typescript -n 100
        mu sigma fetch --min-stars 1000
    """
    from mu.sigma.repos import load_repos, save_repos

    config: SigmaConfig = ctx.obj["config"]

    # Apply CLI overrides
    if languages:
        config.repos.languages = list(languages)
    if count is not None:
        config.repos.repos_per_language = count
    if min_stars is not None:
        config.repos.min_stars = min_stars

    output_path = output or config.paths.repos_file

    # Check for existing
    if output_path.exists() and not force:
        existing = load_repos(output_path)
        click.echo(f"Found {len(existing)} existing repos in {output_path}")
        click.echo("Use --force to refetch")
        return

    click.echo(f"Fetching top repos for: {', '.join(config.repos.languages)}")
    click.echo(f"  {config.repos.repos_per_language} per language")
    click.echo(f"  Minimum stars: {config.repos.min_stars}")

    def on_progress(completed: int, total: int) -> None:
        click.echo(f"  Progress: {completed}/{total} languages")

    async def run() -> None:
        from mu.sigma.repos import fetch_top_repos

        repos = await fetch_top_repos(config, on_progress)
        save_repos(repos, output_path)
        click.echo(f"\nFetched {len(repos)} repositories")
        click.echo(f"Saved to: {output_path}")

        # Show summary
        by_language: dict[str, int] = {}
        for repo in repos:
            by_language[repo.language] = by_language.get(repo.language, 0) + 1

        for lang, cnt in sorted(by_language.items()):
            click.echo(f"  {lang}: {cnt} repos")

    asyncio.run(run())


@sigma.command()
@click.option("--resume", is_flag=True, help="Resume from checkpoint")
@click.option("--repo", help="Process single repo (for testing)")
@click.option("--dry-run", is_flag=True, help="Show what would be processed")
@click.option("--limit", "-n", type=int, help="Limit number of repos to process")
@click.pass_context
def run(
    ctx: click.Context,
    resume: bool,
    repo: str | None,
    dry_run: bool,
    limit: int | None,
) -> None:
    """Run the training data pipeline.

    Processes repositories to generate training pairs:
    1. Clone each repository
    2. Build .mubase graph
    3. Generate questions (Haiku)
    4. Generate answers (Sonnet)
    5. Validate answers (Haiku)
    6. Extract training pairs
    7. Export to parquet

    Examples:
        mu sigma run
        mu sigma run --resume
        mu sigma run --repo owner/repo
        mu sigma run --limit 10 --dry-run
    """
    from mu.sigma.models import RepoInfo
    from mu.sigma.orchestrator import run_pipeline_sync
    from mu.sigma.repos import load_repos

    config: SigmaConfig = ctx.obj["config"]
    config.ensure_directories()

    # Load repos
    if repo:
        # Single repo mode
        repos = [
            RepoInfo(
                name=repo,
                url=f"https://github.com/{repo}.git",
                stars=0,
                language="python",  # Will be detected
                size_kb=0,
            )
        ]
    else:
        repos = load_repos(config.paths.repos_file)
        if not repos:
            click.echo("No repos found. Run 'mu sigma fetch' first.")
            click.echo(f"Expected file: {config.paths.repos_file}")
            return

    if limit:
        repos = repos[:limit]

    # Show cost estimate
    estimate = config.estimate_cost(len(repos))
    click.echo("\nPipeline Configuration:")
    click.echo(f"  Repos to process: {len(repos)}")
    click.echo(f"  Questions per repo: {config.pipeline.questions_per_repo}")
    click.echo("\nCost Estimate:")
    click.echo(f"  Haiku tokens: ~{estimate['haiku_tokens']:,}")
    click.echo(f"  Sonnet tokens: ~{estimate['sonnet_tokens']:,}")
    click.echo(f"  Estimated cost: ${estimate['total_cost_usd']:.2f}")
    click.echo(f"  Within budget: {'Yes' if estimate['within_budget'] else 'NO - EXCEEDS LIMIT'}")

    if dry_run:
        click.echo("\n[DRY RUN] Would process these repos:")
        for r in repos[:10]:
            click.echo(f"  - {r.name} ({r.stars} stars)")
        if len(repos) > 10:
            click.echo(f"  ... and {len(repos) - 10} more")
        return

    if not estimate["within_budget"]:
        if not click.confirm("\nCost exceeds budget. Continue anyway?"):
            return

    click.echo("\nStarting pipeline...")

    def on_progress(status: str, completed: int, total: int) -> None:
        pct = (completed / total * 100) if total > 0 else 0
        click.echo(f"[{completed}/{total}] ({pct:.0f}%) {status}")

    stats = run_pipeline_sync(config, repos, on_progress)

    # Show results
    click.echo("\n" + "=" * 50)
    click.echo("PIPELINE COMPLETE")
    click.echo("=" * 50)
    click.echo("\nRepos:")
    click.echo(f"  Total: {stats.total_repos}")
    click.echo(f"  Successful: {stats.successful_repos}")
    click.echo(f"  Failed: {stats.failed_repos}")
    click.echo(f"  Success rate: {stats.success_rate:.1f}%")
    click.echo("\nGraph:")
    click.echo(f"  Total nodes: {stats.total_nodes:,}")
    click.echo(f"  Total edges: {stats.total_edges:,}")
    click.echo("\nQ&A:")
    click.echo(f"  Questions generated: {stats.questions_generated:,}")
    click.echo(f"  Answers generated: {stats.answers_generated:,}")
    click.echo(f"  Pairs validated: {stats.qa_pairs_validated:,}")
    click.echo(f"  Pairs accepted: {stats.qa_pairs_accepted:,}")
    click.echo(f"  Validation rate: {stats.validation_rate:.1f}%")
    click.echo("\nTraining Pairs:")
    click.echo(f"  Structural: {stats.structural_pairs:,}")
    click.echo(f"  Q&A: {stats.qa_training_pairs:,}")
    click.echo(f"  TOTAL: {stats.total_training_pairs:,}")
    click.echo(f"\nDuration: {stats.total_duration_seconds / 60:.1f} minutes")
    click.echo(f"Output: {config.paths.training_dir}")


@sigma.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show pipeline statistics.

    Displays statistics from the most recent pipeline run,
    including repos processed, pairs generated, and costs.
    """
    from mu.sigma.models import Checkpoint

    config: SigmaConfig = ctx.obj["config"]

    checkpoint = Checkpoint.load(config.paths.checkpoint_file)
    if not checkpoint:
        click.echo("No pipeline data found. Run 'mu sigma run' first.")
        return

    s = checkpoint.stats

    click.echo("MU-SIGMA Pipeline Statistics")
    click.echo("=" * 40)
    click.echo(f"\nLast run: {checkpoint.timestamp}")
    click.echo("\nRepos:")
    click.echo(f"  Total: {s.total_repos}")
    click.echo(f"  Processed: {s.processed_repos}")
    click.echo(f"  Successful: {s.successful_repos}")
    click.echo(f"  Failed: {s.failed_repos}")
    click.echo(f"  Success rate: {s.success_rate:.1f}%")
    click.echo("\nGraph:")
    click.echo(f"  Total nodes: {s.total_nodes:,}")
    click.echo(f"  Total edges: {s.total_edges:,}")
    click.echo("\nQ&A:")
    click.echo(f"  Questions: {s.questions_generated:,}")
    click.echo(f"  Validated: {s.qa_pairs_validated:,}")
    click.echo(f"  Accepted: {s.qa_pairs_accepted:,}")
    click.echo(f"  Validation rate: {s.validation_rate:.1f}%")
    click.echo("\nTraining Pairs:")
    click.echo(f"  Structural: {s.structural_pairs:,}")
    click.echo(f"  Q&A: {s.qa_training_pairs:,}")
    click.echo(f"  TOTAL: {s.total_training_pairs:,}")


@sigma.command()
@click.argument("parquet_path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--sample", "-n", default=10, help="Number of samples to show")
@click.option("--type", "-t", "pair_type", help="Filter by pair type")
@click.pass_context
def inspect(
    ctx: click.Context,
    parquet_path: Path | None,
    sample: int,
    pair_type: str | None,
) -> None:
    """Inspect training data.

    Shows samples from the generated training pairs,
    with optional filtering by pair type.

    Examples:
        mu sigma inspect
        mu sigma inspect --sample 20
        mu sigma inspect --type qa_relevance
    """
    config: SigmaConfig = ctx.obj["config"]

    path = parquet_path or config.paths.training_dir / "training_pairs.parquet"

    if not path.exists():
        # Try JSON fallback
        json_path = config.paths.training_dir / "training_pairs.json"
        if json_path.exists():
            import json

            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            click.echo(f"Loaded {len(data)} pairs from JSON")
        else:
            click.echo(f"No training data found at {path}")
            click.echo("Run 'mu sigma run' first.")
            return
    else:
        try:
            import pandas as pd

            df = pd.read_parquet(path)
            data = df.to_dict("records")
            click.echo(f"Loaded {len(data)} pairs from parquet")
        except ImportError:
            click.echo("pandas/pyarrow required for parquet. Install with:")
            click.echo("  uv add pandas pyarrow")
            return

    # Filter by type if specified
    if pair_type:
        data = [d for d in data if d.get("pair_type") == pair_type]
        click.echo(f"Filtered to {len(data)} pairs of type '{pair_type}'")

    # Show distribution
    type_counts: dict[str, int] = {}
    for d in data:
        pt = d.get("pair_type", "unknown")
        type_counts[pt] = type_counts.get(pt, 0) + 1

    click.echo("\nPair Type Distribution:")
    for pt, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = cnt / len(data) * 100
        click.echo(f"  {pt}: {cnt:,} ({pct:.1f}%)")

    # Show samples
    import random

    samples = random.sample(data, min(sample, len(data)))

    click.echo(f"\nSample Pairs ({len(samples)}):")
    click.echo("-" * 60)

    for i, pair in enumerate(samples, 1):
        click.echo(f"\n[{i}] Type: {pair.get('pair_type')} (weight: {pair.get('weight', 0):.2f})")
        click.echo(f"    Repo: {pair.get('source_repo')}")
        click.echo(f"    Anchor: {pair.get('anchor', '')[:80]}...")
        click.echo(f"    Positive: {pair.get('positive')}")
        click.echo(f"    Negative: {pair.get('negative')}")


@sigma.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path(".sigmarc.toml"),
    help="Output path",
)
def init(output: Path) -> None:
    """Initialize configuration file.

    Creates a .sigmarc.toml with default settings that can be customized.
    """
    if output.exists():
        click.echo(f"Config file already exists: {output}")
        if not click.confirm("Overwrite?"):
            return

    output.write_text(get_default_config_toml())
    click.echo(f"Created config file: {output}")
    click.echo("\nEdit this file to customize pipeline settings.")


@sigma.command()
@click.pass_context
def clean(ctx: click.Context) -> None:
    """Clean up pipeline data.

    Removes temporary files including:
    - Cloned repositories
    - Checkpoint file

    Does NOT remove:
    - .mubase files (can be reused)
    - Q&A pairs (for inspection)
    - Training data (the output)
    """
    import shutil

    config: SigmaConfig = ctx.obj["config"]

    click.echo("Cleaning up pipeline data...")

    # Clean clones
    if config.paths.clones_dir.exists():
        shutil.rmtree(config.paths.clones_dir)
        click.echo(f"  Removed: {config.paths.clones_dir}")

    # Clean checkpoint
    if config.paths.checkpoint_file.exists():
        config.paths.checkpoint_file.unlink()
        click.echo(f"  Removed: {config.paths.checkpoint_file}")

    click.echo("Done.")


def register_sigma_commands(cli: click.Group) -> None:
    """Register sigma commands with main CLI."""
    cli.add_command(sigma)
