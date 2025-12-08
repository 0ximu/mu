"""Centralized path definitions for MU data files.

All MU-related files are stored in the .mu/ directory:

    .mu/
    ├── mubase          # Graph database (DuckDB)
    ├── mubase.wal      # DuckDB write-ahead log
    ├── cache/          # File and LLM response cache
    ├── contracts.yml   # Architecture contracts
    └── daemon.pid      # Daemon process ID file

The configuration file (.murc.toml) remains at project root
since it's user-editable configuration.
"""

from __future__ import annotations

from pathlib import Path

# Directory containing all MU data files
MU_DIR = ".mu"

# Individual file/directory names within .mu/
MUBASE_FILE = "mubase"
CACHE_DIR = "cache"
CONTRACTS_FILE = "contracts.yml"
DAEMON_PID_FILE = "daemon.pid"

# Config file stays at project root (user-editable)
CONFIG_FILE = ".murc.toml"


def get_mu_dir(root: Path | str = ".") -> Path:
    """Get the .mu directory path for a project root.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the .mu directory
    """
    return Path(root).resolve() / MU_DIR


def get_mubase_path(root: Path | str = ".") -> Path:
    """Get the mubase database path.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the mubase file (.mu/mubase)
    """
    return get_mu_dir(root) / MUBASE_FILE


def get_cache_dir(root: Path | str = ".") -> Path:
    """Get the cache directory path.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the cache directory (.mu/cache/)
    """
    return get_mu_dir(root) / CACHE_DIR


def get_contracts_path(root: Path | str = ".") -> Path:
    """Get the contracts file path.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the contracts file (.mu/contracts.yml)
    """
    return get_mu_dir(root) / CONTRACTS_FILE


def get_daemon_pid_path(root: Path | str = ".") -> Path:
    """Get the daemon PID file path.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the daemon PID file (.mu/daemon.pid)
    """
    return get_mu_dir(root) / DAEMON_PID_FILE


def get_config_path(root: Path | str = ".") -> Path:
    """Get the configuration file path.

    Note: Config file stays at project root for easy editing.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the config file (.murc.toml)
    """
    return Path(root).resolve() / CONFIG_FILE


def ensure_mu_dir(root: Path | str = ".") -> Path:
    """Ensure the .mu directory exists.

    Creates the directory if it doesn't exist.

    Args:
        root: Project root directory (default: current directory)

    Returns:
        Path to the .mu directory
    """
    mu_dir = get_mu_dir(root)
    mu_dir.mkdir(parents=True, exist_ok=True)
    return mu_dir


def find_mu_dir(start: Path | str = ".") -> Path | None:
    """Find the nearest .mu directory walking up from start.

    Useful for commands run from subdirectories.

    Args:
        start: Starting directory (default: current directory)

    Returns:
        Path to the nearest .mu directory, or None if not found
    """
    current = Path(start).resolve()

    while current != current.parent:
        mu_dir = current / MU_DIR
        if mu_dir.exists() and mu_dir.is_dir():
            return mu_dir
        current = current.parent

    # Check root directory
    mu_dir = current / MU_DIR
    if mu_dir.exists() and mu_dir.is_dir():
        return mu_dir

    return None


def find_mubase_path(start: Path | str = ".") -> Path | None:
    """Find the nearest mubase file walking up from start.

    Args:
        start: Starting directory (default: current directory)

    Returns:
        Path to the nearest mubase file, or None if not found
    """
    mu_dir = find_mu_dir(start)
    if mu_dir:
        mubase = mu_dir / MUBASE_FILE
        if mubase.exists():
            return mubase
    return None


# Legacy path names for backward compatibility detection
LEGACY_MUBASE = ".mubase"
LEGACY_CACHE_DIR = ".mu-cache"
LEGACY_CONTRACTS = ".mu-contracts.yml"
LEGACY_PID_FILE = ".mu.pid"


def has_legacy_files(root: Path | str = ".") -> dict[str, Path]:
    """Check for legacy MU files that need migration.

    Args:
        root: Project root directory

    Returns:
        Dictionary of legacy file types to their paths (only existing files)
    """
    root_path = Path(root).resolve()
    legacy: dict[str, Path] = {}

    legacy_mubase = root_path / LEGACY_MUBASE
    if legacy_mubase.exists():
        legacy["mubase"] = legacy_mubase

    legacy_cache = root_path / LEGACY_CACHE_DIR
    if legacy_cache.exists():
        legacy["cache"] = legacy_cache

    legacy_contracts = root_path / LEGACY_CONTRACTS
    if legacy_contracts.exists():
        legacy["contracts"] = legacy_contracts

    legacy_pid = root_path / LEGACY_PID_FILE
    if legacy_pid.exists():
        legacy["pid"] = legacy_pid

    return legacy


def migrate_legacy_files(root: Path | str = ".", dry_run: bool = False) -> list[tuple[Path, Path]]:
    """Migrate legacy MU files to the new .mu/ directory structure.

    Args:
        root: Project root directory
        dry_run: If True, only report what would be migrated

    Returns:
        List of (source, destination) tuples for migrated files
    """
    import shutil

    root_path = Path(root).resolve()
    legacy = has_legacy_files(root_path)

    if not legacy:
        return []

    migrations: list[tuple[Path, Path]] = []
    mu_dir = get_mu_dir(root_path)

    if not dry_run:
        mu_dir.mkdir(parents=True, exist_ok=True)

    if "mubase" in legacy:
        src = legacy["mubase"]
        dst = mu_dir / MUBASE_FILE
        migrations.append((src, dst))
        if not dry_run:
            shutil.move(str(src), str(dst))
            # Also move WAL file if present
            wal_src = root_path / f"{LEGACY_MUBASE}.wal"
            if wal_src.exists():
                wal_dst = mu_dir / f"{MUBASE_FILE}.wal"
                shutil.move(str(wal_src), str(wal_dst))

    if "cache" in legacy:
        src = legacy["cache"]
        dst = mu_dir / CACHE_DIR
        migrations.append((src, dst))
        if not dry_run:
            shutil.move(str(src), str(dst))

    if "contracts" in legacy:
        src = legacy["contracts"]
        dst = mu_dir / CONTRACTS_FILE
        migrations.append((src, dst))
        if not dry_run:
            shutil.move(str(src), str(dst))

    if "pid" in legacy:
        src = legacy["pid"]
        dst = mu_dir / DAEMON_PID_FILE
        migrations.append((src, dst))
        if not dry_run:
            shutil.move(str(src), str(dst))

    return migrations


__all__ = [
    # Constants
    "MU_DIR",
    "MUBASE_FILE",
    "CACHE_DIR",
    "CONTRACTS_FILE",
    "DAEMON_PID_FILE",
    "CONFIG_FILE",
    # Path getters
    "get_mu_dir",
    "get_mubase_path",
    "get_cache_dir",
    "get_contracts_path",
    "get_daemon_pid_path",
    "get_config_path",
    # Helpers
    "ensure_mu_dir",
    "find_mu_dir",
    "find_mubase_path",
    # Migration
    "has_legacy_files",
    "migrate_legacy_files",
    # Legacy constants
    "LEGACY_MUBASE",
    "LEGACY_CACHE_DIR",
    "LEGACY_CONTRACTS",
    "LEGACY_PID_FILE",
]
