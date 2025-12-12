"""Training script for MU-SIGMA embeddings.

Fine-tunes a sentence-transformer model on code structure triplets
to create embeddings that understand code relationships.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
from sentence_transformers import InputExample, SentenceTransformer, losses
from sentence_transformers.evaluation import TripletEvaluator
from torch.utils.data import DataLoader

from mu.sigma.models import TrainingPair

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """Configuration for embedding training."""

    # Model settings
    base_model: str = "all-MiniLM-L6-v2"
    output_dir: Path = field(default_factory=lambda: Path("models/mu-sigma-v1"))

    # Training hyperparameters
    epochs: int = 3
    batch_size: int = 64
    warmup_ratio: float = 0.1
    learning_rate: float = 2e-5

    # Triplet loss settings
    triplet_margin: float = 0.5

    # Data settings
    train_ratio: float = 0.9  # 90% train, 10% eval
    max_samples: int | None = None  # Limit samples for testing

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
            "max_samples": self.max_samples,
            "num_workers": self.num_workers,
        }


@dataclass
class TrainingResult:
    """Result from training run."""

    success: bool
    model_path: Path | None = None
    train_samples: int = 0
    eval_samples: int = 0
    final_loss: float | None = None
    eval_accuracy: float | None = None
    epochs_completed: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "model_path": str(self.model_path) if self.model_path else None,
            "train_samples": self.train_samples,
            "eval_samples": self.eval_samples,
            "final_loss": self.final_loss,
            "eval_accuracy": self.eval_accuracy,
            "epochs_completed": self.epochs_completed,
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
    train_ratio: float = 0.9,
) -> tuple[list[InputExample], list[InputExample]]:
    """Split data into train and eval sets."""
    import random

    random.shuffle(examples)
    split_idx = int(len(examples) * train_ratio)
    return examples[:split_idx], examples[split_idx:]


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

        # Split data
        train_examples, eval_examples = split_data(examples, config.train_ratio)
        logger.info(f"Train: {len(train_examples)}, Eval: {len(eval_examples)}")

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

        # Create evaluator - extract texts from InputExample
        eval_anchors: list[str] = []
        eval_positives: list[str] = []
        eval_negatives: list[str] = []
        for e in eval_examples:
            if e.texts is not None and len(e.texts) >= 3:
                eval_anchors.append(e.texts[0])
                eval_positives.append(e.texts[1])
                eval_negatives.append(e.texts[2])
        evaluator = TripletEvaluator(
            anchors=eval_anchors,
            positives=eval_positives,
            negatives=eval_negatives,
            name="mu-sigma-eval",
        )

        # Calculate warmup steps
        total_steps = len(train_dataloader) * config.epochs
        warmup_steps = int(total_steps * config.warmup_ratio)

        # Create output directory
        config.output_dir.mkdir(parents=True, exist_ok=True)

        # Save config
        config_path = config.output_dir / "training_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)

        # Train
        log_progress("Starting training...", 0.3)
        model.fit(
            train_objectives=[(train_dataloader, train_loss)],
            epochs=config.epochs,
            warmup_steps=warmup_steps,
            evaluator=evaluator,
            evaluation_steps=max(1, len(train_dataloader) // 2),  # Eval twice per epoch
            output_path=str(config.output_dir),
            show_progress_bar=True,
            optimizer_params={"lr": config.learning_rate},
        )

        log_progress("Training complete!", 0.9)

        # Final evaluation
        log_progress("Running final evaluation...", 0.95)
        eval_result = evaluator(model, output_path=str(config.output_dir))

        # Extract accuracy from result (may be dict or float depending on version)
        if isinstance(eval_result, dict):
            # New sentence-transformers returns dict with metrics
            final_score = eval_result.get(
                "cosine_accuracy",
                eval_result.get("accuracy", list(eval_result.values())[0] if eval_result else 0.0),
            )
        else:
            final_score = eval_result

        logger.info(f"Final evaluation accuracy: {final_score:.4f}")

        # Save final model
        model.save(str(config.output_dir))
        log_progress(f"Model saved to {config.output_dir}", 1.0)

        return TrainingResult(
            success=True,
            model_path=config.output_dir,
            train_samples=len(train_examples),
            eval_samples=len(eval_examples),
            eval_accuracy=final_score,
            epochs_completed=config.epochs,
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
