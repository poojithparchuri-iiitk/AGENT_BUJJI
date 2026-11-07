import re

# Words that add a day or a time of day to a message. If a draft says one of them
# and the user never did, the model probably invented it.
# "may" and "march" are left out on purpose, because they are common ordinary words.
TIME_WORDS = [
    "tonight", "today", "tomorrow", "yesterday",
    "morning", "afternoon", "evening", "night", "noon", "midnight",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "april", "june", "july", "august",
    "september", "october", "november", "december",
]

# Clock times such as "4 PM", "4:30pm" or "17:30"
CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b|\b\d{1,2}:\d{2}\b", re.IGNORECASE)


def _words(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def _clock_times(text):
    """Map each clock time (spaces removed) to the way it was written."""
    return {
        re.sub(r"\s+", "", m.group(0).lower()): m.group(0).lower()
        for m in CLOCK.finditer(text)
    }


def find_invented_details(user_text, subject, body):
    """Return the days, times of day and clock times that appear in the draft
    but not in what the user said."""
    said_words = _words(user_text)
    draft_text = f"{subject} {body}"
    draft_words = _words(draft_text)

    found = [w for w in TIME_WORDS if w in draft_words and w not in said_words]

    said_clock = _clock_times(user_text)
    for key, shown in _clock_times(draft_text).items():
        if key not in said_clock:
            found.append(shown)
    return found