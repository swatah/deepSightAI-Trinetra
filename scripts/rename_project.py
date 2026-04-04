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

# Naming scheme:
# - DISPLAY_NAME: product name for docs/UI (with space): "deepSightAI Trinetra"
# - TECHNICAL_NAME: code identifiers (Docker, DB, constants) with hyphen: "deepSightAI-Trinetra"
# - URL_SUBDOMAIN: URL subdomain short form: "trinetra"
DISPLAY_NAME = "deepSightAI Trinetra"
TECHNICAL_NAME = "deepSightAI-Trinetra"
URL_SUBDOMAIN = "trinetra"

# ============================================================================
# REPLACEMENT RULES
# ============================================================================

# Each tuple: (pattern, replacement)
# Patterns are regex, use raw strings
REPLACEMENTS = [
    # === Display/Brand Names ===
    # Case-sensitive exact: "ClipSight" → "deepSightAI-Trinetra"
    (r'\bClipSight\b', DISPLAY_NAME, re.MULTILINE),
    # The rest of the patterns match "clipsight" case-insensitively

    # === URLs (must be first before generic clipsight→trinetra) ===
    (r'https?://api\.clipsight\.com', 'https://api.trinetra.com'),
    (r'https?://auth\.clipsight\.com', 'https://auth.trinetra.com'),
    (r'https?://app\.clipsight\.com', 'https://app.trinetra.com'),
    (r'https?://staging-api\.clipsight\.com', 'https://staging-api.trinetra.com'),
    (r'https?://github\.com/yourorg/clipsight', 'https://github.com/yourorg/deepSightAI-Trinetra'),
    (r'https?://hub\.docker\.com/u/clipsight', 'https://hub.docker.com/u/trinetra'),

    # === Docker Images ===
    (r'image:\s*clipsight/', f'image: {TECHNICAL_NAME}/'),
    (r'clipsight/registry', f'{TECHNICAL_NAME}/registry'),
    (r'clipsight/main-api', f'{TECHNICAL_NAME}/main-api'),
    (r'clipsight/extractor', f'{TECHNICAL_NAME}/extractor'),
    (r'clipsight/embedder', f'{TECHNICAL_NAME}/embedder'),
    (r'clipsight/search-api', f'{TECHNICAL_NAME}/search-api'),
    # Docker build -t tags
    (r'-t\s+clipsight/', f'-t {TECHNICAL_NAME}/'),
    (r'docker build -t clipsight/', f'docker build -t {TECHNICAL_NAME}/'),

    # === Database Names ===
    (r'\bclipsight_test\b', f'{TECHNICAL_NAME}_test'),
    (r'\bclipsight\b(?!\w)', TECHNICAL_NAME),  # clipsight as standalone word

    # === Redis / Kafka / MinIO prefixes ===
    (r'clipsight:', f'{TECHNICAL_NAME}:'),
    (r'clipsight_', f'{TECHNICAL_NAME}_'),
    (r'clipsight-', f'{TECHNICAL_NAME}-'),

    # === Kubernetes / ArgoCD ===
    (r'clipsight-staging', f'{TECHNICAL_NAME}-staging'),
    (r'clipsight-production', f'{TECHNICAL_NAME}-production'),
    # Labels
    (r'(app\.kubernetes\.io/part-of:\s*)clipsight', rf'\1{TECHNICAL_NAME}'),
    (r'(app\.kubernetes\.io/name:\s*)clipsight', rf'\1{TECHNICAL_NAME}'),
    (r'(app\.kubernetes\.io/instance:\s*)clipsight', rf'\1{TECHNICAL_NAME}'),
    # Namespace references
    (r'namespace:\s*clipsight-staging', f'namespace: {TECHNICAL_NAME}-staging'),
    (r'namespace:\s*clipsight-production', f'namespace: {TECHNICAL_NAME}-production'),
    (r'namespace:\s*clipsight(\b|-)', f'namespace: {TECHNICAL_NAME}\\1'),

    # === Helm Charts ===
    (r'name:\s*clipsight', f'name: {TECHNICAL_NAME}'),
    (r'app\.kubernetes\.io/part-of: clipsight', f'app.kubernetes.io/part-of: {TECHNICAL_NAME}'),

    # === mkdocs.yml ===
    (r'site_name:\s*ClipSight Enterprise', f'site_name: {DISPLAY_NAME} Enterprise', re.MULTILINE),
    (r'site_author:\s*ClipSight Team', f'site_author: {DISPLAY_NAME} Team', re.MULTILINE),
    (r'repo_url:\s*https://github\.com/yourorg/clipsight', f'repo_url: https://github.com/yourorg/{TECHNICAL_NAME}'),
    (r'repo_name:\s*yourorg/clipsight', f'repo_name: yourorg/{TECHNICAL_NAME}'),
    (r'link:\s*https://github\.com/yourorg/clipsight', f'link: https://github.com/yourorg/{TECHNICAL_NAME}'),
    (r'link:\s*https://hub\.docker\.com/u/clipsight', f'link: https://hub.docker.com/u/{URL_SUBDOMAIN}'),

    # === Documentation generic (fallback) - catch any remaining clipsight ===
    (r'clipsight', TECHNICAL_NAME),
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

    # Skip the rename script itself to prevent self-modification
    if path.name == 'rename_project.py' and path.parent.name == 'scripts':
        return False

    # Skip common non-text directories
    skip_dirs = {
        'node_modules', 'venv', '__pycache__', '.pytest_cache',
        'site-packages', 'dist', 'build', '.tox', '.coverage',
        '.idea', '.vscode', '.eggs', '*.egg-info',
    }
    for part in path.parts:
        if part.startswith('.') and part != '.' and part != '.github':
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
    for item in REPLACEMENTS:
        if len(item) == 3:
            pattern, replacement, flags = item
        else:
            pattern, replacement = item
            flags = re.MULTILINE | re.IGNORECASE  # Default: case-insensitive
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
    # First, handle exact capitalized brand (case-sensitive)
    new_name = re.sub(r'ClipSight', DISPLAY_NAME, new_name)
    # Then handle any case variation of clipsight (technical identifiers)
    new_name = re.sub(r'clipsight', TECHNICAL_NAME, new_name, flags=re.IGNORECASE)
    # Additional patterns for filenames
    new_name = re.sub(r'clipsight-staging', f'{TECHNICAL_NAME}-staging', new_name, flags=re.IGNORECASE)
    new_name = re.sub(r'clipsight-production', f'{TECHNICAL_NAME}-production', new_name, flags=re.IGNORECASE)
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
