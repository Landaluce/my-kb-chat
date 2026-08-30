from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

import file_to_md
import kb_search


class NoCacheStaticFiles(StarletteStaticFiles):
    """Serve static files with no-cache so the browser always revalidates.

    The frontend changes often during development; without a cache policy the
    browser may keep serving stale app.js/style.css after a soft reload.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
KB_DIR = BASE_DIR / "kb"
NOTES_DIR = KB_DIR / "notes"
UPLOADS_DIR = KB_DIR / "uploads"

app = FastAPI(title="KB Chat")
app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")

NOTES_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "note"


def _unique_path(directory: Path, stem: str, suffix: str) -> Path:
    path = directory / f"{stem}{suffix}"
    n = 1
    while path.exists():
        path = directory / f"{stem}-{n}{suffix}"
        n += 1
    return path


def _resolve_kb_path(rel_path: str) -> Path:
    """Resolve and validate a path is a .md file inside kb/."""
    candidate = (KB_DIR / rel_path).resolve()
    try:
        candidate.relative_to(KB_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path is outside the KB")
    if candidate.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="Only .md files are readable")
    return candidate


def _to_rel(abs_path: str) -> str:
    """Turn an absolute kb path into a KB-relative path for /api/file."""
    try:
        return Path(abs_path).resolve().relative_to(KB_DIR.resolve()).as_posix()
    except ValueError:
        return abs_path


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str
    top_k: int = kb_search.DEFAULT_TOP_K
    history: List[ChatMessage] = Field(default_factory=list)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/api/health")
def health():
    try:
        kb_search.load_state()
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not-indexed"})


@app.get("/api/sources")
def sources():
    return {
        "files": [
            {"path": _to_rel(f["path"]), "chunks": f["chunks"]}
            for f in kb_search.file_summaries()
        ]
    }


@app.get("/api/reindex/status")
def reindex_status():
    return kb_search.reindex_status()


@app.post("/api/reindex")
def trigger_reindex():
    kb_search.start_reindex()
    return kb_search.reindex_status()


class FileUpdate(BaseModel):
    content: str


@app.get("/api/file")
def read_file(path: str):
    target = _resolve_kb_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    content = target.read_text(encoding="utf-8", errors="ignore")
    return {"path": str(target), "content": content}


@app.put("/api/file")
def update_file(path: str, req: FileUpdate):
    target = _resolve_kb_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    target.write_text(req.content, encoding="utf-8")
    kb_search.start_reindex()
    return {"path": str(target)}


@app.delete("/api/file")
def delete_file(path: str):
    target = _resolve_kb_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()
    kb_search.start_reindex()
    return {"path": str(target), "deleted": True}


class NoteRequest(BaseModel):
    title: str = ""
    content: str


@app.post("/api/ingest/note")
def ingest_note(req: NoteRequest):
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Note content is empty")
    title = req.title.strip() or "untitled"
    path = _unique_path(NOTES_DIR, _slugify(title), ".md")
    body = f"# {title}\n\n{content}\n"
    path.write_text(body, encoding="utf-8")
    kb_search.start_reindex()
    return {"path": str(path), "title": title}


def _extract_markdown(name: str, data: bytes) -> str:
    """Convert an uploaded file's bytes to markdown text (no disk write)."""
    ext = Path(name).suffix.lower()
    if ext in {".md", ".markdown"}:
        return data.decode("utf-8", errors="ignore")
    tmp_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = UPLOADS_DIR / tmp_name
    try:
        tmp_path.write_bytes(data)
        markdown = file_to_md.to_markdown(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return markdown


@app.post("/api/ingest/preview")
async def ingest_preview(file: UploadFile = File(...)):
    name = file.filename or "file"
    ext = Path(name).suffix.lower()
    if ext not in file_to_md.SUPPORTED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '<none>'}")
    markdown = _extract_markdown(name, await file.read())
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the file")
    return {"name": name, "markdown": markdown}


@app.post("/api/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)):
    name = file.filename or "file"
    ext = Path(name).suffix.lower()
    if ext not in file_to_md.SUPPORTED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '<none>'}")
    markdown = _extract_markdown(name, await file.read())
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the file")
    dest = _unique_path(UPLOADS_DIR, _slugify(Path(name).stem or "upload"), ".md")
    dest.write_text(markdown, encoding="utf-8")
    kb_search.start_reindex()
    return {"path": str(dest)}


@app.post("/api/chat")
def chat(req: ChatRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")
    start = time.time()
    try:
        text, results = kb_search.answer(question, k=req.top_k, history=[m.dict() for m in req.history])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "answer": text,
        "sources": [
            {
                "path": r["path"],
                "rel_path": _to_rel(r["path"]),
                "score": r["score"],
                "preview": r["text"][:200],
            }
            for r in results
        ],
        "latency_ms": int((time.time() - start) * 1000),
    }


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")
    start = time.time()

    def gen():
        try:
            for payload in kb_search.chat_stream_events(
                question, k=req.top_k, history=[m.dict() for m in req.history]
            ):
                if payload["type"] == "done":
                    payload = {
                        "type": "done",
                        "sources": [
                            {
                                "path": r["path"],
                                "rel_path": _to_rel(r["path"]),
                                "score": r["score"],
                                "preview": r["text"][:200],
                            }
                            for r in payload["results"]
                        ],
                        "latency_ms": int((time.time() - start) * 1000),
                    }
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
