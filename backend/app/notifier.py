import threading
import time
from win11toast import toast

from tools.reminders import get_due_reminders, mark_fired

# How often the backend looks for due reminders
CHECK_EVERY_SECONDS = 15

_started = False


def _show_toast(text, remind_at):
    """Show one Windows notification. Runs in its own thread, so a toast that
    stays on screen can never block the reminder checker."""
    try:
        toast("Reminder", f"{text}  ({remind_at})", duration="long")
    except Exception as e:
        print(f"[NOTIFIER] could not show notification: {e}")


def check_once():
    """Find due reminders, show a notification for each, and mark them as fired."""
    due = get_due_reminders()
    for r in due:
        threading.Thread(
            target=_show_toast, args=(r["text"], r["remind_at"]), daemon=True
        ).start()
    mark_fired([r["id"] for r in due])
    return due


def _loop():
    while True:
        try:
            check_once()
        except Exception as e:
            print(f"[NOTIFIER] check failed: {e}")
        time.sleep(CHECK_EVERY_SECONDS)


def start_watcher():
    """Start the background checker (only once)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True).start()
    print("[NOTIFIER] reminder watcher started")