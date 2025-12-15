"""Training script for MU-SIGMA embeddings.

Fine-tunes a sentence-transformer model on code structure triplets
to create embeddings that understand code relationships.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from sentence_transformers.evaluation import TripletEvaluator
from torch.utils.data import DataLoader

from mu.sigma.models import TrainingPair

logger = logging.getLogger(__name__)


def set_seed(seed: int = 42) -> None:
    """Set random seeds for reproducibility across all libraries."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    # Ensure deterministic behavior in cuDNN (may reduce performance)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


@dataclass
class TrainingConfig:
    """Configuration for embedding training."""

    # Model settings
    base_model: str = "all-MiniLM-L6-v2"
    output_dir: Path = field(default_factory=lambda: Path("models/mu-sigma-v1"))

    # Training hyperparameters
    epochs: int = 10  # Increased from 3; early stopping will handle overfitting
    batch_size: int = 64
    warmup_ratio: float = 0.1
    learning_rate: float = 2e-5

    # Triplet loss settings
    triplet_margin: float = 0.5

    # Data settings (80/10/10 train/eval/test split)
    train_ratio: float = 0.8  # 80% train
    eval_ratio: float = 0.1  # 10% eval (validation)
    test_ratio: float = 0.1  # 10% test (held-out, never touched during training)
    max_samples: int | None = None  # Limit samples for testing

    # Early stopping
    early_stopping_patience: int = 3  # Stop after N epochs without improvement

    # Reproducibility
    seed: int = 42

    # Performance
    # NOTE: num_workers=0 is default because multiprocessing DataLoader
    # has pickling issues on macOS with MPS backend
    num_workers: int = 0

    # Device
    device: str | None = None  # Auto-detect if None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_model": self.base_model,
            "output_dir": str(self.output_dir),
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "warmup_ratio": self.warmup_ratio,
            "learning_rate": self.learning_rate,
            "triplet_margin": self.triplet_margin,
            "train_ratio": self.train_ratio,
            "eval_ratio": self.eval_ratio,
            "test_ratio": self.test_ratio,
            "max_samples": self.max_samples,
            "early_stopping_patience": self.early_stopping_patience,
            "seed": self.seed,
            "num_workers": self.num_workers,
        }


@dataclass
class TrainingResult:
    """Result from training run."""

    success: bool
    model_path: Path | None = None
    train_samples: int = 0
    eval_samples: int = 0
    test_samples: int = 0
    final_loss: float | None = None
    eval_accuracy: float | None = None
    test_accuracy: float | None = None  # Held-out test set accuracy
    epochs_completed: int = 0
    early_stopped: bool = False  # Whether training stopped early
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "model_path": str(self.model_path) if self.model_path else None,
            "train_samples": self.train_samples,
            "eval_samples": self.eval_samples,
            "test_samples": self.test_samples,
            "final_loss": self.final_loss,
            "eval_accuracy": self.eval_accuracy,
            "test_accuracy": self.test_accuracy,
            "epochs_completed": self.epochs_completed,
            "early_stopped": self.early_stopped,
            "error": self.error,
        }


