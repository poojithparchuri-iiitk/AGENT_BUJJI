import base64
import hashlib
import hmac
import json
import os
import threading
import time

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

TOKEN_DAYS = 7
MIN_SECRET_LENGTH = 32
MAX_TOKEN_LENGTH = 1000

LOGIN_WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 20


def _secret():
    value = os.environ.get("BUJJI_TOKEN", "")
    if len(value) < MIN_SECRET_LENGTH:
        raise RuntimeError("BUJJI_TOKEN is missing or too short in the .env file.")
    return value.encode("utf-8")


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload_b64):
    digest = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64(digest)


def make_token(account_id, now=None, days=TOKEN_DAYS):
    """A signed token for one account. It stops working after `days` days."""
    now = int(now if now is not None else time.time())
    payload = {"sub": int(account_id), "iat": now, "exp": now + int(days * 86400)}
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return payload_b64 + "." + _sign(payload_b64)


def read_token(token, now=None):
    """The account id if the token is genuine and not expired, otherwise None.
    It never raises: any problem means 'not logged in'."""
    try:
        if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
            return None
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, signature = parts
        if not hmac.compare_digest(signature, _sign(payload_b64)):
            return None
        payload = json.loads(_unb64(payload_b64))
        if not isinstance(payload, dict):
            return None
        sub = payload.get("sub")
        exp = payload.get("exp")
        for value in (sub, exp):
            if isinstance(value, bool) or not isinstance(value, int):
                return None
        now = int(now if now is not None else time.time())
        if exp <= now:
            return None
        return sub
    except Exception:
        return None


# ---- Limit on failed logins (kept in memory: a restart clears it) ----

_failures = {}
_lock = threading.Lock()


def _clean_email(email):
    return str(email or "").strip().lower()[:254]


def _recent(key, now):
    times = _failures.get(key)
    if not times:
        return 0
    times[:] = [t for t in times if now - t <= LOGIN_WINDOW_SECONDS]
    if not times:
        del _failures[key]
        return 0
    return len(times)


def _sweep(now):
    """Forget every entry whose failures are all older than the window,
    so the list cannot grow without limit."""
    for key in list(_failures):
        _recent(key, now)


def login_allowed(email, ip, now=None):
    """False if this email or this IP address has failed too many times lately."""
    now = now if now is not None else time.time()
    with _lock:
        return (
            _recent("email:" + _clean_email(email), now) < MAX_FAILURES_PER_EMAIL
            and _recent("ip:" + str(ip), now) < MAX_FAILURES_PER_IP
        )


def record_failure(email, ip, now=None):
    now = now if now is not None else time.time()
    with _lock:
        _sweep(now)
        for key in ("email:" + _clean_email(email), "ip:" + str(ip)):
            _failures.setdefault(key, []).append(now)


def clear_failures(email):
    """After a successful login, forget that email's failures."""
    with _lock:
        _failures.pop("email:" + _clean_email(email), None)