"""
Tool registry: discovers and manages all tool modules.
Each tool must subclass BaseTool.
"""

import importlib
import os
import logging
from typing import Optional
from .base_tool import BaseTool

logger = logging.getLogger(__name__)

# All tool module paths relative to tools/
TOOL_MODULES = [
    "tools.calendar_tool",
    "tools.reminders_tool",
    "tools.email_tool",
    "tools.pdf_tool",
    "tools.memory_tool",
]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def load_all(self):
        for module_path in TOOL_MODULES:
            try:
                mod = importlib.import_module(module_path)
                # Each module must expose TOOL_CLASS
                tool_cls = getattr(mod, "TOOL_CLASS", None)
                if tool_cls is None:
                    logger.warning(f"Module {module_path} has no TOOL_CLASS")
                    continue
                tool: BaseTool = tool_cls()
                self._tools[tool.name] = tool
                logger.info(f"Loaded tool: {tool.name}")
            except Exception as e:
                logger.error(f"Failed to load {module_path}: {e}")

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_schemas(self) -> list:
        return [
            {
                "name": t.name,
                "description": t.description,
                "params": t.schema,
                "requires_confirmation": t.requires_confirmation,
            }
            for t in self._tools.values()
        ]

    def all_tools(self) -> dict:
        return dict(self._tools)
