from database import get_connection, init_db

# Make sure the tasks table exists
init_db()


def _row_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "due_date": row["due_date"],
        "completed": bool(row["completed"]),
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


def complete_task(task_id: int):
    conn = get_connection()
    conn.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def delete_task(task_id: int):
    conn = get_connection()
    cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


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
        "args": {"title": "string", "due_date": "string (optional)"},
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
        "description": "Mark a task as completed by its ID",
        "args": {"task_id": "integer"},
        "function": complete_task,
    },
    {
        "name": "delete_task",
        "description": "Delete one task by its ID",
        "args": {"task_id": "integer"},
        "function": delete_task,
    },
    {
        "name": "clear_completed_tasks",
        "description": "Delete ALL tasks that are already completed",
        "args": {},
        "function": clear_completed_tasks,
    },
]