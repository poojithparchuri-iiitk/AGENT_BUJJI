import contextlib
import contextvars
import os
import re
import sqlite3
import threading

BASE_DIR = os.path.dirname(__file__)

# The owner's original data (no account): the same bujji.db as before
DB_PATH = os.path.join(BASE_DIR, "bujji.db")
# Each customer gets their own database file in this folder
CUSTOMERS_DIR = os.path.join(BASE_DIR, "customers")

# Which customer the current request uses. None means the owner's original database.
_current = contextvars.ContextVar("bujji_customer", default=None)

# Every table, so every database has the same tables
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        due_date TEXT,
        completed INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        remind_at TEXT NOT NULL,
        fired INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        done_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL
    )
    """,
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
    """,
    """
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]

_ready = set()  # database files whose tables already exist
_lock = threading.Lock()


def _ensure_schema(path):
    """Create any missing tables in this database file, once per run.
    CREATE TABLE IF NOT EXISTS never touches existing data."""
    if path in _ready:
        return
    with _lock:
        if path in _ready:
            return
        conn = sqlite3.connect(path)
        for statement in SCHEMA:
            conn.execute(statement)
        conn.commit()
        conn.close()
        _ready.add(path)


def _valid_id(account_id):
    return (
        isinstance(account_id, int)
        and not isinstance(account_id, bool)
        and account_id > 0
    )


def customer_db_path(account_id):
    if not _valid_id(account_id):
        raise ValueError("Invalid customer id")
    return os.path.join(CUSTOMERS_DIR, f"customer_{account_id}.db")


def customer_exists(account_id):
    return _valid_id(account_id) and os.path.isfile(customer_db_path(account_id))


def ensure_customer_db(account_id):
    """Create this customer's database with empty tables if it is not there yet.
    Safe to call again: it never touches existing data."""
    path = customer_db_path(account_id)
    os.makedirs(CUSTOMERS_DIR, exist_ok=True)
    _ensure_schema(path)
    return path


def list_customer_ids():
    ids = []
    if os.path.isdir(CUSTOMERS_DIR):
        for name in os.listdir(CUSTOMERS_DIR):
            match = re.fullmatch(r"customer_([1-9][0-9]*)\.db", name)
            if match:
                ids.append(int(match.group(1)))
    return sorted(ids)


def current_customer():
    return _current.get()


def set_customer(account_id):
    """Switch to a customer (or None for the owner's database). Returns a token for
    reset_customer. A bad id or a customer with no database is refused."""
    if account_id is not None:
        if not _valid_id(account_id):
            raise ValueError("Invalid customer id")
        if not customer_exists(account_id):
            raise ValueError("Unknown customer")
    return _current.set(account_id)


def reset_customer(token):
    _current.reset(token)


@contextlib.contextmanager
def use_customer(account_id):
    """Use one customer's data inside a 'with' block, then switch back."""
    token = set_customer(account_id)
    try:
        yield
    finally:
        reset_customer(token)


def get_connection():
    account_id = _current.get()
    if account_id is None:
        path = DB_PATH
    else:
        if not customer_exists(account_id):
            raise ValueError("Unknown customer")
        path = customer_db_path(account_id)
    _ensure_schema(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Kept for the tool files that call it when they load."""
    get_connection().close()