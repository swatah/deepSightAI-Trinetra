#!/usr/bin/env python3
"""
Task tracking and progress management for ClipSight enterprise development.
Ensures no work is lost and every task is test-driven.
"""

import json
import sys
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

TASK_STATE_DIR = Path(__file__).parent.parent / ".task_state"
TASKS_DB = TASK_STATE_DIR / "tasks.json"
HISTORY_LOG = TASK_STATE_DIR / "history.log"
CURRENT_TASK_FILE = TASK_STATE_DIR / "current_task"

# Ensure directories exist
TASK_STATE_DIR.mkdir(exist_ok=True)


class TaskDB:
    """Simple JSON-based task database."""

    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load tasks from disk."""
        if TASKS_DB.exists():
            with open(TASKS_DB) as f:
                self.tasks = json.load(f)
        else:
            # Initialize with empty task structure if not exists
            self.tasks = {"tasks": {}}
            self._save()

    def _save(self):
        """Save tasks to disk."""
        with open(TASKS_DB, "w") as f:
            json.dump(self.tasks, f, indent=2)

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get task by ID."""
        return self.tasks["tasks"].get(task_id)

    def update_task(self, task_id: str, **kwargs):
        """Update task fields."""
        task = self.tasks["tasks"].get(task_id)
        if task:
            task.update(kwargs)
            task["modified_at"] = datetime.utcnow().isoformat()
            self._save()

    def create_task(self, task_id: str, **kwargs):
        """Create new task."""
        if task_id in self.tasks["tasks"]:
            raise ValueError(f"Task {task_id} already exists")
        task = {
            "id": task_id,
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending",
            **kwargs
        }
        self.tasks["tasks"][task_id] = task
        self._save()

    def list_tasks(self, phase: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
        """List tasks with optional filters."""
        tasks = list(self.tasks["tasks"].values())
        if phase:
            tasks = [t for t in tasks if t.get("phase") == phase]
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return sorted(tasks, key=lambda t: t["id"])

    def log_history(self, action: str, task_id: str, message: str):
        """Log action to history file."""
        timestamp = datetime.utcnow().isoformat()
        with open(HISTORY_LOG, "a") as f:
            f.write(f"{timestamp} | {action} | {task_id} | {message}\n")


def init_tracking():
    """Initialize tracking database with tasks from DEVELOPMENT_TRACKING.md."""
    print("Initializing task tracking system...")

    # Parse DEVELOPMENT_TRACKING.md to extract tasks
    tracking_doc = Path(__file__).parent.parent / "DEVELOPMENT_TRACKING.md"
    if not tracking_doc.exists():
        print(f"ERROR: {tracking_doc} not found")
        sys.exit(1)

    # Simple parsing: look for | Task | Description | tables
    db = TaskDB()
    import re

    content = tracking_doc.read_text()
    # Extract task rows from markdown tables
    # Pattern: | T1.1.1 | description | criteria | tests | files |
    pattern = r'\|\s*(T\d+\.\d+\.\d+)\s*\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|'

    for match in re.finditer(pattern, content):
        task_id, desc, criteria, tests, files = [g.strip() for g in match.groups()]
        if not db.get_task(task_id):
            db.create_task(
                task_id,
                description=desc,
                acceptance_criteria=criteria,
                test_files=tests,
                impl_files=files,
                status="pending",
                phase=task_id.split('.')[0][1:],  # '1' from 'T1'
                estimated_hours=0  # Could parse from doc if added
            )
            print(f"  Created task {task_id}")

    db.log_history("init", "system", f"Loaded {len(db.tasks['tasks'])} tasks")
    print(f"\n✓ Tracking initialized with {len(db.tasks['tasks'])} tasks")


def start_task(task_id: str):
    """Start working on a task."""
    db = TaskDB()
    task = db.get_task(task_id)
    if not task:
        print(f"ERROR: Task {task_id} not found")
        sys.exit(1)

    if task["status"] not in ["pending", "blocked"]:
        print(f"ERROR: Task {task_id} is {task['status']}, cannot start")
        sys.exit(1)

    # Check dependencies
    deps_file = Path(__file__).parent.parent / "DEPS.md"
    if deps_file.exists():
        content = deps_file.read_text()
        # Parse dependencies
        import re
        pattern = rf"{task_id}.*?depends on[:\s]+([T\d., ]+)"
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            deps = [d.strip() for d in match.group(1).split(',')]
            for dep in deps:
                dep_task = db.get_task(dep)
                if dep_task and dep_task["status"] != "completed":
                    print(f"ERROR: Dependency {dep} not completed (status: {dep_task['status']})")
                    sys.exit(1)

    # Mark as in_progress
    db.update_task(task_id,
                   status="in_progress",
                   started_at=datetime.utcnow().isoformat())
    db.log_history("start", task_id, f"Started work on {task['description']}")

    # Write current task file
    CURRENT_TASK_FILE.write_text(task_id)

    print(f"✓ Started task {task_id}: {task['description']}")
    print(f"  Tests: {task['test_files']}")
    print(f"  Files: {task['impl_files']}")
    print(f"\n  Run: pytest {task['test_files']}  (should FAIL - red phase)")
    print(f"  Then: write code to make it PASS")


def complete_task(task_id: str):
    """Mark task as complete."""
    db = TaskDB()
    task = db.get_task(task_id)
    if not task:
        print(f"ERROR: Task {task_id} not found")
        sys.exit(1)

    if task["status"] != "in_progress":
        print(f"ERROR: Task {task_id} is {task['status']}, not in_progress")
        sys.exit(1)

    # Verify tests pass
    test_files = task.get("test_files", "")
    if test_files:
        print(f"Running tests: {test_files}...")
        result = subprocess.run(
            ["pytest", test_files, "-v"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print("ERROR: Tests failing! Fix before completing.")
            print(result.stdout)
            print(result.stderr)
            sys.exit(1)
        print("✓ Tests passing")

    # Calculate time spent
    started = datetime.fromisoformat(task["started_at"])
    completed = datetime.utcnow()
    hours = (completed - started).total_seconds() / 3600

    # Mark complete
    db.update_task(task_id,
                   status="completed",
                   completed_at=completed.isoformat(),
                   hours_spent=round(hours, 2))
    db.log_history("complete", task_id, f"Completed in {hours:.2f}h")

    # Generate commit message
    commit_msg = generate_commit_message(task_id, task, hours)
    print(f"\n✓ Task {task_id} completed ({hours:.2f}h)")
    print(f"\nSuggested commit message:\n{'='*60}")
    print(commit_msg)
    print(f"{'='*60}\n")
    print("To commit, run:")
    print(f"  git add . && git commit -m '{commit_msg.replace(chr(10), ' ')}'")

    # Clear current task
    if CURRENT_TASK_FILE.exists():
        CURRENT_TASK_FILE.unlink()

    # Suggest next task
    suggest_next_task(task_id)


def generate_commit_message(task_id: str, task: dict, hours: float) -> str:
    """Generate conventional commit message from task."""
    # Map task to commit type based on phase
    phase = int(task.get("phase", "1"))
    if phase == 1:
        commit_type = "feat"
    elif phase == 4:
        commit_type = "perf"
    elif phase == 5:
        commit_type = "feat"
    else:
        commit_type = "fix"  # or "refactor"

    # Extract area/component from files or description
    component = "core"
    impl_files = task.get("impl_files", "")
    if "auth" in impl_files.lower():
        component = "auth"
    elif "milvus" in impl_files.lower():
        component = "milvus"
    elif "k8s" in impl_files.lower():
        component = "k8s"

    # Short description from task description (first sentence)
    desc = task["description"].split('.')[0].strip()

    msg = f"{commit_type}({component}): {desc}\n\n"
    msg += f"- Task: {task_id}\n"
    msg += f"- Tests: {task.get('test_files', 'N/A')}\n"
    msg += f"- Time: {hours:.2f}h"

    return msg


def suggest_next_task(current_task_id: str):
    """Suggest next unblocked task."""
    db = TaskDB()

    # Find tasks that depend on current
    deps_file = Path(__file__).parent.parent / "DEPS.md"
    if not deps_file.exists():
        # Create DEPS file if doesn't exist
        deps_file.write_text("# Task Dependencies\n\n")
        return

    content = deps_file.read_text()

    # Find tasks waiting on current task
    import re
    pattern = rf"([T\d]+\.\d+\.\d+).*?depends on[:\s]+{current_task_id}[, ]?"
    waiters = re.findall(pattern, content)

    if waiters:
        print("\nNext tasks that can now start:")
        for waiter in waiters[:3]:  # Show max 3
            task = db.get_task(waiter)
            if task and task["status"] in ["pending", "blocked"]:
                print(f"  - {waiter}: {task['description']}")
    else:
        # Suggest next pending task in same phase
        current_phase = current_task_id.split('.')[0][1:]
        pending_tasks = db.list_tasks(phase=current_phase, status="pending")
        if pending_tasks:
            print("\nNext pending tasks in this phase:")
            for task in pending_tasks[:3]:
                print(f"  - {task['id']}: {task['description']}")
        else:
            print("\n✓ Phase complete! Move to next phase.")


def list_tasks(phase: Optional[str] = None, status: Optional[str] = None):
    """List tasks in formatted table."""
    db = TaskDB()
    tasks = db.list_tasks(phase=phase, status=status)

    if not tasks:
        print("No tasks found")
        return

    # Print table
    print(f"{'ID':<12} {'Status':<12} {'Phase':<6} {'Description':<50}")
    print("=" * 100)
    for task in tasks:
        print(f"{task['id']:<12} {task['status']:<12} {task.get('phase','?'):<6} {task['description'][:50]:<50}")


def block_task(task_id: str, waiting_on: str, reason: str):
    """Mark task as blocked, waiting on another."""
    db = TaskDB()
    db.update_task(task_id,
                   status="blocked",
                   blocked_by=waiting_on,
                   block_reason=reason)
    db.log_history("block", task_id, f"Blocked waiting for {waiting_on}: {reason}")
    print(f"✓ Task {task_id} marked as blocked (waiting for {waiting_on})")


def show_task(task_id: str):
    """Show task details."""
    db = TaskDB()
    task = db.get_task(task_id)
    if not task:
        print(f"Task {task_id} not found")
        return

    print(f"Task: {task_id}")
    print(f"Description: {task['description']}")
    print(f"Status: {task['status']}")
    print(f"Phase: {task.get('phase', '?')}")
    print(f"Created: {task.get('created_at', 'unknown')}")
    if task.get('started_at'):
        print(f"Started: {task['started_at']}")
    if task.get('completed_at'):
        print(f"Completed: {task['completed_at']}")
        print(f"Time spent: {task.get('hours_spent', 0)}h")
    print(f"\nTests: {task.get('test_files', 'N/A')}")
    print(f"Implementation: {task.get('impl_files', 'N/A')}")
    print(f"\nAcceptance:\n{task.get('acceptance_criteria', 'N/A')}")


def generate_report(output: str = "progress.md"):
    """Generate progress report."""
    db = TaskDB()
    all_tasks = db.list_tasks()

    # Statistics
    total = len(all_tasks)
    completed = len([t for t in all_tasks if t["status"] == "completed"])
    in_progress = len([t for t in all_tasks if t["status"] == "in_progress"])
    blocked = len([t for t in all_tasks if t["status"] == "blocked"])
    pending = len([t for t in all_tasks if t["status"] == "pending"])

    # By phase
    phases = {}
    for task in all_tasks:
        phase = task.get("phase", "?")
        phases.setdefault(phase, {"total": 0, "completed": 0})
        phases[phase]["total"] += 1
        if task["status"] == "completed":
            phases[phase]["completed"] += 1

    # Generate markdown
    report = f"""# Development Progress Report

Generated: {datetime.utcnow().isoformat()}

## Summary

- **Total Tasks**: {total}
- **Completed**: {completed} ({100*completed/total if total else 0:.1f}%)
- **In Progress**: {in_progress}
- **Blocked**: {blocked}
- **Pending**: {pending}

## By Phase

| Phase | Total | Completed | % Complete |
|-------|-------|-----------|------------|
"""
    for phase in sorted(phases.keys()):
        p = phases[phase]
        pct = 100 * p["completed"] / p["total"] if p["total"] else 0
        report += f"| {phase} | {p['total']} | {p['completed']} | {pct:.1f}% |\n"

    # Current task
    if CURRENT_TASK_FILE.exists():
        current_id = CURRENT_TASK_FILE.read_text().strip()
        current_task = db.get_task(current_id)
        if current_task:
            report += f"\n## Current Task\n\n"
            report += f"- **{current_id}**: {current_task['description']}\n"
            report += f"- Started: {current_task.get('started_at', 'unknown')}\n"
            report += f"- Status: {current_task['status']}\n"

    report += "\n## Recent Activity\n\n"
    # Add last 20 history lines
    if HISTORY_LOG.exists():
        lines = HISTORY_LOG.read_text().strip().split('\n')[-20:]
        for line in lines:
            report += f"- {line}\n"

    Path(output).write_text(report)
    print(f"✓ Report written to {output}")


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Task tracking for ClipSight development")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # init
    subparsers.add_parser("init", help="Initialize tracking from DEVELOPMENT_TRACKING.md")

    # start
    start_parser = subparsers.add_parser("start", help="Start a task")
    start_parser.add_argument("task_id", help="Task ID (e.g., T1.1.1)")

    # complete
    complete_parser = subparsers.add_parser("complete", help="Complete a task")
    complete_parser.add_argument("task_id", help="Task ID")

    # list
    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("--phase", help="Filter by phase")
    list_parser.add_argument("--status", choices=["pending", "in_progress", "completed", "blocked"], help="Filter by status")

    # show
    show_parser = subparsers.add_parser("show", help="Show task details")
    show_parser.add_argument("task_id", help="Task ID")

    # block
    block_parser = subparsers.add_parser("block", help="Mark task as blocked")
    block_parser.add_argument("task_id", help="Task ID")
    block_parser.add_argument("--waiting-on", required=True, help="Task ID blocking this")
    block_parser.add_argument("--reason", required=True, help="Reason for block")

    # report
    report_parser = subparsers.add_parser("report", help="Generate progress report")
    report_parser.add_argument("--output", default="progress.md", help="Output file")

    # commit-msg
    commit_parser = subparsers.add_parser("commit-msg", help="Generate commit message (for git hook)")
    commit_parser.add_argument("task_id", help="Task ID")

    args = parser.parse_args()

    if args.command == "init":
        init_tracking()
    elif args.command == "start":
        start_task(args.task_id)
    elif args.command == "complete":
        complete_task(args.task_id)
    elif args.command == "list":
        list_tasks(args.phase, args.status)
    elif args.command == "show":
        show_task(args.task_id)
    elif args.command == "block":
        block_task(args.task_id, args.waiting_on, args.reason)
    elif args.command == "report":
        generate_report(args.output)
    elif args.command == "commit-msg":
        db = TaskDB()
        task = db.get_task(args.task_id)
        if task:
            # Get current task started time to calculate hours
            started = datetime.fromisoformat(task.get("started_at", datetime.utcnow().isoformat()))
            hours = (datetime.utcnow() - started).total_seconds() / 3600
            print(generate_commit_message(args.task_id, task, hours))
        else:
            print(f"ERROR: Task {args.task_id} not found", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
