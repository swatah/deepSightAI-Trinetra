#!/usr/bin/env python3
"""
Rename project from ClipSight to deepSightAI Trinetra.
Performs find-replace across all text files and renames directories/files.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

OLD_NAME = "ClipSight"
OLD_NAME_LOWER = "clipsight"
NEW_NAME = "deepSightAI Trinetra"
NEW_NAME_LOWER = "trinetra"  # Use short form for technical IDs

# ============================================================================
# REPLACEMENT RULES
# ============================================================================

# Each tuple: (pattern, replacement)
# Patterns are regex, use raw strings
REPLACEMENTS = [
    # === Display/Brand Names ===
    # Case-sensitive exact: "ClipSight" → "deepSightAI Trinetra"
    (r'\bClipSight\b', NEW_NAME),
    # Case-insensitive whole word: "clipsight" → "trinetra"
    # Note: using (?i) flag globally in processing

    # === URLs (must be first before generic clipsight→trinetra) ===
    (r'https?://api\.clipsight\.com', 'https://api.trinetra.com'),
    (r'https?://auth\.clipsight\.com', 'https://auth.trinetra.com'),
    (r'https?://app\.clipsight\.com', 'https://app.trinetra.com'),
    (r'https?://staging-api\.clipsight\.com', 'https://staging-api.trinetra.com'),
    (r'https?://github\.com/yourorg/clipsight', 'https://github.com/yourorg/deepSightAI-Trinetra'),
    (r'https?://hub\.docker\.com/u/clipsight', 'https://hub.docker.com/u/trinetra'),

    # === Docker Images ===
    (r'image:\s*clipsight/', 'image: trinetra/'),
    (r'clipsight/registry', 'trinetra/registry'),
    (r'clipsight/main-api', 'trinetra/main-api'),
    (r'clipsight/extractor', 'trinetra/extractor'),
    (r'clipsight/embedder', 'trinetra/embedder'),
    (r'clipsight/search-api', 'trinetra/search-api'),
    # Docker build -t tags
    (r'-t\s+clipsight/','-t trinetra/'),
    (r'docker build -t clipsight/', 'docker build -t trinetra/'),

    # === Database Names ===
    (r'\bclipsight_test\b', f'{NEW_NAME_LOWER}_test'),
    (r'\bclipsight\b(?!\w)', NEW_NAME_LOWER),  # clipsight as standalone word

    # === Redis / Kafka / MinIO prefixes ===
    (r'clipsight:', f'{NEW_NAME_LOWER}:'),
    (r'clipsight_', f'{NEW_NAME_LOWER}_'),
    (r'clipsight-', f'{NEW_NAME_LOWER}-'),

    # === Kubernetes / ArgoCD ===
    (r'clipsight-staging', f'{NEW_NAME_LOWER}-staging'),
    (r'clipsight-production', f'{NEW_NAME_LOWER}-production'),
    # Labels
    (r'(app\.kubernetes\.io/part-of:\s*)clipsight', rf'\1{NEW_NAME_LOWER}'),
    (r'(app\.kubernetes\.io/name:\s*)clipsight', rf'\1{NEW_NAME_LOWER}'),
    (r'(app\.kubernetes\.io/instance:\s*)clipsight', rf'\1{NEW_NAME_LOWER}'),
    # Namespace references
    (r'namespace:\s*clipsight-staging', f'namespace: {NEW_NAME_LOWER}-staging'),
    (r'namespace:\s*clipsight-production', f'namespace: {NEW_NAME_LOWER}-production'),
    (r'namespace:\s*clipsight(\b|-)', f'namespace: {NEW_NAME_LOWER}\\1'),

    # === Helm Charts ===
    (r'name:\s*clipsight', f'name: {NEW_NAME_LOWER}'),
    (r'app\.kubernetes\.io/part-of: clipsight', f'app.kubernetes.io/part-of: {NEW_NAME_LOWER}'),

    # === mkdocs.yml ===
    (r'site_name:\s*ClipSight Enterprise', f'site_name: {NEW_NAME} Enterprise'),
    (r'site_author:\s*ClipSight Team', f'site_author: {NEW_NAME} Team'),
    (r'repo_url:\s*https://github\.com/yourorg/clipsight', f'repo_url: https://github.com/yourorg/deepSightAI-Trinetra'),
    (r'repo_name:\s*yourorg/clipsight', 'repo_name: yourorg/deepSightAI-Trinetra'),
    (r'link:\s*https://github\.com/yourorg/clipsight', 'link: https://github.com/yourorg/deepSightAI-Trinetra'),
    (r'link:\s*https://hub\.docker\.com/u/clipsight', 'link: https://hub.docker.com/u/trinetra'),

    # === Documentation generic (fallback) ===
    (r'\bclipsight\b', NEW_NAME_LOWER),
]

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_binary_file(path: Path) -> bool:
    """Check if file is binary and should be skipped."""
    binary_extensions = {
        '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp',
        '.ttf', '.woff', '.woff2', '.eot', '.otf',
        '.pdf', '.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz',
        '.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.bin',
        '.mp4', '.mov', '.avi', '.mkv', '.wav', '.mp3', '.flac',
        '.sqlite', '.db', '.sqlite3',
    }
    if path.suffix in binary_extensions:
        return True
    try:
        with open(path, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return True
    except:
        pass
    return False

def should_process_file(path: Path) -> bool:
    """Determine if file should be processed."""
    if not path.is_file():
        return False

    # Skip .git
    if '.git' in path.parts:
        return False

    # Skip common non-text directories
    skip_dirs = {
        'node_modules', 'venv', '__pycache__', '.pytest_cache',
        'site-packages', 'dist', 'build', '.tox', '.coverage',
        '.idea', '.vscode', '.eggs', '*.egg-info',
    }
    for part in path.parts:
        if part.startswith('.') and part != '.':
            return False
        if part in skip_dirs:
            return False

    # Skip binary files
    if is_binary_file(path):
        return False

    # Only process known text file extensions
    text_extensions = {
        '.py', '.md', '.yml', '.yaml', '.txt', '.sh', '.bash',
        '.toml', '.json', '.ini', '.cfg', '.conf',
        'Dockerfile', '.dockerfile',
        '.env', '.env.example',
        '.gitignore', '.gitattributes',
        '.htaccess', '.htpasswd',
        '.js', '.jsx', '.ts', '.tsx',
        '.css', '.scss', '.less',
        '.html', '.htm',
        '.xml',
        '.sql',
    }
    if path.name.startswith('Dockerfile'):
        return True
    return path.suffix in text_extensions

def apply_replacements(content: str) -> str:
    """Apply all replacement rules to content."""
    for pattern, replacement in REPLACEMENTS:
        flags = re.MULTILINE | re.IGNORECASE
        content = re.sub(pattern, replacement, content, flags=flags)
    return content

def process_file(path: Path, dry_run: bool = False) -> bool:
    """Apply replacements to a single file. Returns True if modified."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(path, 'r', encoding='latin-1') as f:
                content = f.read()
        except:
            print(f"⚠ Skipping (unreadable): {path}")
            return False
    except Exception as e:
        print(f"⚠ Skipping {path}: {e}")
        return False

    original = content
    content = apply_replacements(content)

    if content != original:
        if dry_run:
            print(f"Would modify: {path}")
        else:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"✓ Modified: {path}")
            except Exception as e:
                print(f"✗ Error writing {path}: {e}")
                return False
        return True
    return False

