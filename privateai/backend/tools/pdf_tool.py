"""
PDF tool — read, chunk, embed, and query PDF documents.
Uses PyMuPDF for extraction + FAISS for local vector search.
No cloud. Embeddings computed locally via sentence-transformers.
"""

import os
import json
import pickle
import hashlib
import logging
from typing import Optional
from pathlib import Path

from .base_tool import BaseTool, ToolError

logger = logging.getLogger(__name__)

VECTOR_STORE_DIR = os.path.expanduser("~/.privateai/vector_store")
CHUNK_SIZE = 400        # tokens approx (chars / 4)
CHUNK_OVERLAP = 50
TOP_K = 4

# Lazy-loaded globals
_embedder = None
_faiss_index = None
_faiss_chunks = []  # parallel list: chunk text + source metadata


def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Sentence transformer loaded")
        except ImportError:
            raise ToolError(
                "sentence-transformers not installed. Run: pip install sentence-transformers"
            )
    return _embedder


def _get_faiss():
    """Load or create FAISS index from disk."""
    global _faiss_index, _faiss_chunks
    os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
    index_path = os.path.join(VECTOR_STORE_DIR, "index.faiss")
    chunks_path = os.path.join(VECTOR_STORE_DIR, "chunks.pkl")

    if _faiss_index is None:
        if os.path.exists(index_path) and os.path.exists(chunks_path):
            import faiss
            _faiss_index = faiss.read_index(index_path)
            with open(chunks_path, "rb") as f:
                _faiss_chunks = pickle.load(f)
            logger.info(f"FAISS index loaded: {_faiss_index.ntotal} vectors")
        else:
            import faiss
            _faiss_index = faiss.IndexFlatL2(384)  # all-MiniLM output dim
            _faiss_chunks = []

    return _faiss_index, _faiss_chunks


def _save_faiss():
    import faiss
    idx, chunks = _faiss_index, _faiss_chunks
    os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
    faiss.write_index(idx, os.path.join(VECTOR_STORE_DIR, "index.faiss"))
    with open(os.path.join(VECTOR_STORE_DIR, "chunks.pkl"), "wb") as f:
        pickle.dump(chunks, f)


def _chunk_text(text: str, source: str) -> list[dict]:
    """Split text into overlapping chunks."""
    words = text.split()
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for i in range(0, len(words), step):
        chunk_words = words[i:i + CHUNK_SIZE]
        chunks.append({
            "text": " ".join(chunk_words),
            "source": source,
            "chunk_index": len(chunks),
        })
    return chunks


class PDFTool(BaseTool):
    name = "pdf"
    description = (
        "Open a PDF file and answer questions about it. "
        "Can index a PDF for semantic search, then query it. "
        "Operations: index (load+embed a PDF), query (ask a question), list (show indexed docs)."
    )
    requires_confirmation = False
    schema = {
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["index", "query", "list"],
                "description": "index = load PDF into memory, query = ask a question, list = show indexed files",
            },
            "file_path": {"type": "string", "description": "Absolute path to PDF file"},
            "question": {"type": "string", "description": "Question to ask about the document"},
        },
        "required": ["operation"],
    }

    def validate(self, params: dict) -> Optional[str]:
        op = params.get("operation")
        if not op:
            return "'operation' is required"
        if op == "index" and not params.get("file_path"):
            return "'file_path' is required"
        if op == "query" and not params.get("question"):
            return "'question' is required"
        return None

    def execute(self, params: dict) -> dict:
        op = params["operation"]
        if op == "index":
            return self._index(params)
        elif op == "query":
            return self._query(params)
        elif op == "list":
            return self._list()
        raise ToolError(f"Unknown operation: {op}")

    def _index(self, params: dict) -> dict:
        path = params["file_path"]
        if not os.path.exists(path):
            raise ToolError(f"File not found: {path}")

        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ToolError("PyMuPDF not installed. Run: pip install pymupdf")

        doc = fitz.open(path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()

        if not full_text.strip():
            raise ToolError("Could not extract text from PDF (may be scanned/image-based).")

        source = os.path.basename(path)
        chunks = _chunk_text(full_text, source)

        embedder = _get_embedder()
        texts = [c["text"] for c in chunks]
        embeddings = embedder.encode(texts, show_progress_bar=False)

        import numpy as np
        idx, stored_chunks = _get_faiss()
        idx.add(np.array(embeddings, dtype="float32"))
        stored_chunks.extend(chunks)
        _save_faiss()

        return {
            "message": f"Indexed '{source}': {len(chunks)} chunks, {len(full_text)} chars. Ready to answer questions.",
            "chunks_added": len(chunks),
            "source": source,
        }

    def _query(self, params: dict) -> dict:
        question = params["question"]

        idx, stored_chunks = _get_faiss()
        if idx.ntotal == 0:
            return {"message": "No documents indexed yet. Use 'index' operation first."}

        embedder = _get_embedder()
        import numpy as np
        q_emb = embedder.encode([question], show_progress_bar=False)
        distances, indices = idx.search(np.array(q_emb, dtype="float32"), TOP_K)

        relevant = []
        for i in indices[0]:
            if i < len(stored_chunks):
                relevant.append(stored_chunks[i])

        if not relevant:
            return {"message": "No relevant content found in indexed documents."}

        context = "\n\n---\n\n".join(c["text"] for c in relevant)
        sources = list({c["source"] for c in relevant})

        return {
            "message": f"Found relevant content in: {', '.join(sources)}",
            "context": context,
            "sources": sources,
            "note": "Use this context to answer the question. The LLM will receive it.",
            # The orchestrator can pass this context back to LLM for a follow-up answer
        }

    def _list(self) -> dict:
        _, stored_chunks = _get_faiss()
        if not stored_chunks:
            return {"message": "No documents indexed.", "sources": []}
        sources = list({c["source"] for c in stored_chunks})
        counts = {s: sum(1 for c in stored_chunks if c["source"] == s) for s in sources}
        lines = [f"• {s} ({counts[s]} chunks)" for s in sources]
        return {"message": "\n".join(lines), "sources": sources}


TOOL_CLASS = PDFTool
