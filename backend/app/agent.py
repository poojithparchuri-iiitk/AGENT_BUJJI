import os, json, re
from datetime import date, datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv

from tools.tasks import TOOL_MANIFEST as TASKS_MANIFEST
from tools.schedule import TOOL_MANIFEST as SCHEDULE_MANIFEST
from tools.reminders import TOOL_MANIFEST as REMINDERS_MANIFEST
from tools.activity import TOOL_MANIFEST as ACTIVITY_MANIFEST
from tools.email_drafts import TOOL_MANIFEST as EMAIL_MANIFEST
from draft_check import find_invented_details

load_dotenv()

endpoint = os.getenv("AZURE_PHI4_ENDPOINT")
api_key = os.getenv("AZURE_PHI4_API_KEY")

# Optional: your full name, used to sign emails (add USER_NAME=... to .env)
USER_NAME = (os.getenv("USER_NAME") or "").strip()

client = OpenAI(
    base_url=endpoint,
    api_key=api_key,
)

# Set to False to silence the [DEBUG] lines in the backend terminal
DEBUG = True

# Combine manifests from all tool files here.
# When you add a new tool file later, import its manifest and add it to this list.
ALL_TOOLS = (
    TASKS_MANIFEST
    + SCHEDULE_MANIFEST
    + REMINDERS_MANIFEST
    + ACTIVITY_MANIFEST
    + EMAIL_MANIFEST
)

# Lookup: tool name -> actual Python function
AVAILABLE_FUNCTIONS = {tool["name"]: tool["function"] for tool in ALL_TOOLS}

# How many previous messages Bujji can "remember" in one chat
MAX_HISTORY = 6
# Long earlier replies are cut to this many characters
MAX_HISTORY_CHARS = 400
# Most tool calls Bujji may run for a single user message
MAX_TOOL_CALLS = 5

# Phrases that claim an action was done. If the model writes one of these in a
# plain-text reply WITHOUT having run a tool, the claim is fake.
CLAIM_PATTERN = re.compile(
    r"\b(has been|have been|successfully"
    r"|i['\u2019]ve (added|deleted|removed|marked|scheduled|moved|renamed|cleared|updated|set|logged|recorded|saved|sent|emailed)"
    r"|i have (added|deleted|removed|marked|scheduled|moved|renamed|cleared|updated|set|logged|recorded|saved|sent|emailed))\b",
    re.IGNORECASE,
)


def _log(label, value):
    """Print a debug line to the backend terminal (only when DEBUG is True)."""
    if DEBUG:
        print(f"[DEBUG] {label}: {str(value)[:300]}")


def _date_context():
    """Right now (date and time) plus the last 7 and next 8 days, so the model can
    convert words like 'yesterday', 'tomorrow', 'this Friday' or '4 PM' into real values."""
    now = datetime.now()
    today = date.today()
    lines = []
    for i in range(-7, 9):
        day = today + timedelta(days=i)
        label = ""
        if i == -1:
            label = " (yesterday)"
        elif i == 0:
            label = " (today)"
        elif i == 1:
            label = " (tomorrow)"
        lines.append(f"- {day.strftime('%A %Y-%m-%d')}{label}")
    return now.strftime("%A, %Y-%m-%d, %H:%M"), "\n".join(lines)


def _clean_history(history):
    """Keep only the last few valid user/assistant messages."""
    if not history:
        return []
    cleaned = []
    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content})
    return cleaned[-MAX_HISTORY:]


def _format_history(recent):
    """Turn earlier messages into a plain transcript for the system prompt."""
    if not recent:
        return "(none)"
    lines = []
    for item in recent:
        who = "User" if item["role"] == "user" else "Bujji"
        lines.append(f"{who}: {item['content'][:MAX_HISTORY_CHARS]}")
    return "\n".join(lines)