def rename_path_component(name: str) -> str:
    """Rename a directory or filename if it contains old names."""
    new_name = name
    # Apply specific renames to the name only
    new_name = re.sub(r'clipsight', NEW_NAME_LOWER, new_name, flags=re.IGNORECASE)
    new_name = re.sub(r'ClipSight', NEW_NAME, new_name)
    # Additional patterns for filenames
    new_name = re.sub(r'clipsight-staging', f'{NEW_NAME_LOWER}-staging', new_name, flags=re.IGNORECASE)
    new_name = re.sub(r'clipsight-production', f'{NEW_NAME_LOWER}-production', new_name, flags=re.IGNORECASE)
    return new_name

def rename_files_and_dirs(root: Path, dry_run: bool = False) -> int:
    """Rename files and directories. Returns count of renames."""
    rename_count = 0

    # First, collect all paths (deepest first for directories)
    all_paths = list(root.rglob('*'))
    # Sort by depth (deepest first) to avoid renaming parent before child
    all_paths.sort(key=lambda p: len(p.parts), reverse=True)

    # Rename files first (leaf nodes)
    for path in all_paths:
        if path.is_file():
            new_name = rename_path_component(path.name)
            if new_name != path.name:
                new_path = path.parent / new_name
                if new_path.exists():
                    print(f"⚠ Target exists, skipping: {path} → {new_path}")
                    continue
                if dry_run:
                    print(f"Would rename file: {path} → {new_path}")
                else:
                    try:
                        path.rename(new_path)
                        print(f"✓ Renamed file: {path} → {new_path}")
                        rename_count += 1
                    except Exception as e:
                        print(f"✗ Error renaming {path}: {e}")

    # Then rename directories (we already sorted deepest first)
    dirs_to_rename = [p for p in all_paths if p.is_dir()]
    for path in dirs_to_rename:
        new_name = rename_path_component(path.name)
        if new_name != path.name:
            new_path = path.parent / new_name
            if new_path.exists():
                print(f"⚠ Target exists, skipping: {path} → {new_path}")
                continue
            if dry_run:
                print(f"Would rename dir: {path} → {new_path}")
            else:
                try:
                    path.rename(new_path)
                    print(f"✓ Renamed dir: {path} → {new_path}")
                    rename_count += 1
                except Exception as e:
                    print(f"✗ Error renaming {path}: {e}")

    return rename_count

