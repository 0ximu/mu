"""Pipeline orchestrator for MU-SIGMA.

Coordinates the end-to-end training data generation pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable

from mu.sigma.answers import generate_answers_batch
from mu.sigma.build import build_mubase, get_all_node_names
from mu.sigma.clone import cleanup_clone, clone_repo
from mu.sigma.config import SigmaConfig
from mu.sigma.frameworks import detect_frameworks
from mu.sigma.models import (
    Checkpoint,
    PipelineStats,
    ProcessingResult,
    QAPair,
    RepoInfo,
    TrainingPair,
)
from mu.sigma.pairs import combine_pairs, extract_qa_pairs, extract_structural_pairs
from mu.sigma.questions import generate_questions
from mu.sigma.validate import filter_valid_pairs, validate_answers_batch

logger = logging.getLogger(__name__)


class SigmaPipeline:
    """Orchestrates the MU-SIGMA training data pipeline."""

    def __init__(self, config: SigmaConfig):
        self.config = config
        self.stats = PipelineStats()
        self.results: list[ProcessingResult] = []
        self.all_training_pairs: list[TrainingPair] = []

    async def run(
        self,
        repos: list[RepoInfo],
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> PipelineStats:
        """Run full pipeline on repos.

        Args:
            repos: List of repositories to process
            progress_callback: Optional callback(status, completed, total)

        Returns:
            Pipeline statistics
        """
        self.config.ensure_directories()

        # Check for existing checkpoint
        checkpoint = Checkpoint.load(self.config.paths.checkpoint_file)
        if checkpoint:
            logger.info(f"Resuming from checkpoint: {len(checkpoint.processed_repos)} repos done")
            self.stats = checkpoint.stats
            self.results = checkpoint.results
            self.all_training_pairs = checkpoint.all_training_pairs
            processed_set = set(checkpoint.processed_repos)
            repos = [r for r in repos if r.name not in processed_set]

        self.stats.total_repos = len(repos) + len(self.results)

        for i, repo in enumerate(repos):
            if progress_callback:
                progress_callback(
                    f"Processing {repo.name}",
                    len(self.results),
                    self.stats.total_repos,
                )

            result = await self.process_repo(repo)
            self.results.append(result)
            self.stats.add_result(result)

            # Save checkpoint periodically
            if (i + 1) % self.config.pipeline.checkpoint_interval == 0:
                self._save_checkpoint()

            if result.success:
                logger.info(
                    f"Processed {repo.name}: "
                    f"success={result.success}, "
                    f"pairs={result.total_training_pairs}"
                )
            else:
                logger.warning(
                    f"Processed {repo.name}: success={result.success}, error={result.error}"
                )

        # Final checkpoint
        self._save_checkpoint()

        # Export training data
        if self.all_training_pairs:
            self._export_training_pairs()

        return self.stats

    async def process_repo(self, repo: RepoInfo) -> ProcessingResult:
        """Process a single repository.

        Steps:
        1. Clone repo
        2. Build .mubase
        3. Generate questions
        4. Generate answers
        5. Validate answers
        6. Extract training pairs
        7. Cleanup

        Args:
            repo: Repository to process

        Returns:
            ProcessingResult with statistics
        """
        start_time = time.time()
        result = ProcessingResult(repo_name=repo.name, success=False)

        try:
            # Step 1: Clone repo
            logger.info(f"Cloning {repo.name}...")
            clone_result = clone_repo(repo, self.config.paths.clones_dir)

            if not clone_result.success or not clone_result.local_path:
                result.error = f"Clone failed: {clone_result.error}"
                result.duration_seconds = time.time() - start_time
                return result

            try:
                # Step 2: Build mubase
                logger.info(f"Building mubase for {repo.name}...")
                build_result = build_mubase(
                    repo_path=clone_result.local_path,
                    output_dir=self.config.paths.mubases_dir,
                    repo_name=repo.name,
                    config=self.config,
                )

                if not build_result.success or not build_result.mubase_path:
                    result.error = f"Build failed: {build_result.error}"
                    result.duration_seconds = time.time() - start_time
                    return result

                result.mubase_path = build_result.mubase_path
                result.node_count = build_result.node_count
                result.edge_count = build_result.edge_count

                # Step 3: Generate questions
                logger.info(f"Generating questions for {repo.name}...")
                questions = await generate_questions(
                    mubase_path=build_result.mubase_path,
                    repo_name=repo.name,
                    language=repo.language,
                    config=self.config,
                )
                result.questions_generated = len(questions)

                if not questions:
                    result.error = "No questions generated"
                    result.success = True  # Still count as partial success
                    result.duration_seconds = time.time() - start_time
                    return result

                # Step 4: Generate answers
                logger.info(f"Generating answers for {repo.name}...")
                qa_pairs = await generate_answers_batch(
                    qa_pairs=questions,
                    mubase_path=build_result.mubase_path,
                    config=self.config,
                )
                result.answers_generated = len([qa for qa in qa_pairs if qa.answer])

                # Step 5: Validate answers
                logger.info(f"Validating answers for {repo.name}...")
                validated_pairs = await validate_answers_batch(
                    qa_pairs=qa_pairs,
                    mubase_path=build_result.mubase_path,
                    config=self.config,
                )
                result.qa_pairs_validated = len(validated_pairs)

                valid_pairs = filter_valid_pairs(validated_pairs)
                result.qa_pairs_accepted = len(valid_pairs)

                # Save Q&A pairs
                self._save_qa_pairs(repo.name, validated_pairs)

                # Step 6: Extract training pairs
                logger.info(f"Extracting training pairs for {repo.name}...")

                # Detect frameworks once for this repo
                frameworks = detect_frameworks(build_result.mubase_path)
                if frameworks:
                    logger.info(f"Detected frameworks for {repo.name}: {frameworks}")

                # Structural pairs from graph
                structural_pairs = extract_structural_pairs(
                    mubase_path=build_result.mubase_path,
                    repo_name=repo.name,
                    frameworks=frameworks,
                )
                result.structural_pairs = len(structural_pairs)

                # Q&A pairs
                all_node_names = list(get_all_node_names(build_result.mubase_path))
                qa_training_pairs = extract_qa_pairs(
                    qa_pairs=valid_pairs,
                    repo_name=repo.name,
                    all_node_names=all_node_names,
                    frameworks=frameworks,
                )
                result.qa_training_pairs = len(qa_training_pairs)

                # Combine pairs
                combined_pairs = combine_pairs(structural_pairs, qa_training_pairs)
                self.all_training_pairs.extend(combined_pairs)

                result.success = True

            finally:
                # Cleanup clone
                if self.config.pipeline.cleanup_clones:
                    cleanup_clone(clone_result)

        except Exception as e:
            logger.exception(f"Error processing {repo.name}")
            result.error = str(e)

        result.duration_seconds = time.time() - start_time
        return result

    def _save_checkpoint(self) -> None:
        """Save current progress to checkpoint file."""
        checkpoint = Checkpoint(
            processed_repos=[r.repo_name for r in self.results],
            results=self.results,
            all_training_pairs=self.all_training_pairs,
            stats=self.stats,
        )
        checkpoint.save(self.config.paths.checkpoint_file)
        logger.info(f"Saved checkpoint: {len(self.results)} repos processed")

    def _save_qa_pairs(self, repo_name: str, qa_pairs: list[QAPair]) -> None:
        """Save Q&A pairs for a repo."""
        safe_name = repo_name.replace("/", "__")
        output_path = self.config.paths.qa_pairs_dir / f"{safe_name}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([qa.to_dict() for qa in qa_pairs], f, indent=2)

    def _export_training_pairs(self) -> None:
        """Export all training pairs to parquet."""
        try:
            import pandas as pd
            import pyarrow as pa
            import pyarrow.parquet as pq

            # Convert to dataframe
            data = [
                {
                    "anchor": p.anchor,
                    "positive": p.positive,
                    "negative": p.negative,
                    "pair_type": p.pair_type.value,
                    "weight": p.weight,
                    "source_repo": p.source_repo,
                    "frameworks": p.frameworks,
                }
                for p in self.all_training_pairs
            ]

            df = pd.DataFrame(data)

            # Save as parquet
            output_path = self.config.paths.training_dir / "training_pairs.parquet"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            table = pa.Table.from_pandas(df)
            pq.write_table(table, output_path)

            logger.info(f"Exported {len(self.all_training_pairs)} training pairs to {output_path}")

        except ImportError:
            # Fallback to JSON if pandas/pyarrow not available
            output_path = self.config.paths.training_dir / "training_pairs.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(
                    [p.to_dict() for p in self.all_training_pairs],
                    f,
                )
            logger.info(
                f"Exported {len(self.all_training_pairs)} pairs to JSON (parquet deps missing)"
            )


async def run_pipeline(
    config: SigmaConfig,
    repos: list[RepoInfo],
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> PipelineStats:
    """Convenience function to run the pipeline.

    Args:
        config: Pipeline configuration
        repos: Repositories to process
        progress_callback: Optional progress callback

    Returns:
        Pipeline statistics
    """
    pipeline = SigmaPipeline(config)
    return await pipeline.run(repos, progress_callback)


def run_pipeline_sync(
    config: SigmaConfig,
    repos: list[RepoInfo],
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> PipelineStats:
    """Synchronous wrapper for run_pipeline.

    Args:
        config: Pipeline configuration
        repos: Repositories to process
        progress_callback: Optional progress callback

    Returns:
        Pipeline statistics
    """
    return asyncio.run(run_pipeline(config, repos, progress_callback))
