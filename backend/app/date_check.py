import re
from datetime import date, datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Arguments that hold a date or a date and time
DATE_ARGS = (
    "due_date", "new_due_date", "start_time", "end_time",
    "new_start_time", "new_end_time", "remind_at", "done_at", "date",
)

# Phrases that cannot be turned into one exact date. If the user used one,
# the check stays silent instead of guessing.
UNCLEAR = re.compile(
    r"\bin \d+ (?:days?|weeks?|months?)\b"
    r"|\b(?:next|this|last) (?:week|month|weekend)\b"
    r"|\bweekend\b|\bday after\b|\bend of\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b"
    r"|\b\d{1,2}[/-]\d{1,2}\b"
    r"|\b(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b",
    re.IGNORECASE,
)

# A time of day the user actually gave: "4 PM", "16:30", "at 8", "noon", "in 10 minutes"
TIME_GIVEN = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s?(?:a\.?m\.?|p\.?m\.?)(?![a-z])"
    r"|\b\d{1,2}:\d{2}\b"
    r"|(?:\bat|@)\s*\d{1,2}\b"
    r"|\b\d{1,2}\s?o['\u2019]?clock\b"
    r"|\b(?:noon|midnight|midday)\b"
    r"|\bin\s+(?:\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen"
    r"|twenty|thirty|forty|half(?: an)?)\s+(?:minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)

# A delay such as "in 10 minutes" or "in an hour"
DELAY = re.compile(
    r"\bin\s+(?:\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten|fifteen"
    r"|twenty|thirty|forty|half(?: an)?)\s+(?:minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)

# "next Monday" or "last Friday" is ambiguous, so the weekday repair stays out of it
RELATIVE_WEEKDAY = re.compile(
    r"\b(?:next|last|previous|coming)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def has_time_of_day(text):
    """True if the text gives a time of day (a clock time, noon or midnight,
    or a delay such as 'in 10 minutes'). Words like 'morning' or 'tonight' do not count."""
    return bool(TIME_GIVEN.search(str(text or "")))


def _references(text, today):
    """The days the user named (today, tomorrow, Monday...) and every date they could mean."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    labels, ok = [], set()

    for word, offset in (("today", 0), ("tonight", 0), ("tomorrow", 1), ("yesterday", -1)):
        if word in words:
            labels.append(word)
            ok.add(today + timedelta(days=offset))

    for index, name in enumerate(WEEKDAYS):
        if name in words:
            labels.append(name.capitalize())
            # A weekday name can mean the last, the next, or the one after that
            for offset in range(-7, 15):
                day = today + timedelta(days=offset)
                if day.weekday() == index:
                    ok.add(day)

    return labels, ok


def find_date_mismatches(said_text, results, today=None):
    """Compare the dates used in tool calls with the days the user named.
    Returns a list of short notes, one for each date that does not match."""
    today = today or date.today()
    text = str(said_text or "")

    if UNCLEAR.search(text):
        return []
    labels, ok = _references(text, today)
    if not ok:
        return []

    problems = []
    for r in results:
        result = r.get("result")
        # Skip calls that failed or changed nothing
        if result is None or result is False or (isinstance(result, dict) and "error" in result):
            continue
        args = r.get("args")
        if not isinstance(args, dict):
            continue

        for name in DATE_ARGS:
            match = re.match(r"\s*(\d{4}-\d{2}-\d{2})", str(args.get(name) or ""))
            if not match:
                continue
            try:
                chosen = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue

            # Today is always accepted: "at 6 PM" with no day, or "in 10 minutes", means today
            if chosen == today or chosen in ok:
                continue

            note = f"{chosen.strftime('%A %Y-%m-%d')} was used, but you said {' and '.join(labels)}"
            if note not in problems:
                problems.append(note)

    return problems


def _single_weekday(text):
    """The weekday the message names, if it names exactly one and nothing else that
    points at a date. Otherwise None."""
    if UNCLEAR.search(text) or RELATIVE_WEEKDAY.search(text) or DELAY.search(text):
        return None
    words = set(re.findall(r"[a-z]+", text.lower()))
    if words & {"today", "tonight", "tomorrow", "yesterday"}:
        return None
    named = [i for i, name in enumerate(WEEKDAYS) if name in words]
    return named[0] if len(named) == 1 else None


def _nearest(today, weekday_index, look_back):
    """That weekday's date: the most recent one up to today (look_back),
    or the next one after today."""
    offsets = range(0, -7, -1) if look_back else range(1, 8)
    for offset in offsets:
        day = today + timedelta(days=offset)
        if day.weekday() == weekday_index:
            return day


def repair_weekday_dates(user_message, tool_name, args, today=None):
    """If the user named exactly one weekday and a date in this tool call falls on a
    different weekday, move that date to the named weekday (the time of day is kept).
    Returns (args, notes). Anything unclear is left alone."""
    today = today or date.today()
    if not isinstance(args, dict):
        return args, []
    index = _single_weekday(str(user_message or ""))
    if index is None:
        return args, []

    fixed = dict(args)
    notes = []
    for name in DATE_ARGS:
        value = str(fixed.get(name) or "")
        match = re.match(r"(\s*)(\d{4}-\d{2}-\d{2})(.*)$", value, re.DOTALL)
        if not match:
            continue
        try:
            chosen = datetime.strptime(match.group(2), "%Y-%m-%d").date()
        except ValueError:
            continue
        if chosen.weekday() == index:
            continue

        # Something already done points back in time; a plan points forward
        look_back = name == "done_at" or tool_name == "list_activities"
        target = _nearest(today, index, look_back)
        fixed[name] = match.group(1) + target.strftime("%Y-%m-%d") + match.group(3)

        note = (
            f"Date fixed: {chosen.strftime('%A %Y-%m-%d')} was picked, but you said "
            f"{WEEKDAYS[index].capitalize()}, so I used {target.strftime('%A %Y-%m-%d')}."
        )
        if note not in notes:
            notes.append(note)
    return fixed, notes