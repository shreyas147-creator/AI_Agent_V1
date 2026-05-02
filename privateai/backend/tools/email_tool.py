"""
Email tool — IMAP/SMTP client.
REQUIRES CONFIRMATION before sending. Always.
Draft → Preview → User confirms → Send.
Config stored in local config file, never in DB.
"""

import os
import json
import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import Optional
import logging

from .base_tool import BaseTool, ToolError

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.expanduser("~/.privateai/email_config.json")


def load_email_config() -> Optional[dict]:
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH) as f:
        return json.load(f)


class EmailTool(BaseTool):
    name = "email"
    description = (
        "Send, read, or list emails. "
        "Sending always requires user confirmation — a draft is shown first. "
        "Use for composing emails, checking inbox, reading messages."
    )
    requires_confirmation = True  # ALWAYS confirm before send
    schema = {
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["draft", "list_inbox", "read"],
                "description": "draft = compose for review, list_inbox = show recent, read = fetch message",
            },
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body text"},
            "message_id": {"type": "string", "description": "For read operation"},
            "count": {"type": "integer", "description": "Number of emails to list (default 10)"},
        },
        "required": ["operation"],
    }

    def validate(self, params: dict) -> Optional[str]:
        op = params.get("operation")
        if not op:
            return "'operation' is required"
        if op == "draft":
            if not params.get("to"):
                return "'to' (recipient address) is required"
            if not params.get("subject"):
                return "'subject' is required"
            if not params.get("body"):
                return "'body' is required"
        return None

    def preview(self, params: dict) -> dict:
        """Show the draft before user confirms send."""
        op = params.get("operation")
        if op == "draft":
            return {
                "description": "Ready to send this email:",
                "to": params.get("to"),
                "subject": params.get("subject"),
                "body": params.get("body"),
                "warning": "This will send a real email. Confirm to proceed.",
            }
        return {"description": f"Email operation: {op}"}

    def execute(self, params: dict) -> dict:
        op = params["operation"]
        if op == "draft":
            return self._send(params)
        elif op == "list_inbox":
            return self._list_inbox(params)
        elif op == "read":
            return self._read(params)
        raise ToolError(f"Unknown operation: {op}")

    def _send(self, params: dict) -> dict:
        cfg = load_email_config()
        if not cfg:
            return {
                "message": (
                    "Email not configured. Create ~/.privateai/email_config.json with: "
                    "{\"smtp_host\": \"...\", \"smtp_port\": 587, \"username\": \"...\", "
                    "\"password\": \"...\", \"from_address\": \"...\"}"
                )
            }

        msg = MIMEMultipart()
        msg["From"] = cfg["from_address"]
        msg["To"] = params["to"]
        msg["Subject"] = params["subject"]
        msg.attach(MIMEText(params["body"], "plain"))

        try:
            with smtplib.SMTP(cfg["smtp_host"], cfg.get("smtp_port", 587)) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["username"], cfg["password"])
                server.sendmail(cfg["from_address"], [params["to"]], msg.as_string())

            return {"message": f"Email sent to {params['to']}: '{params['subject']}'"}
        except smtplib.SMTPAuthenticationError:
            raise ToolError("SMTP authentication failed. Check your credentials.")
        except Exception as e:
            raise ToolError(f"Failed to send email: {e}")

    def _list_inbox(self, params: dict) -> dict:
        cfg = load_email_config()
        if not cfg or "imap_host" not in cfg:
            return {"message": "IMAP not configured. Add 'imap_host' to email_config.json."}

        count = params.get("count", 10)
        try:
            mail = imaplib.IMAP4_SSL(cfg["imap_host"])
            mail.login(cfg["username"], cfg["password"])
            mail.select("inbox")
            _, data = mail.search(None, "ALL")
            ids = data[0].split()
            recent = ids[-count:][::-1]

            messages = []
            for mid in recent:
                _, msg_data = mail.fetch(mid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
                raw = msg_data[0][1].decode(errors="replace")
                parsed = email_lib.message_from_string(raw)
                subj = self._decode_header(parsed.get("Subject", ""))
                frm = self._decode_header(parsed.get("From", ""))
                date = parsed.get("Date", "")
                messages.append({"id": mid.decode(), "from": frm, "subject": subj, "date": date})

            mail.logout()
            lines = [f"• [{m['id']}] {m['subject']} — from {m['from']}" for m in messages]
            return {"message": "\n".join(lines) if lines else "Inbox empty.", "messages": messages}
        except Exception as e:
            raise ToolError(f"IMAP error: {e}")

    def _read(self, params: dict) -> dict:
        cfg = load_email_config()
        if not cfg or "imap_host" not in cfg:
            return {"message": "IMAP not configured."}

        mid = params.get("message_id")
        if not mid:
            raise ToolError("message_id required")

        try:
            mail = imaplib.IMAP4_SSL(cfg["imap_host"])
            mail.login(cfg["username"], cfg["password"])
            mail.select("inbox")
            _, msg_data = mail.fetch(mid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="replace")

            mail.logout()
            return {
                "message": f"From: {msg['From']}\nSubject: {msg['Subject']}\n\n{body[:2000]}",
                "from": msg["From"],
                "subject": msg["Subject"],
                "body": body,
            }
        except Exception as e:
            raise ToolError(f"Could not read message: {e}")

    def _decode_header(self, value: str) -> str:
        if not value:
            return ""
        parts = decode_header(value)
        result = []
        for part, charset in parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(part)
        return " ".join(result)


TOOL_CLASS = EmailTool
