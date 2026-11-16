import os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database
from agent import run_agent
from notifier import start_watcher
from tools.email_drafts import get_pending_drafts, send_draft, discard_draft
from accounts import create_account, verify_login, get_account
from auth import make_token, read_token, login_allowed, record_failure, clear_failures


def _login_required():
    """Set REQUIRE_LOGIN=1 in .env to refuse requests that have no login."""
    return (os.getenv("REQUIRE_LOGIN") or "").strip().lower() in ("1", "true", "yes", "on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warn at startup if the signing secret is missing
    try:
        make_token(0)
    except RuntimeError as e:
        print(f"[AUTH] {e}")
    print("[AUTH] login is required" if _login_required() else "[AUTH] login is NOT required (owner mode)")
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


def _account_from_header(authorization):
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    account_id = read_token(token)
    return get_account(account_id) if account_id is not None else None


def current_account(authorization: str = Header(default="")):
    """The logged-in account, from 'Authorization: Bearer <token>'. Otherwise a 401."""
    account = _account_from_header(authorization)
    if account is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    return account


def current_customer_id(authorization: str = Header(default="")):
    """Whose data this request uses. None means the owner's own data, which is only
    possible when no token is sent and login is not required.
    A token that is sent but bad is ALWAYS refused."""
    if authorization.strip():
        account = _account_from_header(authorization)
        if account is None:
            raise HTTPException(status_code=401, detail="Please log in.")
        database.ensure_customer_db(account["id"])
        return account["id"]
    if _login_required():
        raise HTTPException(status_code=401, detail="Please log in.")
    return None


def _client_ip(request: Request):
    return request.client.host if request.client else "unknown"


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class Credentials(BaseModel):
    email: str
    password: str


@app.get("/")
def read_root():
    return {"message": "Agent Bujji backend is running"}


@app.post("/signup")
def signup(creds: Credentials, request: Request):
    result = create_account(creds.email, creds.password)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    database.ensure_customer_db(result["id"])
    return {"token": make_token(result["id"]), "email": result["email"]}


@app.post("/login")
def login(creds: Credentials, request: Request):
    ip = _client_ip(request)
    if not login_allowed(creds.email, ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait 15 minutes and try again.")
    account = verify_login(creds.email, creds.password)
    if account is None:
        record_failure(creds.email, ip)
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    clear_failures(creds.email)
    return {"token": make_token(account["id"]), "email": account["email"]}


@app.get("/me")
def me(account: dict = Depends(current_account)):
    return {"id": account["id"], "email": account["email"]}


@app.post("/chat")
def chat(request: ChatRequest, customer=Depends(current_customer_id)):
    with database.use_customer(customer):
        reply = run_agent(request.message, request.history)
    return {"reply": reply}


@app.get("/email/drafts")
def email_drafts(customer=Depends(current_customer_id)):
    """Drafts waiting for the user to send or discard them."""
    with database.use_customer(customer):
        return {"drafts": get_pending_drafts()}


@app.post("/email/drafts/{draft_id}/send")
def email_send(draft_id: int, _: None = Depends(require_ui_header), customer=Depends(current_customer_id)):
    if customer is not None:
        # Sending would use the owner's Gmail account, so customers cannot send yet
        return {"ok": False, "error": "Sending email is not available for accounts yet."}
    with database.use_customer(customer):
        return send_draft(draft_id)


@app.post("/email/drafts/{draft_id}/discard")
def email_discard(draft_id: int, _: None = Depends(require_ui_header), customer=Depends(current_customer_id)):
    with database.use_customer(customer):
        return {"ok": discard_draft(draft_id)}