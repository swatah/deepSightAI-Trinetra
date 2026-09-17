import json
import sys
from pathlib import Path

db_path = Path(".task_state/tasks.json")
if not db_path.exists():
    print("DB not found")
    sys.exit(1)

with open(db_path) as f:
    db = json.load(f)

for task_id in sys.argv[1:]:
    if task_id in db["tasks"]:
        db["tasks"][task_id]["status"] = "pending"
        print(f"Reopened {task_id}")

with open(db_path, "w") as f:
    json.dump(db, f, indent=2)
