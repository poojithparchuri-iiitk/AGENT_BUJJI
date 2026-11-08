import re
from datetime import datetime
from database import get_connection

TIME_FORMAT = "%Y-%m-%d %H:%M"
MAX_FACT_LENGTH = 200  # longer notes are refused, so the prompt stays small
MAX_IN_PROMPT = 30     # how many remembered facts Bujji sees with every message

# Words ignored when matching a fact by its text
STOP_WORDS = {
    "the", "a", "an", "my", "that", "this", "it", "to", "of", "about",
    "is", "are", "forget", "remember",
}

# Things that must never be stored. This is a pattern check, not a guarantee.
SENSITIVE_WORDS = re.compile(
    r"password|passcode|passphrase|api[ _-]?key|secret|credentials?"
    r"|\botp\b|\bone[ -]?time\b|\bcvv\b|\bpin\b"
    r"|(?:card|account)[ _-]?(?:number|no\b|details)"
    r"|(?:security|verification|login|unlock) code"
    r"|\bcode\b\D{0,15}\d{4,}"
    r"|aadhaar|aadhar|passport (?:number|no\b)|\bssn\b|social security"
    r"|\btoken\b",
    re.IGNORECASE,
)
SENSITIVE_SHAPES = re.compile(
    r"\b(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{16,}\b"  # long key-like text containing a digit
    r"|\b[a-z]{16}\b"                                # 16 lowercase letters, the shape of an app password
    r"|(?:\d[ -]?){13,}"                             # 13 or more digits, such as a card number
)


def _init_table():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


_init_table()


def _row_to_dict(row):
    return {"id": row["id"], "fact": row["fact"]}


def _find_memories(memory_id=None, fact=None):
    """Find remembered facts by ID, or by words from the text. Returns a list of rows."""
    ref = memory_id if memory_id is not None else fact
    if ref is None:
        return []
    text = str(ref).strip()

    conn = get_connection()
    if text.isdigit():
        rows = conn.execute("SELECT * FROM memories WHERE id = ?", (int(text),)).fetchall()
    else:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]
        all_rows = conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
        rows = [r for r in all_rows if words and all(w in r["fact"].lower() for w in words)]
    conn.close()
    return rows


def remember_fact(fact: str):
    """Save one short fact. Only called when the user explicitly asks to remember something."""
    text = " ".join(str(fact or "").split())
    if not text:
        return {"error": "I need to know what to remember."}
    if len(text) > MAX_FACT_LENGTH:
        return {
            "error": f"That is too long to remember (over {MAX_FACT_LENGTH} characters). "
                     "Ask the user to shorten it to one short fact."
        }
    if SENSITIVE_WORDS.search(text) or SENSITIVE_SHAPES.search(text):
        return {
            "error": "I do not store passwords, PINs, keys, codes, or card and account numbers. "
                     "Tell the user this was NOT saved."
        }

    conn = get_connection()
    existing = conn.execute(
        "SELECT * FROM memories WHERE lower(fact) = ?", (text.lower(),)
    ).fetchone()
    if existing:
        conn.close()
        result = _row_to_dict(existing)
        result["note"] = "This was already remembered."
        return result

    cursor = conn.execute(
        "INSERT INTO memories (fact, created_at) VALUES (?, ?)",
        (text, datetime.now().strftime(TIME_FORMAT)),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def list_memories():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM memories ORDER BY id").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def forget_memory(memory_id=None, fact=None):
    rows = _find_memories(memory_id, fact)
    if not rows:
        return False
    if len(rows) > 1:
        return {
            "error": "More than one remembered fact matches. Ask the user which one they mean.",
            "matches": [_row_to_dict(r) for r in rows],
        }

    conn = get_connection()
    conn.execute("DELETE FROM memories WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    conn.close()
    return True


# --- Used by the agent (NOT a tool the model can call) ---

def get_remembered_facts():
    """The most recent facts, oldest first, for the agent to show the model."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT fact FROM memories ORDER BY id DESC LIMIT ?", (MAX_IN_PROMPT,)
    ).fetchall()
    conn.close()
    return [r["fact"] for r in reversed(rows)]


# --- Tool Manifest ---
# Read by agent.py to build the prompt and the function map.

TOOL_MANIFEST = [
    {
        "name": "remember_fact",
        "description": "Remember one short fact about the user or their life for future chats. Use ONLY when the user explicitly asks you to remember or note something",
        "args": {
            "fact": "string, one short fact written as a plain statement (for example 'Rahul is my project partner')",
        },
        "function": remember_fact,
    },
    {
        "name": "list_memories",
        "description": "List everything you have been asked to remember",
        "args": {},
        "function": list_memories,
    },
    {
        "name": "forget_memory",
        "description": "Forget one remembered fact",
        "args": {
            "memory_id": "integer, only if the ID is known",
            "fact": "string, words from the remembered fact (use when the ID is not known)",
        },
        "function": forget_memory,
    },
]