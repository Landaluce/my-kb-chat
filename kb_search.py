from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import faiss
import numpy as np
import ollama

OUT_DIR = Path("output")
INDEX_PATH = OUT_DIR / "kb_index.faiss"
META_PATH = OUT_DIR / "kb_meta.json"
CHUNKS_PATH = OUT_DIR / "kb_chunks.json"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = os.environ.get("KB_CHAT_MODEL", "llama3.2")
FALLBACK_CHAT_MODEL = "llama3.2"
CHAT_NUM_CTX = int(os.environ.get("KB_CHAT_NUM_CTX", "8192"))
# Fewer chunks in the prompt -> less prompt processing before the first token.
DEFAULT_TOP_K = int(os.environ.get("KB_TOP_K", "5"))
WORD_RE = re.compile(r"\b\w+\b")
FUZZY_CUTOFF = 0.6

# Canonical chunking settings shared by index_kb and kb_watch_incremental.
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Upper bound on the total text length fed to the LLM. Smaller prompt = faster
# prompt processing before the first token (~12k chars ≈ 3k tokens).
MAX_CONTEXT_CHARS = int(os.environ.get("KB_MAX_CONTEXT_CHARS", "12000"))

DONT_KNOW_RE = re.compile(
    r"\b(?:"
    r"i\s+don'?t\s+know"
    r"|i\s+do\s+not\s+know"
    r"|(?:can'?t|cannot)\s+(?:find|answer|determine)"
    r"|not\s+(?:present|found|mentioned|mention|included|covered|available|contained)"
    r"|no\s+(?:information|mention|reference|evidence|record)"
    r"|(?:doesn'?t|does\s+not)\s+(?:mention|contain|include|say)"
    r"|unable\s+to\s+(?:find|answer|determine)"
    r")\b",
    re.IGNORECASE,
)

_keyword_cache = {"fingerprint": None, "docs": None}


_state_cache = {"fp": None, "index": None, "meta": None, "chunks": None}


def _state_fingerprint():
    parts = []
    for p in (INDEX_PATH, META_PATH, CHUNKS_PATH):
        try:
            st = p.stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except FileNotFoundError:
            parts.append("missing")
    return tuple(parts)


def load_state():
    """Load the index, caching it in memory until the files change on disk."""
    cached = _state_cache
    if cached["fp"] == _state_fingerprint() and cached["index"] is not None:
        return cached["index"], cached["meta"], cached["chunks"]
    index = faiss.read_index(str(INDEX_PATH))
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    cached.update(fp=_state_fingerprint(), index=index, meta=meta, chunks=chunks)
    return index, meta, chunks


def embed(text: str):
    resp = ollama.embed(model=EMBED_MODEL, input=text)
    return np.array(resp["embeddings"][0], dtype="float32")