def create_backup_branch(root: Path):
    """Create a git backup branch before renaming."""
    try:
        subprocess.run(['git', 'checkout', '-b', 'rename-backup'], cwd=root, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        subprocess.run(['git', 'commit', '-m', 'Backup before renaming project'], cwd=root, check=True)
        print("✓ Created backup branch 'rename-backup'")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create backup: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Rename project from ClipSight to deepSightAI Trinetra')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without making changes')
    parser.add_argument('--root', default='.', type=Path, help='Root directory (default: current directory)')
    parser.add_argument('--no-backup', action='store_true', help='Skip creating git backup branch')
    args = parser.parse_args()

    root = args.root.resolve()
    print("=" * 70)
    print("PROJECT RENAME: ClipSight → deepSightAI Trinetra")
    print("=" * 70)
    print(f"Root: {root}")
    print(f"Dry run: {args.dry_run}")
    print(f"Skip backup: {args.no_backup}")
    print()

    if not args.dry_run and not args.no_backup:
        confirm = input("Create git backup branch? (y/N): ")
        if confirm.lower() == 'y':
            if not create_backup_branch(root):
                print("⚠ Proceeding without backup...")
        else:
            print("No backup created.")
        print()

    # Step 1: Rename files and directories
    print("=" * 70)
    print("STEP 1: Renaming files and directories")
    print("=" * 70)
    rename_count = rename_files_and_dirs(root, args.dry_run)
    print(f"\n{'Would rename' if args.dry_run else 'Renamed'} {rename_count} files/directories.\n")

    # Step 2: Process file contents
    print("=" * 70)
    print("STEP 2: Updating file contents")
    print("=" * 70)
    modified_count = 0
    error_count = 0
    total_files = 0

    all_files = list(root.rglob('*'))
    for path in all_files:
        if should_process_file(path):
            total_files += 1
            if process_file(path, args.dry_run):
                modified_count += 1
        # else ignore

    print(f"\nProcessed {total_files} files")
    print(f"{'Would modify' if args.dry_run else 'Modified'} {modified_count} files")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total files scanned: {len(all_files)}")
    print(f"Text files processed: {total_files}")
    print(f"{'Changes to apply' if args.dry_run else 'Changes applied'}:")
    print(f"  - Files to rename: {rename_count}")
    print(f"  - Files modified: {modified_count}")
    print()

    if args.dry_run:
        print("DRY RUN complete. Run without --dry-run to apply changes.")
    else:
        print("✓ RENAME COMPLETE!")
        print()
        print("Next steps:")
        print("1. Verify changes: git status, git diff")
        print("2. Look for any missed occurrences: grep -ri 'clipsight' --exclude-dir=.git")
        print("3. Build and test: docker-compose build")
        print("4. Run unit tests: pytest tests/unit/ -v")
        print("5. Fix any remaining issues manually")
        print("6. Commit: git add -A && git commit -m 'feat(rename): deepSightAI Trinetra'")

if __name__ == '__main__':
    import argparse
    main()
