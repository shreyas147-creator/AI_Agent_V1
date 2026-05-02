"""
BaseTool: every capability must subclass this.
Enforces the strict interface that keeps the system safe.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseTool(ABC):
    # Tool identifier — must match what LLM outputs as "action"
    name: str = ""
    description: str = ""
    # JSON schema for params (used by LLM as guidance)
    schema: dict = {}
    # If True, orchestrator will pause and ask user to confirm before executing
    requires_confirmation: bool = False

    @abstractmethod
    def execute(self, params: dict) -> dict:
        """
        Execute the tool.
        Returns dict with at least {"message": str}.
        May include additional data fields.
        Raise ToolError on expected failures.
        """
        ...

    def validate(self, params: dict) -> Optional[str]:
        """
        Validate params against schema.
        Returns error string if invalid, None if OK.
        Default implementation checks required fields.
        """
        required = self.schema.get("required", [])
        props = self.schema.get("properties", {})
        for field in required:
            if field not in params or params[field] is None or params[field] == "":
                label = props.get(field, {}).get("description", field)
                return f"'{field}' is required ({label})"
        return None

    def preview(self, params: dict) -> dict:
        """
        Return a human-readable preview of what execute() will do.
        Override in tools that require_confirmation.
        """
        return {"description": f"Will run {self.name} with {params}"}


class ToolError(Exception):
    """Expected tool failure (not a bug — e.g. file not found, SMTP rejected)."""
    pass
