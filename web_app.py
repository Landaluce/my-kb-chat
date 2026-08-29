from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kb_search

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

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
