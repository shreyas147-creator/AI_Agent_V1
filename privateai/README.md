# PrivateAI

A local-only, offline AI assistant. No cloud. No telemetry. Your data stays on your machine.

## What it can do (v0.1)

- **Calendar** — create, list, update, delete events (SQLite)
- **Reminders** — schedule OS notifications via APScheduler
- **Email** — draft → review → confirm → send (SMTP/IMAP, confirmation required)
- **PDF reader** — index PDFs with FAISS + sentence-transformers, ask questions
- **Memory** — store/recall facts via semantic vector search

---

## Setup (5 minutes)

### 1. Install Ollama + model

```bash
# Install Ollama: https://ollama.com
ollama pull gemma2:2b       # ~1.6GB, fast
# or: ollama pull gemma2:4b for better reasoning (~2.5GB)
```

### 2. Start Ollama

```bash
ollama serve
```

### 3. Install Python deps

```bash
cd backend
pip install -r requirements.txt
```

### 4. Start backend

```bash
cd backend
python main.py
```

### 5. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Open: **http://localhost:5173**

Or run both at once:

```bash
./scripts/start.sh
```

---

## Email setup (optional)

Create `~/.privateai/email_config.json`:

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "imap_host": "imap.gmail.com",
  "username": "you@gmail.com",
  "password": "your-app-password",
  "from_address": "you@gmail.com"
}
```

For Gmail: use an [App Password](https://myaccount.google.com/apppasswords), not your main password.

---

## Architecture

```
User → Frontend (React/Vite)
         ↓ HTTP
     Backend (FastAPI)
         ↓
     Orchestrator          ← brain wrapper
     ├── LLMClient         ← Ollama or llama.cpp
     ├── ToolRegistry      ← plugin system
     └── ShortTermMemory   ← last 10 turns (in-process)
         ↓
     Tools:
     ├── calendar_tool     → SQLite
     ├── reminders_tool    → SQLite + APScheduler
     ├── email_tool        → SMTP/IMAP (confirm required)
     ├── pdf_tool          → PyMuPDF + FAISS
     └── memory_tool       → FAISS
```

**The LLM outputs JSON only. It never directly executes anything.**

```
LLM → {"action": "calendar", "params": {...}}
                    ↓
         Orchestrator validates
                    ↓
         Tool executes (or waits for confirmation)
```

---

## Configuration

Environment variables (set before starting backend):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BACKEND` | `ollama` | `ollama` or `llamacpp` |
| `OLLAMA_MODEL` | `gemma2:2b` | Any model in your Ollama registry |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `LLAMACPP_PATH` | `./llama.cpp/main` | Path to llama.cpp binary |
| `LLAMACPP_MODEL_PATH` | `./models/...gguf` | Path to GGUF model |
| `LLM_TIMEOUT` | `30` | Seconds before LLM timeout |

---

## Data locations

All data is stored locally:

| What | Where |
|------|-------|
| SQLite DB | `~/.privateai/privateai.db` |
| FAISS vector index (PDF) | `~/.privateai/vector_store/` |
| FAISS vector index (memory) | `~/.privateai/memory_store/` |
| Email config | `~/.privateai/email_config.json` |

To delete everything: `DELETE /data/all` endpoint, or just delete `~/.privateai/`.

---

## Adding a new tool

1. Create `backend/tools/your_tool.py`
2. Subclass `BaseTool`, set `name`, `description`, `schema`
3. Implement `execute(params) -> dict`
4. Set `TOOL_CLASS = YourTool` at the bottom
5. Add `"tools.your_tool"` to `TOOL_MODULES` in `tools/registry.py`

That's it. The LLM will automatically see the new tool via the schema.

---

## Switching to llama.cpp

```bash
export LLM_BACKEND=llamacpp
export LLAMACPP_PATH=/path/to/llama.cpp/main
export LLAMACPP_MODEL_PATH=/path/to/gemma-2b-q4_k_m.gguf
python main.py
```

Download GGUF models from: https://huggingface.co/bartowski

---

## Known limitations (v0.1)

- Small models (2B/4B) sometimes output malformed JSON → orchestrator retries gracefully
- PDF tool requires sentence-transformers (~400MB first download)
- Voice input not included (adds failure modes, text-first)
- No mobile app yet