def tokenize(text: str):
    return WORD_RE.findall(text.lower())


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Canonical chunker shared by index_kb and kb_watch_incremental."""
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return []
    out = []
    i = 0
    step = max(1, size - overlap)
    while i < len(text):
        chunk = text[i:i + size].strip()
        if chunk:
            out.append(chunk)
        i += step
    return out


def build_keyword_index(chunks):
    """Map chunk_id -> token list. Keyed by id (not position) because
    incremental indexes can have sparse chunk ids."""
    docs = {}
    for c in chunks:
        text = f"{c.get('path', '')} {c.get('text', '')}".lower()
        docs[c["chunk_id"]] = tokenize(text)
    return docs


def get_keyword_index(chunks):
    """Tokenized chunk corpus, reused across queries until the corpus changes."""
    fp = hash(tuple(c.get("text", "") for c in chunks))
    if _keyword_cache["fingerprint"] != fp:
        _keyword_cache["fingerprint"] = fp
        _keyword_cache["docs"] = build_keyword_index(chunks)
    return _keyword_cache["docs"]


def keyword_score(query: str, doc_tokens):
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.0
    d = Counter(doc_tokens)
    total = 0.0
    for qt in q_tokens:
        if d[qt] > 0:
            total += 1.0
            continue
        best = 0.0
        for dt in d:
            # Quick rejection: wildly different lengths can't clear the fuzzy
            # cutoff, and this skips most candidate tokens cheaply.
            if abs(len(qt) - len(dt)) > 2:
                continue
            sim = SequenceMatcher(None, qt, dt).ratio()
            if sim > best:
                best = sim
        if best >= FUZZY_CUTOFF:
            total += best
    return total / len(q_tokens)


def _score_chunk(index, qv, query, chunk, keyword_docs, keyword_weight, vector_weight):
    """Score one chunk by exact vector similarity plus keyword overlap."""
    cid = chunk["chunk_id"]
    try:
        v = index.reconstruct(int(cid))
        vec_score = float(np.dot(qv[0], v))
    except Exception:
        vec_score = 0.0
    kw_score = keyword_score(query, keyword_docs[cid])
    return (vector_weight * vec_score + keyword_weight * kw_score, vec_score, kw_score, cid)


def hybrid_search(index, chunks, query, embed_fn=embed, k=DEFAULT_TOP_K,
                  keyword_weight=0.35, vector_weight=0.65,
                  pool_factor=8, neighbor_expand=1, keyword_docs=None):
    """Two-pass, file-aware hybrid search.

    Pass 1 pulls a broad FAISS candidate pool. Pass 2 re-scores *every* chunk
    of the candidate files and keeps the best chunk per file, so a file is
    surfaced even when its best chunk missed the raw top-k. Neighboring chunks
    are included to cover answers split across chunk boundaries. Chunk lookups
    go through a chunk_id map because incremental indexes can have sparse ids.
    """
    if not chunks:
        return []

    qv = embed_fn(query).reshape(1, -1)
    faiss.normalize_L2(qv)

    if keyword_docs is None:
        keyword_docs = get_keyword_index(chunks)

    by_id = {c["chunk_id"]: c for c in chunks}
    by_path = {}
    pos_in_file = {}
    for c in chunks:
        by_path.setdefault(c["path"], []).append(c)
        pos_in_file[c["chunk_id"]] = len(by_path[c["path"]]) - 1

    n_chunks = len(chunks)
    candidate_k = min(max(k * pool_factor, k), n_chunks)
    scores, ids = index.search(qv, candidate_k)

    # Pass 1: score the raw FAISS pool.
    candidates = []
    for rank, idx in enumerate(ids[0]):
        if idx == -1:
            continue
        vec_score = float(scores[0][rank])
        kw_score = keyword_score(query, keyword_docs[idx])
        final_score = vector_weight * vec_score + keyword_weight * kw_score
        candidates.append((final_score, vec_score, kw_score, idx))
    candidates.sort(reverse=True, key=lambda x: x[0])

    # Candidate files, in rank order, capped at 2*k.
    seen = set()
    ordered_paths = []
    for _, _, _, idx in candidates:
        p = by_id[idx]["path"]
        if p not in seen:
            seen.add(p)
            ordered_paths.append(p)
        if len(ordered_paths) >= max(k * 2, k):
            break

    # Pass 2: re-score every chunk of the candidate files.
    file_ranked = {}
    file_best = {}
    for p in ordered_paths:
        ranked = [
            _score_chunk(index, qv, query, c, keyword_docs, keyword_weight, vector_weight)
            for c in by_path[p]
        ]
        ranked.sort(reverse=True, key=lambda x: x[0])
        if ranked:
            file_ranked[p] = ranked
            file_best[p] = ranked[0]

    # Final selection: top files' best chunks, then neighbor chunks for
    # boundary coverage, bounded by MAX_CONTEXT_CHARS.
    top_files = sorted(file_best, key=lambda p: file_best[p][0], reverse=True)[:k]

    results = []
    used = set()
    total_chars = 0
    for p in top_files:
        ranked = file_ranked[p]
        by_id_in_file = {cand[3]: cand for cand in ranked}
        chosen = ranked[0]
        candidates_for_file = [chosen]
        chosen_pos = pos_in_file[chosen[3]]
        for dist in range(1, neighbor_expand + 1):
            for offset in (-dist, dist):
                npos = chosen_pos + offset
                if 0 <= npos < len(by_path[p]):
                    cand = by_id_in_file.get(by_path[p][npos]["chunk_id"])
                    if cand is not None and cand[3] not in used:
                        candidates_for_file.append(cand)
        for cand in candidates_for_file:
            if cand[3] in used:
                continue
            extra = len(by_id[cand[3]]["text"]) + 64  # room for the source line
            if total_chars + extra > MAX_CONTEXT_CHARS:
                continue
            results.append(cand)
            used.add(cand[3])
            total_chars += extra

    results.sort(reverse=True, key=lambda x: x[0])
    out = []
    for final_score, vec_score, kw_score, idx in results:
        out.append({
            "score": final_score,
            "vector_score": vec_score,
            "keyword_score": kw_score,
            **by_id[idx],
        })
    return out


def build_context(results):
    parts = []
    for r in results:
        parts.append(f"Source: {r['path']}\n{r['text']}")
    return "\n\n".join(parts)


def _build_messages(question: str, context: str, history=None):
    prompt = f"""Answer using only the context below. If the answer is not present, say you don't know.