def _build_system_prompt(recent):
    # Each tool gets its own block, and each argument gets its own line,
    # so commas inside a description can never be mistaken for argument names.
    tool_descriptions = ""
    for tool in ALL_TOOLS:
        tool_descriptions += f"\nTOOL: {tool['name']}\n"
        tool_descriptions += f"  What it does: {tool['description']}\n"
        if tool["args"]:
            tool_descriptions += "  Arguments (use these EXACT names):\n"
            for arg_name, arg_desc in tool["args"].items():
                tool_descriptions += f"    * {arg_name} = {arg_desc}\n"
        else:
            tool_descriptions += "  Arguments: none\n"

    now_text, calendar_text = _date_context()
    history_text = _format_history(recent)

    # How emails are signed (the \\n below is a literal backslash-n, as it appears in JSON)
    if USER_NAME:
        sign_off_rule = f'end with "Best regards," on one line and then {USER_NAME} on the next line'
        sign_off_json = f"Best regards,\\n{USER_NAME}"
    else:
        sign_off_rule = 'end with "Best regards" and nothing after it'
        sign_off_json = "Best regards"

    return f"""You are Agent Bujji, a personal AI assistant with access to real tools. You do NOT pretend to use tools - you MUST actually call them.

Right now it is {now_text} (24-hour clock).
Calendar (the last 7 days and the next 8 days):
{calendar_text}

Available tools:
{tool_descriptions}

RULES:
1. If the user's request matches a tool's purpose, respond with ONLY JSON tool calls, nothing else - no explanation, no extra text.
2. Format of one call: {{"tool": "<function_name>", "args": {{}}}}
3. If the user asks for several things in one message, output one JSON tool call per request, each on its own line, in the order they were asked (at most 5).
4. Only use tool names from the list above. NEVER invent a tool name.
5. In "args", use ONLY the exact argument names listed for that tool. Never invent or rename arguments. Leave out any optional argument you do not need.
6. If the user asks for something that NO tool above can do (for example checking the weather), reply in plain text: say clearly that you cannot do that yet, and mention what you CAN do with your tools.
7. NEVER say that something was added, deleted, changed, scheduled, set, logged, saved or sent unless a tool actually ran. You cannot change anything without a tool call.
8. Plain text is also fine for normal conversation and greetings. Keep replies short and do not use emojis.
9. DATES AND TIMES: convert the user's words into numbers using the calendar above. If the user gives a date only, pass YYYY-MM-DD. If the user gives a time too, pass YYYY-MM-DD HH:MM using the 24-hour clock (4 PM becomes 16:00, 9 AM becomes 09:00, noon is 12:00). For "in 30 minutes" or "in 2 hours", add that amount to the current time shown above and pass the result. Never pass dates or times as words. If the user gives no date, leave the date argument out.
10. The RECENT CONVERSATION block at the end is for context only, to understand words like "it" or "that task". Those earlier Bujji replies were written AFTER a tool had already run. Do NOT copy their style. Your answer to the NEWEST user message must follow rules 1 to 9: a request that needs a tool is answered with ONLY the JSON tool call(s).
11. Do NOT ask the user for confirmation before doing something they clearly asked for, such as marking a task done. Call the tool right away. Only ask a question if a tool result says more than one item matches.
12. TASKS, EVENTS, REMINDERS and ACTIVITIES: a TASK is something still to get done (submit the report, buy milk), possibly with a deadline. An EVENT is something that happens at a specific time (a meeting, a class, an appointment, a call). A REMINDER is an alert at a specific time ("remind me to ..."). An ACTIVITY is something the user has ALREADY done ("I finished my SQL assignment", "I went for a run", "I studied for two hours"): use log_activity. When the user says "mark ... as done" or "complete the ... task", that is complete_task, NOT log_activity. Never log something in the future as an activity. If the user wants an event or a reminder but gave no time, ask them for the time in plain text.
13. EMAIL: you can only WRITE email drafts with draft_email. You can NEVER send an email: the user sends it with the Send email button under the chat. "Send an email to X" or "email X" means call draft_email. Write the body yourself from what the user wants to say: a short greeting with the person's name, the message, then {sign_off_rule}. Use ONLY facts the user gave: never add dates, times, places or other details they did not mention, in the subject or the body. NEVER write placeholders like [Your Name]. Use save_contact when the user tells you someone's email address. If the user says "send it", "yes send" or "go ahead" about a draft that already exists, do NOT call draft_email again: reply in plain text that you cannot send emails yourself and that they should click the Send email button on the draft. NEVER say that an email was sent.

EXAMPLES:
User: "rename the dentist task to book dentist appointment"
You: {{"tool": "edit_task", "args": {{"title": "dentist", "new_title": "book dentist appointment"}}}}
User: "add a task: submit report at 4 PM tomorrow"
You: {{"tool": "add_task", "args": {{"title": "submit report", "due_date": "<tomorrow's date from the calendar> 16:00"}}}}
User: "I have a project meeting tomorrow at 4 PM"
You: {{"tool": "add_event", "args": {{"title": "project meeting", "start_time": "<tomorrow's date from the calendar> 16:00"}}}}
User: "what is on my schedule tomorrow"
You: {{"tool": "list_events", "args": {{"date": "<tomorrow's date from the calendar>"}}}}
User: "remind me to call mom at 6 PM tomorrow"
You: {{"tool": "add_reminder", "args": {{"text": "call mom", "remind_at": "<tomorrow's date from the calendar> 18:00"}}}}
User: "remind me to stretch in 10 minutes"
You: {{"tool": "add_reminder", "args": {{"text": "stretch", "remind_at": "<today's date> <current time plus 10 minutes>"}}}}
User: "what reminders do I have"
You: {{"tool": "list_reminders", "args": {{}}}}
User: "I finished my SQL assignment"
You: {{"tool": "log_activity", "args": {{"description": "finished my SQL assignment"}}}}
User: "I went for a run yesterday at 6 PM"
You: {{"tool": "log_activity", "args": {{"description": "went for a run", "done_at": "<yesterday's date from the calendar> 18:00"}}}}
User: "what did I accomplish today"
You: {{"tool": "list_activities", "args": {{}}}}
User: "what did I do yesterday"
You: {{"tool": "list_activities", "args": {{"date": "<yesterday's date from the calendar>"}}}}
User: "save Rahul's email as rahul@example.com"
You: {{"tool": "save_contact", "args": {{"name": "Rahul", "email": "rahul@example.com"}}}}
User: "who is in my contacts"
You: {{"tool": "list_contacts", "args": {{}}}}
User: "email Rahul that I will submit the report tomorrow"
You: {{"tool": "draft_email", "args": {{"to": "Rahul", "subject": "Report submission tomorrow", "body": "Hi Rahul,\\n\\nI wanted to let you know that I will submit the report tomorrow.\\n\\n{sign_off_json}"}}}}
User: "mark the milk task as done and show my schedule tomorrow"
You:
{{"tool": "complete_task", "args": {{"title": "milk"}}}}
{{"tool": "list_events", "args": {{"date": "<tomorrow's date from the calendar>"}}}}
User: "I have a design review tomorrow at 2 PM, add it to my schedule and email Rahul about it"
You:
{{"tool": "add_event", "args": {{"title": "design review", "start_time": "<tomorrow's date from the calendar> 14:00"}}}}
{{"tool": "draft_email", "args": {{"to": "Rahul", "subject": "Design review tomorrow at 2 PM", "body": "Hi Rahul,\\n\\nI have a design review tomorrow at 2 PM and wanted to let you know.\\n\\n{sign_off_json}"}}}}

RECENT CONVERSATION (context only):
{history_text}
"""


