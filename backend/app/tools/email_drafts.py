import re
from database import get_connection
from mailer import send_email

# Words ignored when matching a contact by name
STOP_WORDS = {"the", "a", "an", "my", "to", "of"}

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _one_line(text):
    """Collapse line breaks and repeated spaces into single spaces."""
    return " ".join(str(text or "").split())


def _init_tables():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            to_name TEXT,
            to_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT
        )
        """
    )
    conn.commit()
    conn.close()


_init_tables()


def _valid_email(address):
    return bool(EMAIL_PATTERN.fullmatch(str(address).strip()))


def _contact_to_dict(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def _draft_to_dict(row):
    return {
        "id": row["id"],
        "to_name": row["to_name"],
        "to_email": row["to_email"],
        "subject": row["subject"],
        "body": row["body"],
        "status": row["status"],
    }


def _find_contacts(contact_id=None, name=None):
    """Find contacts by ID, or by words from the name. Returns a list of rows."""
    ref = contact_id if contact_id is not None else name
    if ref is None:
        return []
    text = str(ref).strip()

    conn = get_connection()
    if text.isdigit():
        rows = conn.execute("SELECT * FROM contacts WHERE id = ?", (int(text),)).fetchall()
    else:
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]
        all_rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
        rows = [r for r in all_rows if words and all(w in r["name"].lower() for w in words)]
    conn.close()
    return rows


def save_contact(name: str, email: str):
    """Save a person's email address. Saving the same name again updates the address."""
    name = _one_line(name)
    email = str(email).strip()
    if not name:
        return {"error": "I need a name for this contact."}
    if not _valid_email(email):
        return {"error": f"'{email}' is not a valid email address."}

    conn = get_connection()
    existing = conn.execute(
        "SELECT * FROM contacts WHERE lower(name) = ?", (name.lower(),)
    ).fetchone()
    if existing:
        conn.execute("UPDATE contacts SET email = ? WHERE id = ?", (email, existing["id"]))
        contact_id = existing["id"]
    else:
        cursor = conn.execute("INSERT INTO contacts (name, email) VALUES (?, ?)", (name, email))
        contact_id = cursor.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    conn.close()
    return _contact_to_dict(row)


def list_contacts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    conn.close()
    return [_contact_to_dict(r) for r in rows]


def delete_contact(contact_id=None, name=None):
    rows = _find_contacts(contact_id, name)
    if not rows:
        return False
    if len(rows) > 1:
        return {
            "error": "More than one contact matches. Ask the user which one they mean.",
            "matches": [_contact_to_dict(r) for r in rows],
        }

    conn = get_connection()
    conn.execute("DELETE FROM contacts WHERE id = ?", (rows[0]["id"],))
    conn.commit()
    conn.close()
    return True


def _resolve_recipient(to):
    """Turn a name or an address into (to_name, to_email), or return an error dict."""
    text = str(to).strip()
    if not text:
        return {"error": "I need to know who the email is for."}

    if "@" in text:
        if not _valid_email(text):
            return {"error": f"'{text}' is not a valid email address."}
        return (None, text)

    rows = _find_contacts(name=text)
    if not rows:
        return {
            "error": f"I do not have an email address saved for '{text}'. "
                     "Ask the user for the address, and offer to save it as a contact."
        }
    if len(rows) > 1:
        return {
            "error": "More than one contact matches. Ask the user which one they mean.",
            "matches": [_contact_to_dict(r) for r in rows],
        }
    return (rows[0]["name"], rows[0]["email"])


def draft_email(to: str, subject: str, body: str):
    """Write an email DRAFT. This NEVER sends anything."""
    subject = _one_line(subject)  # a subject is always one line
    body = str(body or "").strip()
    if not subject or not body:
        return {"error": "An email needs both a subject and a body."}

    recipient = _resolve_recipient(to)
    if isinstance(recipient, dict):
        return recipient
    to_name, to_email = recipient

    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO email_drafts (to_name, to_email, subject, body) VALUES (?, ?, ?, ?)",
        (to_name, to_email, subject, body),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM email_drafts WHERE id = ?", (cursor.lastrowid,)).fetchone()
    conn.close()

    result = _draft_to_dict(row)
    result["note"] = (
        "This is only a DRAFT. It has NOT been sent. "
        "The user must click the Send email button under the chat to send it."
    )
    return result


# --- Used by the backend (NOT tools the model can call) ---

def get_pending_drafts():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM email_drafts WHERE status = 'pending' ORDER BY id"
    ).fetchall()
    conn.close()
    return [_draft_to_dict(r) for r in rows]


def send_draft(draft_id):
    """Send one pending draft. Called only when the user clicks Send email."""
    conn = get_connection()
    # Claim the draft first, so a double click can never send it twice
    cursor = conn.execute(
        "UPDATE email_drafts SET status = 'sending' WHERE id = ? AND status = 'pending'",
        (draft_id,),
    )
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return {"ok": False, "error": "This draft was already sent or discarded, or it does not exist."}
    row = conn.execute("SELECT * FROM email_drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()

    # Whatever happens while sending, the draft must end up either sent or back to pending
    try:
        result = send_email(row["to_email"], row["subject"], row["body"])
    except Exception as e:
        result = {"ok": False, "error": f"Could not send: {e}"}

    conn = get_connection()
    if result.get("ok"):
        conn.execute(
            "UPDATE email_drafts SET status = 'sent', last_error = NULL WHERE id = ?", (draft_id,)
        )
    else:
        # Not sent: put it back so the user can try again
        conn.execute(
            "UPDATE email_drafts SET status = 'pending', last_error = ? WHERE id = ?",
            (result.get("error"), draft_id),
        )
    conn.commit()
    conn.close()
    return result


def discard_draft(draft_id):
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE email_drafts SET status = 'discarded' WHERE id = ? AND status = 'pending'",
        (draft_id,),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


# --- Tool Manifest ---
# Read by agent.py to build the prompt and the function map.
# send_draft and discard_draft are deliberately NOT here: the model can never send.

TOOL_MANIFEST = [
    {
        "name": "save_contact",
        "description": "Save a person's email address so emails can be addressed to them by name",
        "args": {
            "name": "string, the person's name",
            "email": "string, their email address",
        },
        "function": save_contact,
    },
    {
        "name": "list_contacts",
        "description": "List all saved contacts",
        "args": {},
        "function": list_contacts,
    },
    {
        "name": "delete_contact",
        "description": "Delete one saved contact",
        "args": {
            "contact_id": "integer, only if the ID is known",
            "name": "string, words from the contact's name (use when the ID is not known)",
        },
        "function": delete_contact,
    },
    {
        "name": "draft_email",
        "description": "Write an email DRAFT for the user to review. This does NOT send anything; the user sends it with a button",
        "args": {
            "to": "string, a saved contact's name or a full email address",
            "subject": "string, the email subject",
            "body": "string, the full email text, with a greeting and a sign-off",
        },
        "function": draft_email,
    },
]