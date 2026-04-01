#!/bin/bash
# Install git hooks from templates

set -e

HOOKS_DIR=".git/hooks"
TEMPLATES_DIR="$(dirname "$0")/../git-hooks"

# Create git-hooks directory if not exists
mkdir -p "$TEMPLATES_DIR"

# Create commit-msg hook template
cat > "$TEMPLATES_DIR/commit-msg" << 'EOF'
#!/bin/bash
# Git commit-msg hook to ensure task tracking is followed

COMMIT_MSG_FILE="$1"
COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

# Check if commit message references a task ID
if ! echo "$COMMIT_MSG" | grep -qE "Task: T\d+\.\d+\.\d+"; then
    echo "ERROR: Commit message must reference a task ID"
    echo "Format: 'feat(component): description\n\n- Task: T1.2.3\n- Tests: path/to/test.py\n- Time: Xh'"
    echo ""
    echo "Generate proper message with:"
    echo "  ./scripts/tracking.py commit-msg T1.2.3 > .commit_msg_temp"
    echo "  And copy the output to your commit message"
    exit 1
fi

# Check if task exists in tracking database
TASK_ID=$(echo "$COMMIT_MSG" | grep -oE "Task: T\d+\.\d+\.\d+" | cut -d' ' -f2)
if [ -n "$TASK_ID" ]; then
    if ! python3 scripts/tracking.py show "$TASK_ID" > /dev/null 2>&1; then
        echo "WARNING: Task $TASK_ID not found in tracking database"
        echo "Run './scripts/tracking.py init' if you haven't already"
    fi
fi

echo "✓ Commit message includes task reference"
exit 0
EOF

# Create pre-commit hook template for running tests
cat > "$TEMPLATES_DIR/pre-commit" << 'EOF'
#!/bin/bash
# Pre-commit hook: run tests for changed files

# Get list of changed files
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '^tests/' | grep '\.py$')

if [ -z "$CHANGED_FILES" ]; then
    echo "No test files changed, skipping test run"
    exit 0
fi

echo "Running tests for changed files..."
echo "$CHANGED_FILES" | xargs pytest -v --tb=short

if [ $? -ne 0 ]; then
    echo "ERROR: Tests failed!"
    echo "Fix tests before committing."
    exit 1
fi

echo "✓ All tests passing"
exit 0
EOF

# Make hooks executable
chmod +x "$TEMPLATES_DIR/commit-msg"
chmod +x "$TEMPLATES_DIR/pre-commit"

# Copy to .git/hooks
cp "$TEMPLATES_DIR/commit-msg" "$HOOKS_DIR/commit-msg"
cp "$TEMPLATES_DIR/pre-commit" "$HOOKS_DIR/pre-commit"

echo "✓ Git hooks installed:"
echo "  - commit-msg: Validates task reference in commit message"
echo "  - pre-commit:  Runs tests for changed files"
echo ""
echo "To disable hooks, remove or rename files in $HOOKS_DIR"
