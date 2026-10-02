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
# When you add a new tool file later, just import its manifest and add it to this list.
ALL_TOOLS = TASKS_MANIFEST  # + SCHEDULE_MANIFEST + REMINDERS_MANIFEST ... later

# Build a lookup: tool name -> actual Python function
AVAILABLE_FUNCTIONS = {tool["name"]: tool["function"] for tool in ALL_TOOLS}

def _build_system_prompt():
    tool_descriptions = ""
    for tool in ALL_TOOLS:
        args_desc = ", ".join(f"{k}: {v}" for k, v in tool["args"].items()) or "no arguments"
        tool_descriptions += f"- {tool['name']}({args_desc}): {tool['description']}\n"

    return f"""You are Agent Bujji, a personal AI assistant with access to real tools. You do NOT pretend to use tools — you MUST actually call them.

Available tools:
{tool_descriptions}

RULES:
1. If the user's request matches a tool's purpose, you MUST respond with ONLY a JSON object, nothing else - no explanation, no extra text.
2. Format: {{"tool": "<function_name>", "args": {{}}}}
3. NEVER say things like "this is how it would work" or "I don't have access" - you DO have access. Just output the JSON.
4. Only respond in plain text if no tool applies (e.g., general conversation, greetings).
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

    if tool_call and "tool" in tool_call:
        func_name = tool_call["tool"]
        func_args = tool_call.get("args", {})
        func = AVAILABLE_FUNCTIONS.get(func_name)

        if func:
            result = func(**func_args)

            followup_messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"Tool result: {json.dumps(result)}. Please reply to the user naturally based on this result."}
            ]
            final_response = client.chat.completions.create(
                model="Phi-4",
                messages=followup_messages,
            )
            reply = final_response.choices[0].message.content

    return reply