Context:
{context}

Question: {question}"""
    messages = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in (history or [])
    ]
    messages.append({"role": "user", "content": prompt})
    return messages


def _chat_stream_gen(question: str, context: str, model: str = CHAT_MODEL, history=None):
    """Yield answer tokens from the chat model, with fallback to the base model."""
    messages = _build_messages(question, context, history)
    try:
        stream = ollama.chat(model=model, messages=messages, stream=True,
                             options={"num_ctx": CHAT_NUM_CTX})
    except Exception:
        if model != FALLBACK_CHAT_MODEL:
            # KB_CHAT_MODEL may point at a model that isn't pulled; fall back.
            stream = ollama.chat(model=FALLBACK_CHAT_MODEL, messages=messages, stream=True,
                                 options={"num_ctx": CHAT_NUM_CTX})
        else:
            raise
    for chunk in stream:
        yield chunk["message"]["content"]


def _chat(question: str, context: str, model: str = CHAT_MODEL, history=None):
    return "".join(_chat_stream_gen(question, context, model=model, history=history))


def _is_full_refusal(text: str) -> bool:
    """True when the model gave a short, whole-answer refusal (as opposed to a
    long answer that merely mentions missing info in passing). Only these
    trigger the expensive broader-search retry."""
    return len(text) < 200 and DONT_KNOW_RE.search(text)


def answer(question: str, k=DEFAULT_TOP_K, history=None):
    index, meta, chunks = load_state()
    results = hybrid_search(index, chunks, question, k=k)
    text = _chat(question, build_context(results), history=history)
    if results and _is_full_refusal(text):
        # The retrieved chunks missed the answer: retry once with a broader
        # net (more files + more neighbor chunks).
        results = hybrid_search(index, chunks, question, k=max(k + 2, 10), neighbor_expand=2)
        text = _chat(question, build_context(results), history=history)
    return text, results


def chat_stream_events(question: str, k=DEFAULT_TOP_K, history=None):
    """Yield event payloads for SSE streaming: token / reset / done.

    "done" carries the raw results; the web layer formats them into sources.
    """
    index, meta, chunks = load_state()
    results = hybrid_search(index, chunks, question, k=k)
    context = build_context(results)
    parts = []
    for delta in _chat_stream_gen(question, context, history=history):
        parts.append(delta)
        yield {"type": "token", "text": delta}
    text = "".join(parts)
    if results and _is_full_refusal(text):
        # First pass missed the answer; reset the message and retry broader.
        yield {"type": "reset"}
        results = hybrid_search(index, chunks, question, k=max(k + 2, 10), neighbor_expand=2)
        context = build_context(results)
        for delta in _chat_stream_gen(question, context, history=history):
            yield {"type": "token", "text": delta}
    yield {"type": "done", "results": results}


def file_summaries():
    try:
        _, meta, _ = load_state()
    except Exception:
        return []
    return [
        {"path": path, "chunks": len(ids)}
        for path, ids in meta.get("files", {}).items()
    ]


def reindex() -> None:
    """Rebuild the full index from existing kb/ files (blocking)."""
    import index_kb

    index_kb.main()


# --- Background reindex state ------------------------------------------
_reindex_lock = threading.Lock()
_reindex_state = {
    "running": False,
    "finished_at": None,
    "error": None,
}


def _run_bg():
    global _reindex_state
    with _reindex_lock:
        _reindex_state["running"] = True
        _reindex_state["error"] = None
    try:
        reindex()
        err = None
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
    with _reindex_lock:
        _reindex_state["running"] = False
        _reindex_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        _reindex_state["error"] = err


def start_reindex() -> None:
    """Rebuild the index in a background thread if not already running."""
    with _reindex_lock:
        if _reindex_state["running"]:
            return
        _reindex_state["running"] = True
        _reindex_state["finished_at"] = None
        _reindex_state["error"] = None
    threading.Thread(target=_run_bg, daemon=True).start()


def reindex_status() -> dict:
    with _reindex_lock:
        return dict(_reindex_state)
