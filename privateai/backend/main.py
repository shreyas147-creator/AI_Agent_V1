"""
PrivateAI — local-only assistant backend
Entry point: starts FastAPI server, registers tools, loads LLM
"""

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json

from orchestrator.orchestrator import Orchestrator
from db.database import init_db

app = FastAPI(title="PrivateAI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://localhost:5173", "tauri://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class ConfirmRequest(BaseModel):
    action_id: str
    confirmed: bool
    session_id: Optional[str] = "default"


@app.on_event("startup")
async def startup():
    init_db()
    orchestrator.load_tools()


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": orchestrator.llm.is_loaded()}


@app.post("/chat")
def chat(req: ChatRequest):
    """
    Main chat endpoint.
    Returns either:
      - { type: "response", text: "..." }
      - { type: "confirmation_required", action_id: "...", preview: {...} }
    """
    result = orchestrator.handle(req.message, req.session_id)
    return result


@app.post("/confirm")
def confirm(req: ConfirmRequest):
    """Execute a previously previewed action after user confirms."""
    result = orchestrator.execute_confirmed(req.action_id, req.confirmed, req.session_id)
    return result


@app.get("/tools")
def list_tools():
    return {"tools": orchestrator.list_tools()}


@app.get("/memory/{session_id}")
def get_memory(session_id: str):
    return orchestrator.get_short_term_memory(session_id)


@app.delete("/memory/{session_id}")
def clear_memory(session_id: str):
    orchestrator.clear_memory(session_id)
    return {"status": "cleared"}


@app.delete("/data/all")
def delete_all_data():
    """Nuclear option — wipes everything. Requires explicit call."""
    from db.database import drop_all
    drop_all()
    init_db()
    orchestrator.clear_all_memory()
    return {"status": "all_data_deleted"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
