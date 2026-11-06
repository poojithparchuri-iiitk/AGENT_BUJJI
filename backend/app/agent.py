import os, json, re
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


def _build_system_prompt():
    tool_descriptions = ""
    for tool in ALL_TOOLS:
        args_desc = ", ".join(f"{k}: {v}" for k, v in tool["args"].items()) or "no arguments"
        tool_descriptions += f"- {tool['name']}({args_desc}): {tool['description']}\n"

    return f"""You are Agent Bujji, a personal AI assistant with access to real tools. You do NOT pretend to use tools - you MUST actually call them.

Available tools:
{tool_descriptions}

RULES:
1. If the user's request matches a tool's purpose, respond with ONLY a JSON object, nothing else - no explanation, no extra text.
2. Format: {{"tool": "<function_name>", "args": {{}}}}
3. Only use tool names from the list above. NEVER invent a tool name.
4. If the user asks for something that NO tool above can do (for example sending an email, setting a reminder, or checking the weather), reply in plain text: say clearly that you cannot do that yet, and mention what you CAN do with your tools.
5. NEVER claim you did something unless a tool actually ran and confirmed it.
6. Plain text is also fine for normal conversation and greetings.
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


def run_agent(user_message: str) -> str:
    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": user_message}
    ]

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
            "Do not claim anything the result does not show."
        )}
    ]
    final_response = client.chat.completions.create(
        model="Phi-4",
        messages=followup_messages,
    )
    return final_response.choices[0].message.content