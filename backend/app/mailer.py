import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = "smtp.gmail.com"
ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _connect_587(context):
    """Port 587: connect plainly, then upgrade to a secure connection (STARTTLS)."""
    server = smtplib.SMTP(SMTP_HOST, 587, timeout=30)
    server.ehlo()
    server.starttls(context=context)
    server.ehlo()
    return server


def _connect_465(context):
    """Port 465: secure from the very first byte."""
    return smtplib.SMTP_SSL(SMTP_HOST, 465, context=context, timeout=30)


def send_email(to, subject, body):
    """Send one plain-text email through Gmail.
    Tries port 587 first, then port 465.
    Returns {"ok": True} on success, or {"ok": False, "error": "..."} on failure.
    It never raises: every problem comes back as an error message."""
    user = (os.getenv("GMAIL_USER") or "").strip()
    password = (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    reply_to = (os.getenv("EMAIL_REPLY_TO") or "").strip()
    from_name = os.getenv("EMAIL_FROM_NAME", "Agent Bujji")

    if not user or not password:
        return {"ok": False, "error": "GMAIL_USER or GMAIL_APP_PASSWORD is missing in the .env file."}

    to = str(to).strip()
    if not ADDRESS.fullmatch(to):
        return {"ok": False, "error": f"'{to}' is not a valid email address."}

    # A subject is one line; a line break in a header is refused by Python anyway
    subject = " ".join(str(subject).split())

    try:
        msg = EmailMessage()
        msg["From"] = formataddr((from_name, user))
        msg["To"] = to
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(str(body))
    except ValueError as e:
        return {"ok": False, "error": f"The email could not be built: {e}"}

    context = ssl.create_default_context()
    problems = []

    for label, connect in (("port 587", _connect_587), ("port 465", _connect_465)):
        try:
            with connect(context) as server:
                server.login(user, password)
                server.send_message(msg)
            return {"ok": True}
        except smtplib.SMTPAuthenticationError:
            # The connection worked but the login was refused: trying another port will not help
            return {"ok": False, "error": "Gmail rejected the login. Check GMAIL_USER and the app password, and that 2-Step Verification is on."}
        except Exception as e:
            problems.append(f"{label}: {type(e).__name__}: {e}")

    return {"ok": False, "error": "Could not reach Gmail. " + " | ".join(problems)}