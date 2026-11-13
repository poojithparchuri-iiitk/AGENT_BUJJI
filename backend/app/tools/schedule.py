import re
from datetime import datetime, timedelta
from database import get_connection

TIME_FORMAT = "%Y-%m-%d %H:%M"
DATE_FORMAT = "%Y-%m-%d"
DEFAULT_DURATION = timedelta(hours=1)

# Words ignored when matching an event by its title
STOP_WORDS = {"the", "a", "an", "my", "one", "event", "meeting", "it", "that", "this", "to", "of"}

TIME_ERROR = {
    "error": "I need both the date AND the time (format YYYY-MM-DD HH:MM). Ask the user for the missing part."
}

PAST_ERROR = {
    "error": "That time has already passed, so nothing was saved. Tell the user, and ask whether they "
             "meant a later date. If it already happened, they can log it as an activity instead."
}


def _now():
    return datetime.now().replace(second=0, microsecond=0)


def _init_table():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


_init_table()


def _row_to_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
    }


def _parse_time(value):
    """Turn 'YYYY-MM-DD HH:MM' into a datetime, or None if it is not in that format."""
    try:
        return datetime.strptime(str(value).strip(), TIME_FORMAT)
    except ValueError:
        return None


def _find_events(event_id=None, title=None):
    """Find events by ID, or by words from the title. Returns a list of rows."""
    ref = event_id if event_id is not None else title
    if ref is None:
        return []
    text = str(ref).strip()

    conn = get_connection()
    if text.isdigit():
        rows = conn.execute("SELECT * FROM events WHERE id = ?", (int(text),)).fetchall()
    else:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]
        all_rows = conn.execute("SELECT * FROM events ORDER BY start_time").fetchall()
        rows = [r for r in all_rows if words and all(w in r["title"].lower() for w in words)]
    conn.close()
    return rows


def _ambiguous(rows):
    return {
        "error": "More than one event matches. Ask the user which one they mean.",
        "matches": [_row_to_dict(r) for r in rows],
    }


def _conflicts(start_str, end_str, ignore_id=0):
    """Events that overlap the given time range (other than ignore_id)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events WHERE start_time < ? AND end_time > ? AND id != ? ORDER BY start_time",
        (end_str, start_str, ignore_id),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def add_event(title: str, start_time: str, end_time: str = None):
    start = _parse_time(start_time)
    if start is None:
        return TIME_ERROR

    if end_time:
        end = _parse_time(end_time)
        if end is None:
            return TIME_ERROR
    else:
        end = start + DEFAULT_DURATION  # no end time given: assume 1 hour

    if end <= start:
        return {"error": "The end time must be after the start time."}

    # An event that has already ended cannot be scheduled. One that is still going on can.
    if end < _now():
        return PAST_ERROR

    start_str = start.strftime(TIME_FORMAT)
    end_str = end.strftime(TIME_FORMAT)

    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO events (title, start_time, end_time) VALUES (?, ?, ?)",
        (title, start_str, end_str),
    )
    conn.commit()
    new_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM events WHERE id = ?", (new_id,)).fetchone()
    conn.close()

    result = _row_to_dict(row)
    clashes = _conflicts(start_str, end_str, ignore_id=new_id)
    if clashes:
        result["warning_overlaps_with"] = clashes
    return result


def list_events(date: str = None):
    """With a date (YYYY-MM-DD): all events that day. Without: upcoming events."""
    conn = get_connection()
    if date:
        try:
            datetime.strptime(str(date).strip(), DATE_FORMAT)
        except ValueError:
            conn.close()
            return {"error": "The date must be in the format YYYY-MM-DD."}
        rows = conn.execute(
            "SELECT * FROM events WHERE start_time LIKE ? ORDER BY start_time",
            (str(date).strip() + "%",),
        ).fetchall()
    else:
        now_str = datetime.now().strftime(TIME_FORMAT)
        rows = conn.execute(
            "SELECT * FROM events WHERE end_time >= ? ORDER BY start_time",
            (now_str,),
        ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def edit_event(event_id=None, title=None, new_title=None, new_start_time=None, new_end_time=None):
    """Change the title and/or the times of one event."""
    if not (new_title or new_start_time or new_end_time):
        return {"error": "Nothing to change. Ask the user what the new title or new time should be."}

    rows = _find_events(event_id, title)
    if not rows:
        return None
    if len(rows) > 1:
        return _ambiguous(rows)

    row = rows[0]
    old_start = _parse_time(row["start_time"])
    old_end = _parse_time(row["end_time"])

    start = old_start
    end = old_end

    if new_start_time:
        start = _parse_time(new_start_time)
        if start is None:
            return TIME_ERROR
        end = start + (old_end - old_start)  # moving the start keeps the same length
    if new_end_time:
        end = _parse_time(new_end_time)
        if end is None:
            return TIME_ERROR

    if end <= start:
        return {"error": "The end time must be after the start time."}

    # Moving an event into the past is refused. Renaming an old event is still fine.
    if (new_start_time or new_end_time) and end < _now():
        return PAST_ERROR

    start_str = start.strftime(TIME_FORMAT)
    end_str = end.strftime(TIME_FORMAT)
    final_title = new_title if new_title else row["title"]

    conn = get_connection()
    conn.execute(
        "UPDATE events SET title = ?, start_time = ?, end_time = ? WHERE id = ?",
        (final_title, start_str, end_str, row["id"]),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
    conn.close()

    result = _row_to_dict(updated)
    clashes = _conflicts(start_str, end_str, ignore_id=row["id"])
    if clashes:
        result["warning_overlaps_with"] = clashes
    return result


def delete_event(event_id=None, title=None):
    rows = _find_events(event_id, title)
    if not rows:
        return False
    if len(rows) > 1:
        return _ambiguous(rows)

    conn = get_connection()
    conn.execute("DELETE FROM events WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    conn.close()
    return True


# --- Tool Manifest ---
# Read by agent.py to build the prompt and the function map.

TOOL_MANIFEST = [
    {
        "name": "add_event",
        "description": "Add a calendar event (a meeting, class, appointment) at a specific date and time",
        "args": {
            "title": "string, the event name",
            "start_time": "string YYYY-MM-DD HH:MM (date AND time required, 24-hour clock)",
            "end_time": "string YYYY-MM-DD HH:MM (optional, defaults to 1 hour after the start)",
        },
        "function": add_event,
    },
    {
        "name": "list_events",
        "description": "List upcoming events, or every event on one particular day",
        "args": {
            "date": "string YYYY-MM-DD (optional, only to see one particular day)",
        },
        "function": list_events,
    },
    {
        "name": "edit_event",
        "description": "Change the title and/or the time of one existing event",
        "args": {
            "event_id": "integer, only if the ID is known",
            "title": "string, words from the CURRENT title, used to find the event",
            "new_title": "string, the new title (optional)",
            "new_start_time": "string YYYY-MM-DD HH:MM, the new start (optional)",
            "new_end_time": "string YYYY-MM-DD HH:MM, the new end (optional)",
        },
        "function": edit_event,
    },
    {
        "name": "delete_event",
        "description": "Delete one event from the calendar",
        "args": {
            "event_id": "integer, only if the ID is known",
            "title": "string, words from the event title (use when the ID is not known)",
        },
        "function": delete_event,
    },
]