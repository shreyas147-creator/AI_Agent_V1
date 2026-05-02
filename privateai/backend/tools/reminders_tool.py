"""
Reminders tool — schedule and fire OS notifications.
Uses APScheduler for background jobs, SQLite for persistence.
No confirmation required (read/write local only).
"""

from typing import Optional
from datetime import datetime, timedelta
import threading
import logging

from .base_tool import BaseTool, ToolError
from db.database import get_db

logger = logging.getLogger(__name__)

# Global scheduler — started once on import
_scheduler = None
_scheduler_lock = threading.Lock()


def get_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            try:
                from apscheduler.schedulers.background import BackgroundScheduler
                _scheduler = BackgroundScheduler()
                _scheduler.start()
                logger.info("APScheduler started")
            except ImportError:
                logger.warning("apscheduler not installed — reminders won't fire automatically")
    return _scheduler


def fire_notification(reminder_id: int, title: str, body: str):
    """Fire OS notification and mark reminder as fired."""
    try:
        import plyer
        plyer.notification.notify(title=title, message=body, app_name="PrivateAI", timeout=10)
    except Exception:
        # Fallback: just log
        logger.info(f"REMINDER: {title} — {body}")

    db = get_db()
    try:
        db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
        db.commit()
    finally:
        db.close()


class RemindersTool(BaseTool):
    name = "reminders"
    description = (
        "Set a reminder that fires an OS notification at a specific time. "
        "Also list, update, or delete reminders."
    )
    requires_confirmation = False
    schema = {
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "list", "delete"],
                "description": "What to do",
            },
            "title": {"type": "string", "description": "Reminder title / what to remind"},
            "remind_at": {"type": "string", "description": "ISO 8601 datetime when to fire"},
            "note": {"type": "string", "description": "Optional extra detail"},
            "reminder_id": {"type": "integer", "description": "For delete"},
        },
        "required": ["operation"],
    }

    def validate(self, params: dict) -> Optional[str]:
        op = params.get("operation")
        if not op:
            return "'operation' is required"
        if op == "create":
            if not params.get("title"):
                return "'title' is required"
            if not params.get("remind_at"):
                return "'remind_at' is required (ISO 8601)"
        if op == "delete" and not params.get("reminder_id"):
            return "'reminder_id' is required"
        return None

    def execute(self, params: dict) -> dict:
        op = params["operation"]
        db = get_db()
        try:
            if op == "create":
                return self._create(db, params)
            elif op == "list":
                return self._list(db)
            elif op == "delete":
                return self._delete(db, params)
        finally:
            db.close()

    def _create(self, db, params: dict) -> dict:
        remind_at_str = params["remind_at"]
        try:
            remind_at = datetime.fromisoformat(remind_at_str)
        except Exception:
            raise ToolError(f"Invalid time format: '{remind_at_str}'")

        if remind_at < datetime.now():
            raise ToolError("Reminder time is in the past.")

        cur = db.execute(
            "INSERT INTO reminders (title, note, remind_at, fired) VALUES (?,?,?,0)",
            (params["title"], params.get("note", ""), remind_at.isoformat()),
        )
        db.commit()
        reminder_id = cur.lastrowid

        # Schedule with APScheduler
        sched = get_scheduler()
        if sched:
            try:
                sched.add_job(
                    fire_notification,
                    trigger="date",
                    run_date=remind_at,
                    args=[reminder_id, "PrivateAI Reminder", params["title"]],
                    id=f"reminder_{reminder_id}",
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning(f"Could not schedule reminder: {e}")

        human_time = remind_at.strftime("%b %d at %I:%M %p")
        return {
            "message": f"Reminder set: '{params['title']}' on {human_time}.",
            "reminder_id": reminder_id,
        }

    def _list(self, db) -> dict:
        rows = db.execute(
            "SELECT id, title, note, remind_at, fired FROM reminders "
            "WHERE fired = 0 ORDER BY remind_at"
        ).fetchall()

        if not rows:
            return {"message": "No upcoming reminders.", "reminders": []}

        reminders = [{"id": r[0], "title": r[1], "note": r[2], "remind_at": r[3]} for r in rows]
        lines = [f"• [{r['id']}] {r['title']} — {self._fmt(r['remind_at'])}" for r in reminders]
        return {"message": "\n".join(lines), "reminders": reminders}

    def _delete(self, db, params: dict) -> dict:
        rid = params["reminder_id"]
        db.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        db.commit()
        sched = get_scheduler()
        if sched:
            try:
                sched.remove_job(f"reminder_{rid}")
            except Exception:
                pass
        return {"message": f"Reminder {rid} deleted."}

    def _fmt(self, iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%b %d, %I:%M %p")
        except Exception:
            return iso


TOOL_CLASS = RemindersTool
