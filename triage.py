import os
import sys
import math
import json
from pathlib import Path

# CONFIGURATION
IGNORE_DIRS = {
    '.git', 'node_modules', 'venv', '.venv', 'env', '.env', 'dist', 'build',
    '__pycache__', '.next', 'target', 'vendor', '.idea', '.vscode',
    'examples', 'example', 'fixtures', 'test-fixtures', '__tests__', 'e2e', 'tests',
    # Mobile / Build Artifacts
    'Pods', 'DerivedData', '.build', 'ios', 'android', 'cmake-build-debug',
    'typings', 'coverage', 'site-packages'
}

IGNORE_EXTS = {
    # Images/Media
    '.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico', '.mp4', '.mp3', '.wav',
    # Data/Config (Non-Architectural)
    '.json', '.lock', '.map', '.txt', '.md', '.xml', '.csv', '.log', '.sql', '.sqlite',
    '.yml', '.yaml', '.toml', '.ini',
    # Binary / Compiled / Obfuscated
    '.o', '.a', '.so', '.dylib', '.exe', '.dll', '.ipa', '.apk', '.bin', '.dat',
    '.pyc', '.pyo', '.pyd', '.class', '.jar', '.war',
    # iOS / Xcode Noise
    '.xcconfig', '.xcscheme', '.pch', '.plist', '.modulemap', '.strings', '.nib', '.xib', '.storyboard',
    # C/C++ Headers (Often Vendor/Generated - Enable if analyzing C++ Core)
    '.h', '.hpp', '.hxx'
}

# Files that define a "Sub-Project" or "Module"
MODULE_MARKERS = {
    'package.json', 'go.mod', 'pom.xml', 'Cargo.toml',
    'requirements.txt', 'build.gradle', 'mix.exs', 'composer.json',
    'pyproject.toml'
}

WORKSPACE_MARKERS = {
    'pnpm-workspace.yaml', 'lerna.json', 'nx.json',
    'turbo.json', 'rush.json', 'workspace.json'
}

def is_binary_file(filepath):
    """
    Reads the first 1024 bytes to check for NULL bytes.
    This catches binaries that have weird extensions.
    """
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return True
            return False
    except:
        return True

def get_complexity_score(loc, file_count):
    """
    Heuristic complexity score (0-100+).
    Uncalibrated - serves as a relative baseline.
    """
    if loc == 0 or file_count == 0:
        return 0

    # Base score on LOC (Log scale)
    loc_score = math.log(loc, 10) * 10

    # Density Penalty (Avg lines per file)
    avg_lines = loc / file_count
    density_penalty = min(avg_lines / 50, 20)

    return round(loc_score + density_penalty, 2)

def analyze_repo(repo_path):
    repo_path = Path(repo_path).resolve()

    stats = {
        "repo_name": repo_path.name,
        "total_files": 0,
        "total_loc": 0,
        "languages": {},
        "modules": [],
        "is_monorepo": False,
        "complexity_score": 0
    }

    # 1. Check for Monorepo Root Markers
    root_files = set(f.name for f in repo_path.iterdir() if f.is_file())
    if not root_files.isdisjoint(WORKSPACE_MARKERS):
        stats["is_monorepo"] = True

    # 2. Walk tree to find Modules and count stats
    potential_modules = []

    for root, dirs, files in os.walk(repo_path):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        rel_path = Path(root).relative_to(repo_path)

        # Check for Module Markers
        has_marker = any(m in files for m in MODULE_MARKERS)

        if has_marker:
            # If it's the root, keep it. If deep, it's a sub-module candidate.
            # We store string paths for easier filtering later
            potential_modules.append(str(rel_path))

        for file in files:
            ext = Path(file).suffix.lower()
            if ext in IGNORE_EXTS or not ext:
                continue

            file_path = Path(root) / file

            # SKIP BINARIES (The expensive mistake)
            if is_binary_file(file_path):
                continue

            try:
                with open(file_path, 'r', errors='ignore') as f:
                    loc = sum(1 for line in f if line.strip())

                stats["total_loc"] += loc
                stats["total_files"] += 1

                lang = ext.lstrip('.')
                stats["languages"][lang] = stats["languages"].get(lang, 0) + loc
            except Exception:
                pass

    # 3. Smart Module Filtering (The Claude Fix)
    # Remove nested modules (e.g., keep 'packages/ui', drop 'packages/ui/sub-thing')
    if potential_modules:
        # Sort by length so we process shortest paths (parents) first
        potential_modules.sort(key=lambda p: p.count('/'))

        filtered_modules = []
        for mod in potential_modules:
            # If mod is '.' (root), always keep it unless we already have explicit submodules
            if mod == '.':
                filtered_modules.append(mod)
                continue

            # Check if this module is inside an existing filtered module
            # e.g. "packages/ui/nested" starts with "packages/ui/"
            is_nested = any(mod.startswith(parent + '/') or (parent == '.' and mod != '.') for parent in filtered_modules)

            if not is_nested:
                filtered_modules.append(mod)

        # Final formatting
        for mod in filtered_modules:
            mod_type = "Root" if mod == "." else "Sub-Package"
            stats["modules"].append({"path": mod, "type": mod_type})

        if len(stats["modules"]) > 1:
            stats["is_monorepo"] = True

    # Fallback: If absolutely no modules found, treat as Monolith
    if not stats["modules"]:
        stats["modules"].append({"path": ".", "type": "Monolith"})

    # 4. Calculate Complexity
    stats["complexity_score"] = get_complexity_score(stats["total_loc"], stats["total_files"])

    # 5. Sort Languages by LOC (Descending)
    stats["languages"] = dict(sorted(stats["languages"].items(), key=lambda item: item[1], reverse=True))

    return stats

def print_report(stats):
    print("\n" + "="*50)
    print(f"📊 GLASS BOX TRIAGE V4: {stats['repo_name']}")
    print("="*50)
    print(f"Total LOC:        {stats['total_loc']:,}")
    print(f"Total Files:      {stats['total_files']:,}")
    print(f"Complexity Score: {stats['complexity_score']} / 100")
    print(f"Architecture:     {'🗂  MONOREPO' if stats['is_monorepo'] else '📦 MONOLITH'}")

    print("\n💻 Languages:")
    for lang, count in list(stats["languages"].items())[:5]:
        print(f"  - {lang:<10}: {count:,} loc")

    print("\n🌊 Wave 0.5: Identified Chunks")
    for i, mod in enumerate(stats["modules"]):
        if i > 15:
            print(f"  ... {len(stats['modules']) - 15} more modules")
            break
        print(f"  [{i+1}] {mod['path']}")

    print("\n💰 Pipeline Estimation")
    cost = (stats['total_loc'] / 500000) * 4.25
    print(f"  - Est. Cost: ${cost:.2f}")

    if stats['complexity_score'] > 80:
        print("\n⚠️  NOTE: Repo is dense. Analysis may require higher context windows.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python triage_v3.py <path_to_repo> [--json]")
        sys.exit(1)

    repo_path = sys.argv[1]
    json_mode = "--json" in sys.argv

    data = analyze_repo(repo_path)

    if json_mode:
        print(json.dumps(data, indent=2))
    else:
        print_report(data)
