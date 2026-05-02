"""
Memory tool — long-term memory via FAISS vector store.
Short-term memory is handled in-process by the Orchestrator.
This tool handles explicit "remember this" / "recall" operations.
"""

import os
import pickle
import json
import logging
from datetime import datetime
from typing import Optional

from .base_tool import BaseTool, ToolError

logger = logging.getLogger(__name__)

MEMORY_STORE_DIR = os.path.expanduser("~/.privateai/memory_store")

_memory_index = None
_memory_entries = []  # [{text, timestamp, tags}]


def _get_memory_index():
    global _memory_index, _memory_entries
    os.makedirs(MEMORY_STORE_DIR, exist_ok=True)
    index_path = os.path.join(MEMORY_STORE_DIR, "memory.faiss")
    entries_path = os.path.join(MEMORY_STORE_DIR, "entries.pkl")

    if _memory_index is None:
        if os.path.exists(index_path) and os.path.exists(entries_path):
            import faiss
            _memory_index = faiss.read_index(index_path)
            with open(entries_path, "rb") as f:
                _memory_entries = pickle.load(f)
        else:
            import faiss
            _memory_index = faiss.IndexFlatL2(384)
            _memory_entries = []

    return _memory_index, _memory_entries


def _save_memory():
    import faiss
    os.makedirs(MEMORY_STORE_DIR, exist_ok=True)
    faiss.write_index(_memory_index, os.path.join(MEMORY_STORE_DIR, "memory.faiss"))
    with open(os.path.join(MEMORY_STORE_DIR, "entries.pkl"), "wb") as f:
        pickle.dump(_memory_entries, f)


def _get_embedder():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        raise ToolError("sentence-transformers required: pip install sentence-transformers")


class MemoryTool(BaseTool):
    name = "memory"
    description = (
        "Store a fact or preference for long-term recall, or search past memories. "
        "Use when user says 'remember that', 'don't forget', or asks 'do you remember'."
    )
    requires_confirmation = False
    schema = {
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["store", "recall", "list", "forget"],
                "description": "store = save a fact, recall = search memories, list = show all, forget = delete by id",
            },
            "content": {"type": "string", "description": "The fact or text to remember"},
            "query": {"type": "string", "description": "What to search for when recalling"},
            "memory_id": {"type": "integer", "description": "For forget operation"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
        },
        "required": ["operation"],
    }

    def validate(self, params: dict) -> Optional[str]:
        op = params.get("operation")
        if not op:
            return "'operation' is required"
        if op == "store" and not params.get("content"):
            return "'content' is required"
        if op == "recall" and not params.get("query"):
            return "'query' is required"
        if op == "forget" and params.get("memory_id") is None:
            return "'memory_id' is required"
        return None

    def execute(self, params: dict) -> dict:
        op = params["operation"]
        if op == "store":
            return self._store(params)
        elif op == "recall":
            return self._recall(params)
        elif op == "list":
            return self._list()
        elif op == "forget":
            return self._forget(params)
        raise ToolError(f"Unknown operation: {op}")

    def _store(self, params: dict) -> dict:
        content = params["content"]
        tags = params.get("tags", [])

        embedder = _get_embedder()
        import numpy as np
        emb = embedder.encode([content], show_progress_bar=False)

        idx, entries = _get_memory_index()
        entry = {
            "id": len(entries),
            "text": content,
            "timestamp": datetime.now().isoformat(),
            "tags": tags,
        }
        idx.add(np.array(emb, dtype="float32"))
        entries.append(entry)
        _save_memory()

        return {"message": f"Remembered: '{content}'", "memory_id": entry["id"]}

    def _recall(self, params: dict) -> dict:
        query = params["query"]
        idx, entries = _get_memory_index()

        if idx.ntotal == 0:
            return {"message": "No memories stored yet.", "memories": []}

        embedder = _get_embedder()
        import numpy as np
        q_emb = embedder.encode([query], show_progress_bar=False)
        k = min(5, idx.ntotal)
        distances, indices = idx.search(np.array(q_emb, dtype="float32"), k)

        results = []
        for dist, i in zip(distances[0], indices[0]):
            if i < len(entries) and dist < 1.5:  # distance threshold
                results.append(entries[i])

        if not results:
            return {"message": "Nothing relevant found in memory.", "memories": []}

        lines = [f"• [{m['id']}] {m['text']} (saved {m['timestamp'][:10]})" for m in results]
        return {"message": "\n".join(lines), "memories": results}

    def _list(self) -> dict:
        _, entries = _get_memory_index()
        if not entries:
            return {"message": "No memories stored.", "memories": []}
        lines = [f"• [{m['id']}] {m['text']}" for m in entries[-20:]]  # last 20
        return {"message": "\n".join(lines), "memories": entries}

    def _forget(self, params: dict) -> dict:
        # FAISS doesn't support deletion, so we rebuild the index
        global _memory_index, _memory_entries
        mid = params["memory_id"]
        _, entries = _get_memory_index()

        new_entries = [e for e in entries if e["id"] != mid]
        if len(new_entries) == len(entries):
            return {"message": f"No memory with id {mid} found."}

        # Rebuild index
        import faiss
        import numpy as np
        new_index = faiss.IndexFlatL2(384)
        if new_entries:
            embedder = _get_embedder()
            texts = [e["text"] for e in new_entries]
            embs = embedder.encode(texts, show_progress_bar=False)
            new_index.add(np.array(embs, dtype="float32"))

        _memory_index = new_index
        _memory_entries = new_entries
        _save_memory()

        return {"message": f"Memory {mid} deleted."}


TOOL_CLASS = MemoryTool
