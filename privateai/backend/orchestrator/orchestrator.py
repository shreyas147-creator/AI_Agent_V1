"""
Orchestrator: parses intent, decides action vs response,
manages short-term memory, handles confirmation flow.

The LLM NEVER directly executes anything.
It outputs structured JSON → we validate → we execute.
"""

import json
import uuid
import time
from typing import Optional
from collections import defaultdict, deque

from llm.llm_client import LLMClient
from tools.registry import ToolRegistry
from db.database import log_interaction


SYSTEM_PROMPT = """You are PrivateAI, a local assistant. You MUST always respond with valid JSON only.

Available tools: {tool_schemas}

Rules:
1. If the user wants an ACTION, respond:
   {{"action": "<tool_name>", "params": {{...}}, "reasoning": "<why>"}}

2. If just a conversation/question (no tool needed), respond:
   {{"action": "none", "response": "<your answer>"}}

3. If you need clarification before acting, respond:
   {{"action": "clarify", "question": "<what you need to know>"}}

4. Never guess missing required params — ask instead.
5. For time expressions like "tomorrow 3pm", "next Monday", output ISO 8601.
6. Be concise. Do not add markdown, prose, or explanation outside the JSON.

Short-term memory (recent turns):
{memory}
"""


class Orchestrator:
    def __init__(self):
        self.llm = LLMClient()
        self.registry = ToolRegistry()
        # session_id → deque of last N turns
        self._memory: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
        # pending confirmations: action_id → {tool, params, session_id}
        self._pending: dict[str, dict] = {}

    def load_tools(self):
        self.registry.load_all()

    def list_tools(self) -> list:
        return self.registry.list_schemas()

    def get_short_term_memory(self, session_id: str) -> list:
        return list(self._memory[session_id])

    def clear_memory(self, session_id: str):
        self._memory[session_id].clear()

    def clear_all_memory(self):
        self._memory.clear()
        self._pending.clear()

    def handle(self, message: str, session_id: str) -> dict:
        t0 = time.monotonic()
        memory_text = self._format_memory(session_id)
        tool_schemas = json.dumps(self.registry.list_schemas(), indent=2)

        system = SYSTEM_PROMPT.format(
            tool_schemas=tool_schemas,
            memory=memory_text or "None yet."
        )

        raw = self.llm.generate(system_prompt=system, user_message=message)
        parsed = self._safe_parse(raw)

        self._memory[session_id].append({"role": "user", "content": message})

        latency_ms = int((time.monotonic() - t0) * 1000)

        if parsed is None:
            # LLM returned garbage — fail safely
            reply = {"type": "response", "text": "I couldn't understand that. Could you rephrase?", "latency_ms": latency_ms}
            self._memory[session_id].append({"role": "assistant", "content": reply["text"]})
            return reply

        action = parsed.get("action", "none")

        if action == "none":
            text = parsed.get("response", "")
            self._memory[session_id].append({"role": "assistant", "content": text})
            log_interaction(session_id, message, text, "none", latency_ms)
            return {"type": "response", "text": text, "latency_ms": latency_ms}

        if action == "clarify":
            q = parsed.get("question", "Could you clarify?")
            self._memory[session_id].append({"role": "assistant", "content": q})
            return {"type": "clarify", "text": q, "latency_ms": latency_ms}

        # It's a tool call
        tool = self.registry.get(action)
        if tool is None:
            text = f"I don't have a tool called '{action}' yet."
            self._memory[session_id].append({"role": "assistant", "content": text})
            return {"type": "response", "text": text, "latency_ms": latency_ms}

        params = parsed.get("params", {})
        validation_error = tool.validate(params)
        if validation_error:
            text = f"Missing info: {validation_error}"
            self._memory[session_id].append({"role": "assistant", "content": text})
            return {"type": "clarify", "text": text, "latency_ms": latency_ms}

        # Check if tool requires confirmation
        if tool.requires_confirmation:
            action_id = str(uuid.uuid4())
            preview = tool.preview(params)
            self._pending[action_id] = {
                "tool_name": action,
                "params": params,
                "session_id": session_id,
                "message": message,
            }
            return {
                "type": "confirmation_required",
                "action_id": action_id,
                "tool": action,
                "preview": preview,
                "latency_ms": latency_ms,
            }

        # Safe tool — execute immediately
        result = tool.execute(params)
        text = result.get("message", "Done.")
        self._memory[session_id].append({"role": "assistant", "content": text})
        log_interaction(session_id, message, text, action, latency_ms)
        return {"type": "response", "text": text, "data": result, "latency_ms": latency_ms}

    def execute_confirmed(self, action_id: str, confirmed: bool, session_id: str) -> dict:
        pending = self._pending.pop(action_id, None)
        if pending is None:
            return {"type": "error", "text": "No pending action found. It may have expired."}

        if not confirmed:
            return {"type": "response", "text": "Cancelled. Nothing was changed."}

        tool_name = pending["tool_name"]
        params = pending["params"]
        tool = self.registry.get(tool_name)
        if tool is None:
            return {"type": "error", "text": f"Tool '{tool_name}' not found."}

        result = tool.execute(params)
        text = result.get("message", "Done.")
        self._memory[session_id].append({"role": "assistant", "content": text})
        log_interaction(session_id, pending["message"], text, tool_name, 0)
        return {"type": "response", "text": text, "data": result}

    def _format_memory(self, session_id: str) -> str:
        mem = self._memory[session_id]
        if not mem:
            return ""
        lines = []
        for turn in mem:
            role = turn["role"].upper()
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)

    def _safe_parse(self, raw: str) -> Optional[dict]:
        raw = raw.strip()
        # Strip markdown fences if model wraps it
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract first {...} block
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(raw[start:end+1])
                except Exception:
                    pass
        return None
