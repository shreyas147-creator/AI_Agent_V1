"""
Calendar tool — CRUD for events stored in local SQLite.
No cloud sync. No external calls.
"""

from typing import Optional
from datetime import datetime, timedelta
import json

from .base_tool import BaseTool, ToolError
from db.database import get_db


class CalendarTool(BaseTool):
    name = "calendar"
    description = (
        "Create, list, update, or delete calendar events. "
        "Use for meetings, appointments, scheduling tasks with a specific time."
    )
    requires_confirmation = False
    schema = {
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "list", "update", "delete"],
                "description": "What to do",
            },
            "title": {"type": "string", "description": "Event title"},
            "start_time": {"type": "string", "description": "ISO 8601 start datetime, e.g. 2024-06-01T14:00:00"},
            "end_time": {"type": "string", "description": "ISO 8601 end datetime"},
            "description": {"type": "string", "description": "Optional notes"},
            "event_id": {"type": "integer", "description": "For update/delete"},
            "date_filter": {"type": "string", "description": "For list: 'today', 'tomorrow', 'week', or ISO date"},
        },
        "required": ["operation"],
    }

    def validate(self, params: dict) -> Optional[str]:
        op = params.get("operation")
        if not op:
            return "'operation' is required (create, list, update, delete)"
        if op == "create":
            if not params.get("title"):
                return "'title' is required for creating an event"
            if not params.get("start_time"):
                return "'start_time' is required (ISO 8601 format)"
        if op in ("update", "delete") and not params.get("event_id"):
            return "'event_id' is required for update/delete"
        return None

    def execute(self, params: dict) -> dict:
        op = params["operation"]
        db = get_db()
        try:
            if op == "create":
                return self._create(db, params)
            elif op == "list":
                return self._list(db, params)
            elif op == "update":
                return self._update(db, params)
            elif op == "delete":
                return self._delete(db, params)
        finally:
            db.close()

    def _create(self, db, params: dict) -> dict:
        start_str = params["start_time"]
        end_str = params.get("end_time")

        start = self._parse_time(start_str)
        if end_str:
            end = self._parse_time(end_str)
        else:
            end = start + timedelta(hours=1)

        cur = db.execute(
            "INSERT INTO calendar_events (title, start_time, end_time, description) VALUES (?,?,?,?)",
            (params["title"], start.isoformat(), end.isoformat(), params.get("description", "")),
        )
        db.commit()
        event_id = cur.lastrowid
        return {
            "message": f"Event '{params['title']}' created on {start.strftime('%b %d at %I:%M %p')}.",
            "event_id": event_id,
        }

    def _list(self, db, params: dict) -> dict:
        date_filter = params.get("date_filter", "today")
        now = datetime.now()

        if date_filter == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif date_filter == "tomorrow":
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif date_filter == "week":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        else:
            try:
                start = datetime.fromisoformat(date_filter)
                end = start + timedelta(days=1)
            except Exception:
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)

        rows = db.execute(
            "SELECT id, title, start_time, end_time, description FROM calendar_events "
            "WHERE start_time >= ? AND start_time < ? ORDER BY start_time",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

        events = [
            {
                "id": r[0],
                "title": r[1],
                "start": r[2],
                "end": r[3],
                "description": r[4],
            }
            for r in rows
        ]

        if not events:
            return {"message": f"No events for {date_filter}.", "events": []}

        lines = [f"• {e['title']} at {self._fmt(e['start'])}" for e in events]
        return {"message": "\n".join(lines), "events": events}

    def _update(self, db, params: dict) -> dict:
        event_id = params["event_id"]
        updates = []
        vals = []
        if "title" in params:
            updates.append("title = ?"); vals.append(params["title"])
        if "start_time" in params:
            updates.append("start_time = ?"); vals.append(self._parse_time(params["start_time"]).isoformat())
        if "end_time" in params:
            updates.append("end_time = ?"); vals.append(self._parse_time(params["end_time"]).isoformat())
        if "description" in params:
            updates.append("description = ?"); vals.append(params["description"])
        if not updates:
            return {"message": "Nothing to update."}
        vals.append(event_id)
        db.execute(f"UPDATE calendar_events SET {', '.join(updates)} WHERE id = ?", vals)
        db.commit()
        return {"message": f"Event {event_id} updated."}

    def _delete(self, db, params: dict) -> dict:
        event_id = params["event_id"]
        db.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        db.commit()
        return {"message": f"Event {event_id} deleted."}

    def _parse_time(self, s: str) -> datetime:
        try:
            return datetime.fromisoformat(s)
        except Exception:
            raise ToolError(f"Could not parse time: '{s}'. Use ISO 8601 format.")

    def _fmt(self, iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%b %d, %I:%M %p")
        except Exception:
            return iso


TOOL_CLASS = CalendarTool
