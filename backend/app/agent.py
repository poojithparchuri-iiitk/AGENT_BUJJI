import os, json, re
from datetime import date, datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv

from tools.tasks import TOOL_MANIFEST as TASKS_MANIFEST
from tools.schedule import TOOL_MANIFEST as SCHEDULE_MANIFEST

load_dotenv()

endpoint = os.getenv("AZURE_PHI4_ENDPOINT")
api_key = os.getenv("AZURE_PHI4_API_KEY")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key,
)

# Set to False to silence the [DEBUG] lines in the backend terminal
DEBUG = True

# Combine manifests from all tool files here.
# When you add a new tool file later, import its manifest and add it to this list.
ALL_TOOLS = TASKS_MANIFEST + SCHEDULE_MANIFEST  # + REMINDERS_MANIFEST ... later

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
    r"|i['\u2019]ve (added|deleted|removed|marked|scheduled|moved|renamed|cleared|updated)"
    r"|i have (added|deleted|removed|marked|scheduled|moved|renamed|cleared|updated))\b",
    re.IGNORECASE,
)


def _log(label, value):
    """Print a debug line to the backend terminal (only when DEBUG is True)."""
    if DEBUG:
        print(f"[DEBUG] {label}: {str(value)[:300]}")


def _date_context():
    """Right now (date and time) plus the next 8 days, so the model can convert
    words like 'tomorrow', 'this Friday' or '4 PM' into real values."""
    now = datetime.now()
    today = date.today()
    upcoming = "\n".join(
        f"- {(today + timedelta(days=i)).strftime('%A %Y-%m-%d')}"
        for i in range(0, 9)
    )
    return now.strftime("%A, %Y-%m-%d, %H:%M"), upcoming


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

    now_text, upcoming_text = _date_context()
    history_text = _format_history(recent)

    return f"""You are Agent Bujji, a personal AI assistant with access to real tools. You do NOT pretend to use tools - you MUST actually call them.

Right now it is {now_text} (24-hour clock).
Calendar for the next days:
{upcoming_text}

Available tools:
{tool_descriptions}

RULES:
1. If the user's request matches a tool's purpose, respond with ONLY JSON tool calls, nothing else - no explanation, no extra text.
2. Format of one call: {{"tool": "<function_name>", "args": {{}}}}
3. If the user asks for several things in one message, output one JSON tool call per request, each on its own line, in the order they were asked (at most 5).
4. Only use tool names from the list above. NEVER invent a tool name.
5. In "args", use ONLY the exact argument names listed for that tool. Never invent or rename arguments. Leave out any optional argument you do not need.
6. If the user asks for something that NO tool above can do (for example sending an email, setting a reminder, or checking the weather), reply in plain text: say clearly that you cannot do that yet, and mention what you CAN do with your tools.
7. NEVER say that something was added, deleted, changed or scheduled unless a tool actually ran. You cannot change anything without a tool call.
8. Plain text is also fine for normal conversation and greetings.
9. DATES AND TIMES: convert the user's words into numbers using the calendar above. If the user gives a date only, pass YYYY-MM-DD. If the user gives a time too, pass YYYY-MM-DD HH:MM using the 24-hour clock (4 PM becomes 16:00, 9 AM becomes 09:00, noon is 12:00). Never pass dates or times as words. If the user gives no date, leave the date argument out.
10. The RECENT CONVERSATION block at the end is for context only, to understand words like "it" or "that task". Those earlier Bujji replies were written AFTER a tool had already run. Do NOT copy their style. Your answer to the NEWEST user message must follow rules 1 to 9: a request that needs a tool is answered with ONLY the JSON tool call(s).
11. Do NOT ask the user for confirmation before doing something they clearly asked for, such as marking a task done. Call the tool right away. Only ask a question if a tool result says more than one item matches.
12. TASKS versus EVENTS: a TASK is something to get done (submit the report, buy milk), possibly with a deadline. An EVENT is something that happens at a specific time (a meeting, a class, an appointment, a call). Use the event tools for events and the task tools for tasks. If the user wants an event but gave no time, ask them for the time in plain text.

EXAMPLES:
User: "rename the dentist task to book dentist appointment"
You: {{"tool": "edit_task", "args": {{"title": "dentist", "new_title": "book dentist appointment"}}}}
User: "add a task: submit report at 4 PM tomorrow"
You: {{"tool": "add_task", "args": {{"title": "submit report", "due_date": "<tomorrow's date from the calendar> 16:00"}}}}
User: "I have a project meeting tomorrow at 4 PM"
You: {{"tool": "add_event", "args": {{"title": "project meeting", "start_time": "<tomorrow's date from the calendar> 16:00"}}}}
User: "what is on my schedule tomorrow"
You: {{"tool": "list_events", "args": {{"date": "<tomorrow's date from the calendar>"}}}}
User: "mark the milk task as done and show my schedule tomorrow"
You:
{{"tool": "complete_task", "args": {{"title": "milk"}}}}
{{"tool": "list_events", "args": {{"date": "<tomorrow's date from the calendar>"}}}}

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
            "Reply to the user naturally, using ONLY these results. Cover EVERY result, "
            "one by one, in order. "
            "If a result is null, false, empty, or contains an error, say clearly which "
            "request did not work and why, instead of calling it done. "
            "When listing tasks or events, show each item's real id number exactly as it "
            "appears in the result; never renumber them. "
            "If a result contains warning_overlaps_with, tell the user the new time "
            "clashes with those events. "
            "Do not claim anything the results do not show."
        )}
    ]
    return _ask(followup_messages)