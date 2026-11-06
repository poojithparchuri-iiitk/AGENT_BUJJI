import os, json, re
from datetime import date, timedelta
from openai import OpenAI
from dotenv import load_dotenv

from tools.tasks import TOOL_MANIFEST as TASKS_MANIFEST

load_dotenv()

endpoint = os.getenv("AZURE_PHI4_ENDPOINT")
api_key = os.getenv("AZURE_PHI4_API_KEY")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key,
)

# Combine manifests from all tool files here.
# When you add a new tool file later, import its manifest and add it to this list.
ALL_TOOLS = TASKS_MANIFEST  # + SCHEDULE_MANIFEST + REMINDERS_MANIFEST ... later

# Lookup: tool name -> actual Python function
AVAILABLE_FUNCTIONS = {tool["name"]: tool["function"] for tool in ALL_TOOLS}

# How many previous messages Bujji can "remember" in one chat
MAX_HISTORY = 6


def _date_context():
    """Today's date plus the next 8 days, so the model can convert
    words like 'tomorrow' or 'this Friday' into real dates."""
    today = date.today()
    upcoming = "\n".join(
        f"- {(today + timedelta(days=i)).strftime('%A %Y-%m-%d')}"
        for i in range(0, 9)
    )
    return today.strftime("%A, %Y-%m-%d"), upcoming


def _build_system_prompt():
    tool_descriptions = ""
    for tool in ALL_TOOLS:
        args_desc = ", ".join(f"{k}: {v}" for k, v in tool["args"].items()) or "no arguments"
        tool_descriptions += f"- {tool['name']}({args_desc}): {tool['description']}\n"

    today_text, upcoming_text = _date_context()

    return f"""You are Agent Bujji, a personal AI assistant with access to real tools. You do NOT pretend to use tools - you MUST actually call them.

Today is {today_text}.
Calendar for the next days:
{upcoming_text}

Available tools:
{tool_descriptions}

RULES:
1. If the user's request matches a tool's purpose, respond with ONLY a JSON object, nothing else - no explanation, no extra text.
2. Format: {{"tool": "<function_name>", "args": {{}}}}
3. Only use tool names from the list above. NEVER invent a tool name.
4. If the user asks for something that NO tool above can do (for example sending an email, setting a reminder, or checking the weather), reply in plain text: say clearly that you cannot do that yet, and mention what you CAN do with your tools.
5. NEVER claim you did something unless a tool actually ran and confirmed it.
6. Plain text is also fine for normal conversation and greetings.
7. DATES: when a tool needs a due date, convert the user's words (tomorrow, Friday, next Monday, in 3 days) into YYYY-MM-DD using the calendar above. Always pass the date as YYYY-MM-DD, never as words. If the user gives no date, leave due_date out.
8. You can see the recent conversation. Use it to understand words like "it" or "that task". Even when the earlier replies were plain text, a request that needs a tool must still be answered with ONLY the JSON object.
9. Do NOT ask the user for confirmation before doing something they clearly asked for, such as marking a task done. Call the tool right away. Only ask a question if a tool result says more than one task matches.
"""


def _try_parse_tool_call(reply: str):
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


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


def run_agent(user_message: str, history=None) -> str:
    messages = (
        [{"role": "system", "content": _build_system_prompt()}]
        + _clean_history(history)
        + [{"role": "user", "content": user_message}]
    )

    response = client.chat.completions.create(
        model="Phi-4",
        messages=messages,
    )

    reply = response.choices[0].message.content.strip()
    tool_call = _try_parse_tool_call(reply)

    # Plain text reply (no tool requested)
    if not tool_call or "tool" not in tool_call:
        return reply

    func_name = tool_call["tool"]
    func_args = tool_call.get("args", {})
    func = AVAILABLE_FUNCTIONS.get(func_name)

    # The model asked for a tool that does not exist
    if func is None:
        return "Sorry, I can't do that yet. I don't have a tool for it."

    # Run the real tool; never hide a failure
    try:
        result = func(**func_args)
    except Exception as e:
        return f"I tried to do that, but it failed: {e}"

    # Ask the model to phrase a reply based ONLY on the real result
    followup_messages = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": (
            f"Tool result: {json.dumps(result)}\n"
            "Reply to the user naturally, using ONLY this result. "
            "If the result is null, false, or empty because nothing was found or changed, "
            "say clearly that it did not work or nothing matched. "
            "When listing tasks, show each task's real id number exactly as it appears "
            "in the result; never renumber them. "
            "Do not claim anything the result does not show."
        )}
    ]
    final_response = client.chat.completions.create(
        model="Phi-4",
        messages=followup_messages,
    )
    return final_response.choices[0].message.content