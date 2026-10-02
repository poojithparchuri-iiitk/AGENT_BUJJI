from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os, json, re
from dotenv import load_dotenv

from tasks import add_task, list_tasks, complete_task, delete_task

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

endpoint = os.getenv("AZURE_PHI4_ENDPOINT")
api_key = os.getenv("AZURE_PHI4_API_KEY")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key,
)

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def read_root():
    return {"message": "Agent Bujji backend is running"}

available_functions = {
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "delete_task": delete_task,
}

SYSTEM_PROMPT = """You are Agent Bujji, a personal AI assistant with access to real tools. You do NOT pretend to use tools — you MUST actually call them.

Available tools:
- add_task(title: str, due_date: str = None)
- list_tasks()
- complete_task(task_id: int)
- delete_task(task_id: int)

RULES:
1. If the user wants to see, add, complete, or delete a task, you MUST respond with ONLY a JSON object, nothing else - no explanation, no extra text.
2. Format: {"tool": "<function_name>", "args": {}}
3. Example for listing tasks: {"tool": "list_tasks", "args": {}}
4. Example for adding a task: {"tool": "add_task", "args": {"title": "submit report", "due_date": "tomorrow"}}
5. NEVER say things like "this is how it would work" or "I don't have access" - you DO have access. Just output the JSON.
6. Only respond in plain text if no tool applies (e.g., general conversation, greetings).
"""

@app.post("/chat")
def chat(request: ChatRequest):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.message}
    ]

    response = client.chat.completions.create(
        model="Phi-4",
        messages=messages,
    )

    reply = response.choices[0].message.content.strip()

    # Try to detect a tool call (JSON object) in the reply
    tool_call = None
    try:
        tool_call = json.loads(reply)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            try:
                tool_call = json.loads(match.group())
            except json.JSONDecodeError:
                tool_call = None

    if tool_call and "tool" in tool_call:
        func_name = tool_call["tool"]
        func_args = tool_call.get("args", {})
        func = available_functions.get(func_name)

        if func:
            result = func(**func_args)

            # Ask the model to phrase a natural reply based on the result
            followup_messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"Tool result: {json.dumps(result)}. Please reply to the user naturally based on this result."}
            ]
            final_response = client.chat.completions.create(
                model="Phi-4",
                messages=followup_messages,
            )
            reply = final_response.choices[0].message.content

    return {"reply": reply}