import re
from database import get_connection, init_db

# Make sure the tasks table exists
init_db()

# Words ignored when matching a task by its title
STOP_WORDS = {"the", "a", "an", "my", "one", "task", "tasks", "it", "that", "this", "to", "of"}


def _row_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "due_date": row["due_date"],
        "completed": bool(row["completed"]),
    }


def _find_tasks(task_id=None, title=None):
    """Find tasks by ID, or by words from the title. Returns a list of rows."""
    ref = task_id if task_id is not None else title
    if ref is None:
        return []
    text = str(ref).strip()

    conn = get_connection()
    if text.isdigit():
        rows = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(text),)).fetchall()
    else:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]
        all_rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        rows = [r for r in all_rows if words and all(w in r["title"].lower() for w in words)]
    conn.close()
    return rows


def _ambiguous(rows):
    return {
        "error": "More than one task matches. Ask the user which one they mean.",
        "matches": [_row_to_dict(r) for r in rows],
    }


def add_task(title: str, due_date: str = None):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO tasks (title, due_date) VALUES (?, ?)",
        (title, due_date),
    )
    conn.commit()
    new_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def list_tasks():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def complete_task(task_id=None, title=None):
    rows = _find_tasks(task_id, title)
    if not rows:
        return None
    if len(rows) > 1:
        return _ambiguous(rows)

    conn = get_connection()
    conn.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (rows[0]["id"],)).fetchone()
    conn.close()
    return _row_to_dict(row)


def delete_task(task_id=None, title=None):
    rows = _find_tasks(task_id, title)
    if not rows:
        return False
    if len(rows) > 1:
        return _ambiguous(rows)

    conn = get_connection()
    conn.execute("DELETE FROM tasks WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    conn.close()
    return True


def clear_completed_tasks():
    conn = get_connection()
    cursor = conn.execute("DELETE FROM tasks WHERE completed = 1")
    conn.commit()
    conn.close()
    return {"deleted_count": cursor.rowcount}


# --- Tool Manifest ---
# Read by agent.py to build the prompt and the function map.

TOOL_MANIFEST = [
    {
        "name": "add_task",
        "description": "Add a new task",
        "args": {"title": "string", "due_date": "string YYYY-MM-DD (optional)"},
        "function": add_task,
    },
    {
        "name": "list_tasks",
        "description": "List all tasks",
        "args": {},
        "function": list_tasks,
    },
    {
        "name": "complete_task",
        "description": "Mark one task as completed",
        "args": {
            "task_id": "integer, only if the ID is known",
            "title": "string, words from the task title (use when the ID is not known)",
        },
        "function": complete_task,
    },
    {
        "name": "delete_task",
        "description": "Delete one task",
        "args": {
            "task_id": "integer, only if the ID is known",
            "title": "string, words from the task title (use when the ID is not known)",
        },
        "function": delete_task,
    },
    {
        "name": "clear_completed_tasks",
        "description": "Delete ALL tasks that are already completed",
        "args": {},
        "function": clear_completed_tasks,
    },
]