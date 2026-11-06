from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import run_agent
from tools.reminders import get_due_reminders, mark_fired

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@app.get("/")
def read_root():
    return {"message": "Agent Bujji backend is running"}


@app.post("/chat")
def chat(request: ChatRequest):
    reply = run_agent(request.message, request.history)
    return {"reply": reply}


@app.get("/reminders/due")
def due_reminders():
    """Reminders whose time has arrived. Each one is returned only once."""
    due = get_due_reminders()
    mark_fired([r["id"] for r in due])
    return {"due": due}