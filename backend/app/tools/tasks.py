import re
from datetime import datetime
from database import get_connection, init_db

# Make sure the tasks table exists
init_db()

# Words ignored when matching a task by its title
STOP_WORDS = {"the", "a", "an", "my", "one", "task", "tasks", "it", "that", "this", "to", "of"}

MAX_TITLE_LENGTH = 200

DATE_ERROR = {
    "error": "The due date must be a real date in the form YYYY-MM-DD, or YYYY-MM-DD HH:MM. "
             "Nothing was saved. Ask the user for the date."
}


def _clean_title(title):
    """One line, single spaces. Returns the cleaned title, or an error dict."""
    text = " ".join(str(title or "").split())
    if not text:
        return {"error": "A task needs a title. Nothing was saved. Ask the user what the task is."}
    if len(text) > MAX_TITLE_LENGTH:
        return {
            "error": f"That title is too long (over {MAX_TITLE_LENGTH} characters). Nothing was saved. "
                     "Ask the user for a shorter title."
        }
    return text


def _clean_due_date(value):
    """None for no due date, the cleaned date as text, or an error dict."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            datetime.strptime(text, fmt)
            return text
        except ValueError:
            continue
    return DATE_ERROR


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
    clean = _clean_title(title)
    if isinstance(clean, dict):
        return clean
    due = _clean_due_date(due_date)
    if isinstance(due, dict):
        return due

    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO tasks (title, due_date) VALUES (?, ?)",
        (clean, due),
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


def edit_task(task_id=None, title=None, new_title=None, new_due_date=None):
    """Change the title and/or due date of one task."""
    if not new_title and not new_due_date:
        return {"error": "Nothing to change. Ask the user what the new title or new due date should be."}

    # Check the new values first, so nothing is changed if one of them is bad
    clean_title = None
    if new_title:
        clean_title = _clean_title(new_title)
        if isinstance(clean_title, dict):
            return clean_title
    clean_due = None
    if new_due_date:
        clean_due = _clean_due_date(new_due_date)
        if isinstance(clean_due, dict):
            return clean_due

    rows = _find_tasks(task_id, title)
    if not rows:
        return None
    if len(rows) > 1:
        return _ambiguous(rows)

    target_id = rows[0]["id"]
    conn = get_connection()
    if clean_title:
        conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (clean_title, target_id))
    if clean_due:
        conn.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (clean_due, target_id))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (target_id,)).fetchone()
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
        "args": {"title": "string", "due_date": "string YYYY-MM-DD or YYYY-MM-DD HH:MM (optional)"},
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
        "name": "edit_task",
        "description": "Change the title and/or the due date of one existing task",
        "args": {
            "task_id": "integer, only if the ID is known",
            "title": "string, words from the CURRENT title, used to find the task",
            "new_title": "string, the new title (optional)",
            "new_due_date": "string YYYY-MM-DD or YYYY-MM-DD HH:MM, the new due date (optional)",
        },
        "function": edit_task,
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