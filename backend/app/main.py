from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import run_agent
from notifier import start_watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the backend starts: begin watching for due reminders
    start_watcher()
    yield


app = FastAPI(lifespan=lifespan)

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