def _parse_tool_calls(reply: str):
    """Find EVERY JSON object in the reply that looks like a tool call."""
    decoder = json.JSONDecoder()
    calls = []
    i = 0
    while i < len(reply):
        if reply[i] == "{":
            try:
                obj, end = decoder.raw_decode(reply, i)
                if isinstance(obj, dict) and "tool" in obj:
                    calls.append(obj)
                i = end
                continue
            except json.JSONDecodeError:
                pass
        i += 1
    return calls


def _ask(messages):
    response = client.chat.completions.create(
        model="Phi-4",
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def _run_calls(calls):
    """Run each tool call in order and collect what every tool returned."""
    results = []
    for call in calls[:MAX_TOOL_CALLS]:
        name = call.get("tool")
        args = call.get("args", {})
        if not isinstance(args, dict):
            args = {}
        func = AVAILABLE_FUNCTIONS.get(name)
        _log("tool call", f"{name} {args}")

        if func is None:
            results.append({"tool": name, "result": {"error": "There is no such tool."}})
            continue
        try:
            result = func(**args)
        except Exception as e:
            result = {"error": f"The tool failed: {e}"}
        _log("tool result", result)
        results.append({"tool": name, "args": args, "result": result})
    return results


def _draft_created(results):
    """True if an email draft was really created in this turn."""
    return any(
        r.get("tool") == "draft_email"
        and isinstance(r.get("result"), dict)
        and "error" not in r["result"]
        for r in results
    )


def _draft_warnings(results, said_text):
    """Days and times in a draft that the user never mentioned."""
    warnings = []
    for r in results:
        res = r.get("result")
        if r.get("tool") == "draft_email" and isinstance(res, dict) and "error" not in res:
            for item in find_invented_details(said_text, res.get("subject", ""), res.get("body", "")):
                if item not in warnings:
                    warnings.append(item)
    return warnings


def run_agent(user_message: str, history=None) -> str:
    recent = _clean_history(history)
    _log("---- new message", user_message)

    messages = [
        {"role": "system", "content": _build_system_prompt(recent)},
        {"role": "user", "content": user_message},
    ]

    reply = _ask(messages)
    _log("model reply 1", reply)
    calls = _parse_tool_calls(reply)

    # Safety net: a plain-text reply that CLAIMS an action, with no tool run, is fake.
    if not calls and CLAIM_PATTERN.search(reply):
        _log("safety net", "fake claim detected, retrying once")
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": (
                "No tool was run, so nothing has been done yet. Answer my request again "
                "with ONLY the JSON tool call(s). If a needed detail (like the time) is "
                "missing, ask me for it instead of claiming it is done."
            )},
        ]
        reply = _ask(retry_messages)
        _log("model reply 2 (retry)", reply)
        calls = _parse_tool_calls(reply)
        if not calls and CLAIM_PATTERN.search(reply):
            return "I could not complete that, so nothing was changed. Please try rephrasing your request."

    # Plain text reply (no tool requested)
    if not calls:
        _log("no tool called", "plain text answer")
        return reply

    results = _run_calls(calls)

    # Every call named a tool that does not exist
    if all(r["result"] == {"error": "There is no such tool."} for r in results):
        return "Sorry, I can't do that yet. I don't have a tool for it."

    # Ask the model to phrase ONE reply covering every real result
    followup_messages = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": (
            f"Tool results, in the order they ran: {json.dumps(results, default=str)}\n"
            "Reply to the user naturally and briefly, without emojis, using ONLY these results. "
            "Cover EVERY result, one by one, in order. "
            "If a result is null, false, empty, or contains an error, say clearly which "
            "request did not work and why, instead of calling it done. "
            "When listing tasks, events, reminders, activities or contacts, show each item's "
            "real id number exactly as it appears in the result; never renumber them. "
            "If the user asked what they did or accomplished, summarize the activities "
            "in a friendly way. An empty activity list means nothing was logged for that day. "
            "If a result contains warning_overlaps_with, tell the user the new time "
            "clashes with those events. "
            "If a result is an email draft, say in ONE short sentence who it is addressed to. "
            "Do NOT repeat its subject or body, and do not mention buttons or how to send it: "
            "the page shows the draft and the code adds the instructions. "
            "NEVER say the email was sent. "
            "If a result says no email address is saved for someone, ask the user for the "
            "address and offer to save it as a contact. "
            "Do not claim anything the results do not show."
        )}
    ]
    final = _ask(followup_messages)

    # Added by code, so it never depends on the model remembering to say it
    if _draft_created(results):
        # What the user actually said: this message plus their earlier ones in this chat
        said_text = " ".join([user_message] + [m["content"] for m in recent if m["role"] == "user"])
        extra = _draft_warnings(results, said_text)
        if extra:
            _log("draft check", extra)
            quoted = ", ".join(f'"{w}"' for w in extra)
            final += f"\n\nCheck the draft: it mentions {quoted}, which was not in your request."
        final += (
            "\n\nThis draft has not been sent. "
            "Click Send email below if it looks right."
        )
    return final