import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime

# Customer accounts live in their own database, apart from any customer's data
ACCOUNTS_DB_PATH = os.path.join(os.path.dirname(__file__), "accounts.db")

HASH_NAME = "pbkdf2_sha256"
ITERATIONS = 600_000
MIN_PASSWORD = 10
MAX_PASSWORD = 128
MAX_EMAIL = 254
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

_dummy = None


def _connect():
    conn = sqlite3.connect(ACCOUNTS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def _clean_email(email):
    """Trimmed, lowercase email, or None if it is not a valid address."""
    text = str(email or "").strip().lower()
    if len(text) > MAX_EMAIL or not EMAIL_PATTERN.fullmatch(text):
        return None
    return text


def _hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_NAME}${iterations}${salt.hex()}${digest.hex()}"


def _check_password(password, stored):
    try:
        name, iterations, salt_hex, digest_hex = stored.split("$")
        if name != HASH_NAME:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def _dummy_hash():
    """A hash to check against when the email is unknown, so timing gives nothing away."""
    global _dummy
    if _dummy is None:
        _dummy = _hash_password("not-a-real-password")
    return _dummy


def create_account(email, password):
    """Returns {"id", "email"} on success, or {"error": "..."}."""
    clean = _clean_email(email)
    if clean is None:
        return {"error": "That is not a valid email address."}
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        return {"error": f"The password must be at least {MIN_PASSWORD} characters."}
    if len(password) > MAX_PASSWORD:
        return {"error": f"The password must be at most {MAX_PASSWORD} characters."}
    if password.strip().lower() == clean:
        return {"error": "The password cannot be your email address."}

    password_hash = _hash_password(password)
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO accounts (email, password_hash, created_at) VALUES (?, ?, ?)",
            (clean, password_hash, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "email": clean}
    except sqlite3.IntegrityError:
        return {"error": "An account with this email already exists."}
    finally:
        conn.close()


def verify_login(email, password):
    """Returns {"id", "email"} if the login is right, otherwise None.
    It never says whether the email exists."""
    clean = _clean_email(email)
    if clean is None or not isinstance(password, str) or len(password) > MAX_PASSWORD:
        return None

    conn = _connect()
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (clean,)).fetchone()
    conn.close()

    if row is None:
        _check_password(password, _dummy_hash())
        return None
    if _check_password(password, row["password_hash"]):
        return {"id": row["id"], "email": row["email"]}
    return None


def get_account(account_id):
    """The public details of one account (never the password hash), or None."""
    conn = _connect()
    row = conn.execute(
        "SELECT id, email, created_at FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None