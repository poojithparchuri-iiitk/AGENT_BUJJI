from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import run_agent
from notifier import start_watcher
from tools.email_drafts import get_pending_drafts, send_draft, discard_draft


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once when the backend starts: begin watching for due reminders
    start_watcher()
    yield


app = FastAPI(lifespan=lifespan)

# Only pages served from this laptop (any localhost port) may call the backend
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_ui_header(x_bujji_ui: str = Header(default="")):
    """Sending or discarding an email must come from the Bujji chat page,
    which adds this header to its requests."""
    if x_bujji_ui != "1":
        raise HTTPException(status_code=403, detail="This action must come from the Agent Bujji page.")


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


@app.get("/email/drafts")
def email_drafts():
    """Drafts waiting for the user to send or discard them."""
    return {"drafts": get_pending_drafts()}


@app.post("/email/drafts/{draft_id}/send")
def email_send(draft_id: int, _: None = Depends(require_ui_header)):
    return send_draft(draft_id)


@app.post("/email/drafts/{draft_id}/discard")
def email_discard(draft_id: int, _: None = Depends(require_ui_header)):
    return {"ok": discard_draft(draft_id)}