def load_training_pairs(path: Path) -> list[TrainingPair]:
    """Load training pairs from JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [TrainingPair.from_dict(d) for d in data]


def pairs_to_triplets(
    pairs: list[TrainingPair],
    use_weights: bool = True,
) -> list[InputExample]:
    """Convert training pairs to sentence-transformers InputExample triplets.

    If use_weights is True, higher-weight pairs are duplicated to increase
    their representation in training.
    """
    examples = []

    for pair in pairs:
        # Create base example
        example = InputExample(
            texts=[pair.anchor, pair.positive, pair.negative],
        )

        if use_weights and pair.weight > 0.7:
            # Duplicate high-weight examples
            # weight 1.0 -> 2 copies, 0.9 -> 1.5 copies (rounded)
            copies = max(1, round(pair.weight * 2))
            for _ in range(copies):
                examples.append(example)
        else:
            examples.append(example)

    return examples


def split_data(
    examples: list[InputExample],
    train_ratio: float = 0.8,
    eval_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> tuple[list[InputExample], list[InputExample], list[InputExample]]:
    """Split data into train, eval, and test sets.

    Args:
        examples: List of training examples
        train_ratio: Fraction for training (default 0.8)
        eval_ratio: Fraction for validation during training (default 0.1)
        test_ratio: Fraction for held-out test (default 0.1)

    Returns:
        Tuple of (train_examples, eval_examples, test_examples)
    """
    # Validate ratios
    total = train_ratio + eval_ratio + test_ratio
    if abs(total - 1.0) > 0.01:
        logger.warning(f"Split ratios sum to {total}, normalizing")
        train_ratio /= total
        eval_ratio /= total
        test_ratio /= total

    # Shuffle data (seed should already be set)
    shuffled = examples.copy()
    random.shuffle(shuffled)

    # Calculate split indices
    n = len(shuffled)
    train_end = int(n * train_ratio)
    eval_end = train_end + int(n * eval_ratio)

    return shuffled[:train_end], shuffled[train_end:eval_end], shuffled[eval_end:]


def _create_triplet_evaluator(
    examples: list[InputExample],
    name: str,
) -> TripletEvaluator:
    """Create a TripletEvaluator from InputExample list."""
    anchors: list[str] = []
    positives: list[str] = []
    negatives: list[str] = []
    for e in examples:
        if e.texts is not None and len(e.texts) >= 3:
            anchors.append(e.texts[0])
            positives.append(e.texts[1])
            negatives.append(e.texts[2])
    return TripletEvaluator(
        anchors=anchors,
        positives=positives,
        negatives=negatives,
        name=name,
    )


def _extract_eval_score(eval_result: dict[str, float] | float) -> float:
    """Extract accuracy score from evaluator result."""
    if isinstance(eval_result, dict):
        return eval_result.get(
            "cosine_accuracy",
            eval_result.get("accuracy", list(eval_result.values())[0] if eval_result else 0.0),
        )
    return float(eval_result)


def train_embeddings(
    training_pairs_path: Path,
    config: TrainingConfig | None = None,
    progress_callback: Callable[[str, float], None] | None = None,
) -> TrainingResult:
    """Train embedding model on triplet data.

    Args:
        training_pairs_path: Path to training_pairs.json
        config: Training configuration (uses defaults if None)
        progress_callback: Optional callback(status: str, progress: float)

    Returns:
        TrainingResult with model path and metrics
    """
    config = config or TrainingConfig()

    def log_progress(status: str, progress: float = 0.0) -> None:
        logger.info(status)
        if progress_callback:
            progress_callback(status, progress)

    try:
        # Set random seed for reproducibility
        set_seed(config.seed)
        logger.info(f"Random seed set to {config.seed}")

        # Load data
        log_progress("Loading training pairs...", 0.0)
        pairs = load_training_pairs(training_pairs_path)
        logger.info(f"Loaded {len(pairs)} training pairs")

        if config.max_samples:
            pairs = pairs[: config.max_samples]
            logger.info(f"Limited to {len(pairs)} samples")

        # Convert to triplets
        log_progress("Converting to triplet format...", 0.1)
        examples = pairs_to_triplets(pairs, use_weights=True)
        logger.info(f"Created {len(examples)} training examples (with weight duplication)")

        # Split data into train/eval/test (80/10/10)
        train_examples, eval_examples, test_examples = split_data(
            examples,
            train_ratio=config.train_ratio,
            eval_ratio=config.eval_ratio,
            test_ratio=config.test_ratio,
        )
        logger.info(
            f"Split: Train={len(train_examples)}, Eval={len(eval_examples)}, "
            f"Test={len(test_examples)} (held-out)"
        )

        # Save test set separately (never touched during training)
        test_set_path = config.output_dir / "test_set.json"
        config.output_dir.mkdir(parents=True, exist_ok=True)
        with open(test_set_path, "w", encoding="utf-8") as f:
            test_data = [
                {"anchor": e.texts[0], "positive": e.texts[1], "negative": e.texts[2]}
                for e in test_examples
                if e.texts and len(e.texts) >= 3
            ]
            json.dump(test_data, f)
        logger.info(f"Test set saved to {test_set_path}")

        # Load base model
        log_progress(f"Loading base model: {config.base_model}...", 0.2)
        device = config.device
        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        logger.info(f"Using device: {device}")

        model = SentenceTransformer(config.base_model, device=device)

        # Create data loader
        train_dataloader: DataLoader[InputExample] = DataLoader(
            train_examples,  # type: ignore[arg-type]
            shuffle=True,
            batch_size=config.batch_size,
            num_workers=config.num_workers,
            persistent_workers=config.num_workers > 0,
        )

        # Create loss function
        train_loss = losses.TripletLoss(
            model=model,
            distance_metric=losses.TripletDistanceMetric.COSINE,
            triplet_margin=config.triplet_margin,
        )

        # Create evaluator for validation set
        evaluator = _create_triplet_evaluator(eval_examples, "mu-sigma-eval")

        # Save config
        config_path = config.output_dir / "training_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)

        # Early stopping state
        best_score = -1.0
        patience_counter = 0
        best_model_path = config.output_dir / "best_model"
        best_model_path.mkdir(parents=True, exist_ok=True)
        epochs_completed = 0
        early_stopped = False

        # Calculate warmup steps for single epoch
        steps_per_epoch = len(train_dataloader)
        warmup_steps = int(steps_per_epoch * config.warmup_ratio)

        log_progress("Starting training with early stopping...", 0.3)

        # Train epoch by epoch with early stopping
        for epoch in range(config.epochs):
            logger.info(f"=== Epoch {epoch + 1}/{config.epochs} ===")

            # Train for one epoch
            model.fit(
                train_objectives=[(train_dataloader, train_loss)],
                epochs=1,
                warmup_steps=warmup_steps if epoch == 0 else 0,
                evaluator=None,  # We'll evaluate manually
                output_path=str(config.output_dir),
                show_progress_bar=True,
                optimizer_params={"lr": config.learning_rate},
            )

            epochs_completed = epoch + 1

            # Evaluate on validation set
            eval_result = evaluator(model, output_path=str(config.output_dir))
            current_score = _extract_eval_score(eval_result)
            logger.info(f"Epoch {epoch + 1} validation accuracy: {current_score:.4f}")

            # Early stopping check
            if current_score > best_score:
                best_score = current_score
                patience_counter = 0
                # Save best model
                model.save(str(best_model_path))
                logger.info(f"New best model saved (accuracy: {best_score:.4f})")
            else:
                patience_counter += 1
                logger.info(
                    f"No improvement. Patience: {patience_counter}/{config.early_stopping_patience}"
                )
                if patience_counter >= config.early_stopping_patience:
                    logger.info(
                        f"Early stopping triggered after {epochs_completed} epochs "
                        f"(best accuracy: {best_score:.4f})"
                    )
                    early_stopped = True
                    break

            # Progress update
            progress = 0.3 + (0.6 * (epoch + 1) / config.epochs)
            log_progress(f"Completed epoch {epoch + 1}/{config.epochs}", progress)

        # Load best model for final evaluation
        logger.info("Loading best model for final evaluation...")
        model = SentenceTransformer(str(best_model_path), device=device)

        log_progress("Training complete!", 0.9)

        # Final evaluation on validation set
        log_progress("Running final evaluation on validation set...", 0.93)
        final_eval_result = evaluator(model, output_path=str(config.output_dir))
        final_eval_score = _extract_eval_score(final_eval_result)
        logger.info(f"Final validation accuracy: {final_eval_score:.4f}")

        # Evaluate on held-out TEST set (never seen during training)
        log_progress("Running evaluation on held-out test set...", 0.96)
        test_evaluator = _create_triplet_evaluator(test_examples, "mu-sigma-test")
        test_result = test_evaluator(model, output_path=str(config.output_dir))
        test_score = _extract_eval_score(test_result)
        logger.info(f"Held-out TEST set accuracy: {test_score:.4f}")

        # Save final model
        model.save(str(config.output_dir))
        log_progress(f"Model saved to {config.output_dir}", 1.0)

        return TrainingResult(
            success=True,
            model_path=config.output_dir,
            train_samples=len(train_examples),
            eval_samples=len(eval_examples),
            test_samples=len(test_examples),
            eval_accuracy=final_eval_score,
            test_accuracy=test_score,
            epochs_completed=epochs_completed,
            early_stopped=early_stopped,
        )

    except Exception as e:
        logger.exception("Training failed")
        return TrainingResult(
            success=False,
            error=str(e),
        )


def load_trained_model(model_path: Path) -> SentenceTransformer:
    """Load a trained MU-SIGMA model."""
    return SentenceTransformer(str(model_path))


def evaluate_model(
    model: SentenceTransformer,
    test_pairs: list[TrainingPair],
) -> dict[str, float]:
    """Evaluate model on test pairs.

    Returns accuracy metrics broken down by pair type.
    """
    results: dict[str, dict[str, int]] = {}

    for pair in test_pairs:
        pair_type = pair.pair_type.value

        if pair_type not in results:
            results[pair_type] = {"correct": 0, "total": 0}

        # Encode triplet
        embeddings = model.encode(
            [pair.anchor, pair.positive, pair.negative],
            convert_to_tensor=True,
        )

        # Check if positive is closer than negative
        anchor_emb = embeddings[0]
        pos_emb = embeddings[1]
        neg_emb = embeddings[2]

        pos_dist = 1 - torch.nn.functional.cosine_similarity(
            anchor_emb.unsqueeze(0), pos_emb.unsqueeze(0)
        ).item()
        neg_dist = 1 - torch.nn.functional.cosine_similarity(
            anchor_emb.unsqueeze(0), neg_emb.unsqueeze(0)
        ).item()

        results[pair_type]["total"] += 1
        if pos_dist < neg_dist:
            results[pair_type]["correct"] += 1

    # Calculate accuracies
    accuracies = {}
    total_correct = 0
    total_samples = 0

    for pair_type, counts in results.items():
        if counts["total"] > 0:
            acc = counts["correct"] / counts["total"]
            accuracies[pair_type] = acc
            total_correct += counts["correct"]
            total_samples += counts["total"]

    if total_samples > 0:
        accuracies["overall"] = total_correct / total_samples

    return accuracies
