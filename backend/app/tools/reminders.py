import re
from datetime import datetime
from database import get_connection

TIME_FORMAT = "%Y-%m-%d %H:%M"

MAX_TEXT_LENGTH = 200

# Words ignored when matching a reminder by its text
STOP_WORDS = {"the", "a", "an", "my", "one", "reminder", "reminders", "remind", "me", "it", "that", "this", "to", "of"}

TIME_ERROR = {
    "error": "I need both the date AND the time (format YYYY-MM-DD HH:MM). Ask the user for the missing part."
}


def _clean_text(text):
    """One line, single spaces. Returns the cleaned text, or an error dict."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return {"error": "A reminder needs some text. Nothing was saved. Ask the user what to remind them about."}
    if len(cleaned) > MAX_TEXT_LENGTH:
        return {
            "error": f"That reminder is too long (over {MAX_TEXT_LENGTH} characters). Nothing was saved. "
                     "Ask the user for a shorter one."
        }
    return cleaned


def _init_table():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            fired INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


_init_table()


def _row_to_dict(row):
    return {
        "id": row["id"],
        "text": row["text"],
        "remind_at": row["remind_at"],
    }


def _parse_time(value):
    """Turn 'YYYY-MM-DD HH:MM' into a datetime, or None if it is not in that format."""
    try:
        return datetime.strptime(str(value).strip(), TIME_FORMAT)
    except ValueError:
        return None


def _find_reminders(reminder_id=None, text=None):
    """Find pending reminders by ID, or by words from the text. Returns a list of rows."""
    ref = reminder_id if reminder_id is not None else text
    if ref is None:
        return []
    query = str(ref).strip()

    conn = get_connection()
    if query.isdigit():
        rows = conn.execute(
            "SELECT * FROM reminders WHERE id = ? AND fired = 0", (int(query),)
        ).fetchall()
    else:
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOP_WORDS]
        all_rows = conn.execute(
            "SELECT * FROM reminders WHERE fired = 0 ORDER BY remind_at"
        ).fetchall()
        rows = [r for r in all_rows if words and all(w in r["text"].lower() for w in words)]
    conn.close()
    return rows


def _ambiguous(rows):
    return {
        "error": "More than one reminder matches. Ask the user which one they mean.",
        "matches": [_row_to_dict(r) for r in rows],
    }


def add_reminder(text: str, remind_at: str):
    clean = _clean_text(text)
    if isinstance(clean, dict):
        return clean

    when = _parse_time(remind_at)
    if when is None:
        return TIME_ERROR

    # A reminder in the past could never fire, so refuse it
    this_minute = datetime.now().replace(second=0, microsecond=0)
    if when < this_minute:
        return {"error": "That time has already passed. Ask the user for a time in the future."}

    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO reminders (text, remind_at) VALUES (?, ?)",
        (clean, when.strftime(TIME_FORMAT)),
    )
    conn.commit()
    new_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def list_reminders():
    """All reminders that have not gone off yet."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE fired = 0 ORDER BY remind_at"
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def delete_reminder(reminder_id=None, text=None):
    rows = _find_reminders(reminder_id, text)
    if not rows:
        return False
    if len(rows) > 1:
        return _ambiguous(rows)

    conn = get_connection()
    conn.execute("DELETE FROM reminders WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    conn.close()
    return True


# --- Used by the backend (NOT tools the model can call) ---

def get_due_reminders():
    """Reminders whose time has arrived and that have not been shown yet."""
    now_str = datetime.now().strftime(TIME_FORMAT)
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE fired = 0 AND remind_at <= ? ORDER BY remind_at",
        (now_str,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def mark_fired(reminder_ids):
    """Mark reminders as shown, so each one only pops up once."""
    if not reminder_ids:
        return
    conn = get_connection()
    for rid in reminder_ids:
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (rid,))
    conn.commit()
    conn.close()


# --- Tool Manifest ---
# Read by agent.py to build the prompt and the function map.

TOOL_MANIFEST = [
    {
        "name": "add_reminder",
        "description": "Set a reminder that alerts the user at a specific date and time",
        "args": {
            "text": "string, what to remind the user about",
            "remind_at": "string YYYY-MM-DD HH:MM (date AND time required, 24-hour clock, must be in the future)",
        },
        "function": add_reminder,
    },
    {
        "name": "list_reminders",
        "description": "List all pending reminders that have not gone off yet",
        "args": {},
        "function": list_reminders,
    },
    {
        "name": "delete_reminder",
        "description": "Delete one pending reminder",
        "args": {
            "reminder_id": "integer, only if the ID is known",
            "text": "string, words from the reminder text (use when the ID is not known)",
        },
        "function": delete_reminder,
    },
]