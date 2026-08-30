# KB Chat

A local, RAG-style knowledge-base chatbot. Ask questions in natural language and get
answers grounded in your own Markdown notes and documents — all running locally with
no external APIs. Content is chunked, embedded, searched with a hybrid (vector +
keyword) index, and answered by an LLM served through [Ollama](https://ollama.com/).

## Features

- **Web UI** (FastAPI + vanilla JS) with streaming answers, source citations, file
  browsing/editing, note creation, and drag-and-drop upload that converts PDFs,
  DOCX, videos, etc. to Markdown.
- **CLI** (`chat.py`) for quick terminal Q&A.
- **Hybrid search** across the knowledge base combining FAISS vector similarity with
  a fuzzy keyword overlap score.
- **Incremental watcher** (`kb_watch_incremental.py`) that re-embeds files as they
  change, and a background/blocking reindex for bulk changes.
- **Everything runs locally** — embeddings (`nomic-embed-text`) and chat
  (`llama3.2` by default) via Ollama.

## Architecture

```bash
kb/                      Your knowledge base (gitignored)
  notes/...              Plain Markdown notes, organized by topic
  uploads/ ...           Files converted to .md on upload
output/                  Generated search index (gitignored)
  kb_index.faiss         FAISS vectors
  kb_chunks.json         Chunk texts + metadata
  kb_meta.json           File → chunk-id map
static/                  Web UI (index.html, app.js, style.css, render.js)
chat.py                  CLI entry point
web_app.py               FastAPI server (REST + SSE)
kb_search.py             Index loading, hybrid search, chat/stream generation
index_kb.py              Full (blocking) reindex
kb_watch_incremental.py  Watch kb/ and update the index incrementally
file_to_md.py            File → Markdown conversion for uploads
make_favicon.py          Regenerate static/favicon.ico
```

Answer flow: a query is embedded and searched against the index, the top matching
chunks are assembled into a prompt (bounded by `MAX_CONTEXT_CHARS`), and the LLM
streams a grounded answer. If the model returns a short, whole-answer refusal, the
search retries once with a broader net.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) running locally
- The embedding and chat models pulled:

```bash
ollama pull nomic-embed-text
ollama pull llama3.2   # or set KB_CHAT_MODEL to any installed model
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build the index from your kb/ docs
python index_kb.py

# (Optional) keep the index fresh as files change
python kb_watch_incremental.py
```

## Usage

### Web UI

```bash
python web_app.py
# open http://127.0.0.1:8000
```

Or run with uvicorn directly:

```bash
uvicorn web_app:app --host 127.0.0.1 --port 8000
```

### CLI

```bash
python chat.py
# commands: /help, /sources, /reindex, exit
```

### Tests

The Markdown renderer has unit tests (Node `node:test`):

```bash
node --test render.test.js
```

## API summary

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Non-streaming answer with sources |
| `POST` | `/api/chat/stream` | SSE streamed answer (`token` / `reset` / `done` / `error`) |
| `GET` | `/api/sources` | List indexed files and chunk counts |
| `GET` / `PUT` / `DELETE` | `/api/file?path=` | Read / edit / delete a `.md` file |
| `POST` | `/api/ingest/note` | Create a plain note |
| `POST` | `/api/ingest/upload` | Upload a file, convert to `.md`, save |
| `POST` | `/api/ingest/preview` | Upload a file, return extracted Markdown without saving |
| `POST` | `/api/reindex` | Rebuild the index in the background |
| `GET` | `/api/reindex/status` | Background reindex progress |
| `GET` | `/api/health` | Health check |

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `KB_CHAT_MODEL` | `llama3.2` | Chat model |
| `KB_CHAT_NUM_CTX` | `8192` | LLM context window |
| `KB_TOP_K` | `5` | Files pulled into the prompt |
| `KB_MAX_CONTEXT_CHARS` | `12000` | Max prompt text fed to the LLM |

## Notes

- `kb/` and `output/` are intentionally gitignored — your knowledge base stays
  private and out of version control.
- The web UI is served with `no-cache` headers, so a hard reload picks up JS/CSS
  changes.
- Chat/embed responses stream from Ollama; generation speed depends on your GPU
  and whether the models are already resident in memory.