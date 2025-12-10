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
    help="Output file (default: {data-dir}/repos.json)",
)
@click.option("--force", "-f", is_flag=True, help="Overwrite existing repos file")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.pass_context
def fetch(
    ctx: click.Context,
    languages: tuple[str, ...],
    count: int | None,
    min_stars: int | None,
    output: Path | None,
    force: bool,
    data_dir: Path | None,
) -> None:
    """Fetch top GitHub repositories by stars.

    Fetches repositories for specified languages, sorted by stars.
    Results are saved to repos.json for use by the pipeline.

    Examples:
        mu sigma fetch
        mu sigma fetch -l python -l typescript -n 100
        mu sigma fetch --min-stars 1000 --data-dir data/sigma-python
    """
    from mu.sigma.repos import load_repos, save_repos

    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override first (affects all derived paths)
    if data_dir:
        config = config.with_data_dir(data_dir)

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
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.pass_context
def run(
    ctx: click.Context,
    resume: bool,
    repo: str | None,
    dry_run: bool,
    limit: int | None,
    data_dir: Path | None,
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
        mu sigma run --data-dir data/sigma-rust
    """
    from mu.sigma.models import RepoInfo
    from mu.sigma.orchestrator import run_pipeline_sync
    from mu.sigma.repos import load_repos

    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override first (affects all derived paths)
    if data_dir:
        config = config.with_data_dir(data_dir)

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
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.pass_context
def stats(ctx: click.Context, data_dir: Path | None) -> None:
    """Show pipeline statistics.

    Displays statistics from the most recent pipeline run,
    including repos processed, pairs generated, and costs.

    Examples:
        mu sigma stats
        mu sigma stats --data-dir data/sigma-rust
    """
    from mu.sigma.models import Checkpoint

    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override
    if data_dir:
        config = config.with_data_dir(data_dir)

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
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.pass_context
def inspect(
    ctx: click.Context,
    parquet_path: Path | None,
    sample: int,
    pair_type: str | None,
    data_dir: Path | None,
) -> None:
    """Inspect training data.

    Shows samples from the generated training pairs,
    with optional filtering by pair type.

    Examples:
        mu sigma inspect
        mu sigma inspect --sample 20
        mu sigma inspect --type qa_relevance
        mu sigma inspect --data-dir data/sigma-rust
    """
    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override
    if data_dir:
        config = config.with_data_dir(data_dir)

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
@click.option(
    "--input",
    "-i",
    "input_path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to training_pairs.json (default: {data-dir}/training/training_pairs.json)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("models/mu-sigma-v1"),
    help="Output directory for trained model",
)
@click.option(
    "--base-model",
    default="all-MiniLM-L6-v2",
    help="Base model to fine-tune",
)
@click.option("--epochs", "-e", default=3, help="Number of training epochs")
@click.option("--batch-size", "-b", default=64, help="Training batch size")
@click.option("--margin", default=0.5, help="Triplet loss margin")
@click.option("--lr", default=2e-5, help="Learning rate")
@click.option("--max-samples", "-n", type=int, help="Limit samples (for testing)")
@click.option("--device", type=click.Choice(["cpu", "cuda", "mps"]), help="Device to use")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.pass_context
def train(
    ctx: click.Context,
    input_path: Path | None,
    output: Path,
    base_model: str,
    epochs: int,
    batch_size: int,
    margin: float,
    lr: float,
    max_samples: int | None,
    device: str | None,
    data_dir: Path | None,
) -> None:
    """Train embedding model on generated triplets.

    Fine-tunes a sentence-transformer model (default: all-MiniLM-L6-v2)
    using triplet loss to learn code structure relationships.

    Examples:
        mu sigma train
        mu sigma train --epochs 5 --batch-size 128
        mu sigma train --max-samples 1000 --device cpu
        mu sigma train -o models/mu-sigma-v2
        mu sigma train --data-dir data/sigma-all
    """
    from mu.sigma.train import TrainingConfig, train_embeddings

    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override first (affects all derived paths)
    if data_dir:
        config = config.with_data_dir(data_dir)

    # Default input path
    data_path = input_path or config.paths.training_dir / "training_pairs.json"

    if not data_path.exists():
        click.echo(f"Training data not found: {data_path}")
        click.echo("Run 'mu sigma run' first to generate training pairs.")
        return

    # Build training config
    train_config = TrainingConfig(
        base_model=base_model,
        output_dir=output,
        epochs=epochs,
        batch_size=batch_size,
        triplet_margin=margin,
        learning_rate=lr,
        max_samples=max_samples,
        device=device,
    )

    click.echo("MU-SIGMA Embedding Training")
    click.echo("=" * 40)
    click.echo(f"\nInput: {data_path}")
    click.echo(f"Output: {output}")
    click.echo(f"Base model: {base_model}")
    click.echo(f"Epochs: {epochs}")
    click.echo(f"Batch size: {batch_size}")
    click.echo(f"Triplet margin: {margin}")
    click.echo(f"Learning rate: {lr}")
    if max_samples:
        click.echo(f"Max samples: {max_samples}")
    click.echo()

    def on_progress(status: str, progress: float) -> None:
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "=" * filled + "-" * (bar_width - filled)
        click.echo(f"[{bar}] {progress * 100:.0f}% {status}")

    result = train_embeddings(data_path, train_config, on_progress)

    if result.success:
        click.echo("\n" + "=" * 40)
        click.echo("TRAINING COMPLETE")
        click.echo("=" * 40)
        click.echo(f"\nModel saved: {result.model_path}")
        click.echo(f"Train samples: {result.train_samples:,}")
        click.echo(f"Eval samples: {result.eval_samples:,}")
        click.echo(f"Epochs completed: {result.epochs_completed}")
        if result.eval_accuracy is not None:
            click.echo(f"Eval accuracy: {result.eval_accuracy:.4f}")
        click.echo("\nTo use the trained model:")
        click.echo("  from sentence_transformers import SentenceTransformer")
        click.echo(f'  model = SentenceTransformer("{result.model_path}")')
    else:
        click.echo(f"\nTraining failed: {result.error}")
        raise SystemExit(1)


@sigma.command()
@click.argument("data_dirs", nargs=-1, type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    required=True,
    help="Output directory for merged data",
)
@click.option("--dry-run", is_flag=True, help="Show what would be merged without writing")
@click.pass_context
def merge(
    ctx: click.Context,
    data_dirs: tuple[Path, ...],
    output: Path,
    dry_run: bool,
) -> None:
    """Merge training data from multiple parallel runs.

    Combines training_pairs.json or training_pairs.parquet files from multiple
    data directories, deduplicates by (anchor, positive, negative) tuple,
    and outputs a merged training_pairs.json file.

    Examples:
        mu sigma merge data/sigma-python data/sigma-rust -o data/sigma-all
        mu sigma merge data/sigma data/sigma-rust data/sigma-go -o data/sigma-combined
        mu sigma merge data/sigma-* -o data/sigma-all --dry-run
    """
    import json

    click.echo("MU-SIGMA Merge")
    click.echo("=" * 40)
    click.echo(f"\nMerging {len(data_dirs)} data directories:")
    for d in data_dirs:
        click.echo(f"  - {d}")
    click.echo(f"\nOutput: {output}")

    # Collect all pairs
    all_pairs: list[dict[str, str | float]] = []
    seen: set[tuple[str, str, str]] = set()
    stats_by_dir: dict[str, dict[str, int]] = {}

    for data_dir in data_dirs:
        json_file = data_dir / "training" / "training_pairs.json"
        parquet_file = data_dir / "training" / "training_pairs.parquet"

        pairs: list[dict[str, str | float]] = []

        # Try JSON first, then Parquet
        if json_file.exists():
            with open(json_file, encoding="utf-8") as f:
                pairs = json.load(f)
            click.echo(f"\n{data_dir}: (JSON)")
        elif parquet_file.exists():
            try:
                import pyarrow.parquet as pq

                table = pq.read_table(parquet_file)
                pairs = table.to_pylist()
                click.echo(f"\n{data_dir}: (Parquet)")
            except ImportError:
                click.echo(f"\nWarning: pyarrow not installed, can't read {parquet_file}")
                stats_by_dir[str(data_dir)] = {"loaded": 0, "unique": 0}
                continue
        else:
            click.echo(f"\nWarning: No training_pairs.json or .parquet in {data_dir}")
            stats_by_dir[str(data_dir)] = {"loaded": 0, "unique": 0}
            continue

        loaded = len(pairs)
        unique = 0

        for pair in pairs:
            key = (pair.get("anchor", ""), pair.get("positive", ""), pair.get("negative", ""))
            if key not in seen:
                seen.add(key)
                all_pairs.append(pair)
                unique += 1

        stats_by_dir[str(data_dir)] = {"loaded": loaded, "unique": unique}
        click.echo(f"  Loaded: {loaded:,} pairs")
        click.echo(f"  New unique: {unique:,} pairs")

    # Summary
    click.echo("\n" + "-" * 40)
    click.echo(f"Total unique pairs: {len(all_pairs):,}")
    click.echo(
        f"Duplicates removed: {sum(s['loaded'] for s in stats_by_dir.values()) - len(all_pairs):,}"
    )

    if dry_run:
        click.echo("\n[DRY RUN] Would write merged data to:")
        click.echo(f"  {output / 'training' / 'training_pairs.json'}")
        return

    # Create output directory
    output_training_dir = output / "training"
    output_training_dir.mkdir(parents=True, exist_ok=True)

    # Write merged file
    output_file = output_training_dir / "training_pairs.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_pairs, f)

    click.echo(f"\nMerged data written to: {output_file}")
    click.echo(f"Total pairs: {len(all_pairs):,}")

    # Also write a merge manifest for traceability
    manifest_file = output / "merge_manifest.json"
    manifest = {
        "source_dirs": [str(d) for d in data_dirs],
        "stats_by_dir": stats_by_dir,
        "total_pairs": len(all_pairs),
        "duplicates_removed": sum(s["loaded"] for s in stats_by_dir.values()) - len(all_pairs),
    }
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    click.echo(f"Merge manifest: {manifest_file}")


@sigma.command()
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.pass_context
def clean(ctx: click.Context, data_dir: Path | None) -> None:
    """Clean up pipeline data.

    Removes temporary files including:
    - Cloned repositories
    - Checkpoint file

    Does NOT remove:
    - .mubase files (can be reused)
    - Q&A pairs (for inspection)
    - Training data (the output)

    Examples:
        mu sigma clean
        mu sigma clean --data-dir data/sigma-rust
    """
    import shutil

    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override
    if data_dir:
        config = config.with_data_dir(data_dir)

    click.echo("Cleaning up pipeline data...")
    click.echo(f"Data directory: {config.paths.data_dir}")

    # Clean clones
    if config.paths.clones_dir.exists():
        shutil.rmtree(config.paths.clones_dir)
        click.echo(f"  Removed: {config.paths.clones_dir}")

    # Clean checkpoint
    if config.paths.checkpoint_file.exists():
        config.paths.checkpoint_file.unlink()
        click.echo(f"  Removed: {config.paths.checkpoint_file}")

    click.echo("Done.")


@sigma.command("retrofit-frameworks")
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    help="Data directory for isolated runs (default: data/sigma)",
)
@click.option("--dry-run", is_flag=True, help="Preview without saving")
@click.pass_context
def retrofit_frameworks(ctx: click.Context, data_dir: Path | None, dry_run: bool) -> None:
    """Add framework tags to existing training pairs.

    Detects frameworks from mubases and updates training pairs that
    don't have framework tags. This is a local operation - no API calls.

    Examples:
        mu sigma retrofit-frameworks
        mu sigma retrofit-frameworks --dry-run
        mu sigma retrofit-frameworks --data-dir data/sigma-all
    """
    import json

    from mu.sigma.frameworks import detect_frameworks
    from mu.sigma.models import TrainingPair

    config: SigmaConfig = ctx.obj["config"]

    # Apply data-dir override
    if data_dir:
        config = config.with_data_dir(data_dir)

    pairs_path = config.paths.training_dir / "training_pairs.json"

    if not pairs_path.exists():
        click.echo(f"No training pairs found at {pairs_path}")
        click.echo("Run 'mu sigma run' first to generate training pairs.")
        return

    click.echo(f"Retrofitting frameworks for {config.paths.data_dir}...")

    # Load existing pairs
    with open(pairs_path, encoding="utf-8") as f:
        data = json.load(f)
    pairs = [TrainingPair.from_dict(d) for d in data]
    click.echo(f"Loaded {len(pairs):,} training pairs")

    # Get unique repos
    repos = {p.source_repo for p in pairs}
    click.echo(f"Found {len(repos)} unique repos")

    # Detect frameworks for each repo's mubase
    repo_frameworks: dict[str, list[str]] = {}
    mubases_found = 0
    for repo in repos:
        # Convert owner/repo to owner__repo for filename
        mubase_name = f"{repo.replace('/', '__')}.mubase"
        mubase_path = config.paths.mubases_dir / mubase_name
        if mubase_path.exists():
            mubases_found += 1
            frameworks = detect_frameworks(mubase_path)
            repo_frameworks[repo] = frameworks
        else:
            repo_frameworks[repo] = []

    click.echo(f"Found {mubases_found}/{len(repos)} mubases")

    # Update pairs with frameworks
    updated = 0
    for pair in pairs:
        if not pair.frameworks:  # Only update if empty
            frameworks = repo_frameworks.get(pair.source_repo, [])
            if frameworks:
                pair.frameworks = frameworks
                updated += 1

    # Report summary
    click.echo()
    click.echo(f"Repos processed: {len(repos)}")
    click.echo(f"Pairs updated: {updated:,}/{len(pairs):,}")

    # Show frameworks per repo (only repos with detected frameworks)
    repos_with_frameworks = sorted(
        [(repo, fw) for repo, fw in repo_frameworks.items() if fw],
        key=lambda x: x[0],
    )
    if repos_with_frameworks:
        click.echo()
        click.echo("Detected frameworks:")
        for repo, fw in repos_with_frameworks:
            click.echo(f"  {repo}: {', '.join(fw)}")

    # Save unless dry-run
    if not dry_run:
        with open(pairs_path, "w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in pairs], f)
        click.echo(f"\nSaved to {pairs_path}")
    else:
        click.echo("\n[DRY RUN] No changes saved")


def register_sigma_commands(cli: click.Group) -> None:
    """Register sigma commands with main CLI."""
    cli.add_command(sigma)
