from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import file_to_md
import kb_search

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
KB_DIR = BASE_DIR / "kb"
NOTES_DIR = KB_DIR / "notes"
UPLOADS_DIR = KB_DIR / "uploads"

app = FastAPI(title="KB Chat")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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

app = FastAPI(title="KB Chat")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    question: str
    top_k: int = kb_search.DEFAULT_TOP_K


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    try:
        kb_search.load_state()
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not-indexed"})


@app.get("/api/sources")
def sources():
    return {"files": kb_search.file_summaries()}


@app.get("/api/reindex/status")
def reindex_status():
    return kb_search.reindex_status()


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


@app.post("/api/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)):
    name = file.filename or "file"
    ext = Path(name).suffix.lower()
    if ext not in file_to_md.SUPPORTED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '<none>'}")
    if ext in {".md", ".markdown"}:
        stem = Path(name).stem
        raw = (await file.read()).decode("utf-8", errors="ignore")
        dest = _unique_path(UPLOADS_DIR, _slugify(stem or "upload"), ".md")
        dest.write_text(raw, encoding="utf-8")
    else:
        tmp_name = f"{uuid.uuid4().hex}{ext}"
        tmp_path = UPLOADS_DIR / tmp_name
        tmp_path.write_bytes(await file.read())
        try:
            markdown = file_to_md.to_markdown(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
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
        text, results = kb_search.answer(question, k=req.top_k)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "answer": text,
        "sources": [
            {"path": r["path"], "score": r["score"], "preview": r["text"][:200]}
            for r in results
        ],
        "latency_ms": int((time.time() - start) * 1000),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
