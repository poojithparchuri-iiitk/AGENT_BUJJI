import re
from datetime import datetime
from database import get_connection

TIME_FORMAT = "%Y-%m-%d %H:%M"
DATE_FORMAT = "%Y-%m-%d"

MAX_TEXT_LENGTH = 200

# Words ignored when matching an activity by its description
STOP_WORDS = {"the", "a", "an", "my", "one", "activity", "entry", "log", "it", "that", "this", "to", "of"}


def _clean_text(text):
    """One line, single spaces. Returns the cleaned text, or an error dict."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return {"error": "An activity needs a description. Nothing was saved. Ask the user what they did."}
    if len(cleaned) > MAX_TEXT_LENGTH:
        return {
            "error": f"That description is too long (over {MAX_TEXT_LENGTH} characters). Nothing was saved. "
                     "Ask the user for a shorter one."
        }
    return cleaned


def _init_table():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            done_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


_init_table()


def _row_to_dict(row):
    return {
        "id": row["id"],
        "description": row["description"],
        "done_at": row["done_at"],
    }


def _parse_done_at(value):
    """Accept 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'. A date alone is stored as 00:00.
    Returns a datetime, or None if the format is wrong."""
    text = str(value).strip()
    for fmt in (TIME_FORMAT, DATE_FORMAT):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _find_activities(activity_id=None, description=None):
    """Find activities by ID, or by words from the description. Returns a list of rows."""
    ref = activity_id if activity_id is not None else description
    if ref is None:
        return []
    text = str(ref).strip()

    conn = get_connection()
    if text.isdigit():
        rows = conn.execute("SELECT * FROM activities WHERE id = ?", (int(text),)).fetchall()
    else:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]
        all_rows = conn.execute("SELECT * FROM activities ORDER BY done_at").fetchall()
        rows = [r for r in all_rows if words and all(w in r["description"].lower() for w in words)]
    conn.close()
    return rows


def _ambiguous(rows):
    return {
        "error": "More than one activity matches. Ask the user which one they mean.",
        "matches": [_row_to_dict(r) for r in rows],
    }


def log_activity(description: str, done_at: str = None):
    """Record something the user has already done. With no done_at, it means right now."""
    clean = _clean_text(description)
    if isinstance(clean, dict):
        return clean

    now = datetime.now().replace(second=0, microsecond=0)

    if done_at:
        when = _parse_done_at(done_at)
        if when is None:
            return {"error": "The time must be in the format YYYY-MM-DD HH:MM (or YYYY-MM-DD)."}
        if when > now:
            return {"error": "That is in the future, and this log is only for things already done."}
    else:
        when = now

    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO activities (description, done_at) VALUES (?, ?)",
        (clean, when.strftime(TIME_FORMAT)),
    )
    conn.commit()
    new_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM activities WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def list_activities(date: str = None):
    """Everything logged on one day. With no date, it means today."""
    if date:
        try:
            datetime.strptime(str(date).strip(), DATE_FORMAT)
        except ValueError:
            return {"error": "The date must be in the format YYYY-MM-DD."}
        day = str(date).strip()
    else:
        day = datetime.now().strftime(DATE_FORMAT)

    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM activities WHERE done_at LIKE ? ORDER BY done_at",
        (day + "%",),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def delete_activity(activity_id=None, description=None):
    rows = _find_activities(activity_id, description)
    if not rows:
        return False
    if len(rows) > 1:
        return _ambiguous(rows)

    conn = get_connection()
    conn.execute("DELETE FROM activities WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    conn.close()
    return True


# --- Tool Manifest ---
# Read by agent.py to build the prompt and the function map.

TOOL_MANIFEST = [
    {
        "name": "log_activity",
        "description": "Record something the user has ALREADY finished or done (past tense, for example 'I finished my SQL assignment')",
        "args": {
            "description": "string, what the user did",
            "done_at": "string YYYY-MM-DD HH:MM or YYYY-MM-DD (optional, only if the user says it happened earlier, otherwise leave it out)",
        },
        "function": log_activity,
    },
    {
        "name": "list_activities",
        "description": "List what the user has done on one day (today by default)",
        "args": {
            "date": "string YYYY-MM-DD (optional, only to see a day other than today)",
        },
        "function": list_activities,
    },
    {
        "name": "delete_activity",
        "description": "Delete one logged activity, for example one that was logged by mistake",
        "args": {
            "activity_id": "integer, only if the ID is known",
            "description": "string, words from the activity description (use when the ID is not known)",
        },
        "function": delete_activity,
    },
]