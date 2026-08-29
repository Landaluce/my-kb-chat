from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import List

import faiss
import numpy as np
import ollama

OUT_DIR = Path("output")
INDEX_PATH = OUT_DIR / "kb_index.faiss"
META_PATH = OUT_DIR / "kb_meta.json"
CHUNKS_PATH = OUT_DIR / "kb_chunks.json"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "llama3.2"
DEFAULT_TOP_K = 5
WORD_RE = re.compile(r"\b\w+\b")


def load_state():
    index = faiss.read_index(str(INDEX_PATH))
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    return index, meta, chunks


def embed(text: str):
    resp = ollama.embed(model=EMBED_MODEL, input=text)
    return np.array(resp["embeddings"][0], dtype="float32")


def tokenize(text: str):
    return WORD_RE.findall(text.lower())


def build_keyword_index(chunks):
    docs = []
    for c in chunks:
        text = f"{c.get('path','')} {c.get('text','')}".lower()
        docs.append(tokenize(text))
    return docs


def keyword_score(query: str, doc_tokens):
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.0
    q = Counter(q_tokens)
    d = Counter(doc_tokens)
    overlap = sum(min(q[t], d[t]) for t in q)
    return overlap / len(q_tokens)


def hybrid_search(index, chunks, query, embed_fn=embed, k=DEFAULT_TOP_K, keyword_weight=0.35, vector_weight=0.65):
    qv = embed_fn(query).reshape(1, -1)
    faiss.normalize_L2(qv)
    scores, ids = index.search(qv, min(max(k * 4, k), len(chunks)))

    doc_tokens = build_keyword_index(chunks)
    candidates = []
    for rank, idx in enumerate(ids[0]):
        if idx == -1:
            continue
        vec_score = float(scores[0][rank])
        kw_score = keyword_score(query, doc_tokens[idx])
        final_score = vector_weight * vec_score + keyword_weight * kw_score
        candidates.append((final_score, vec_score, kw_score, idx))

    candidates.sort(reverse=True, key=lambda x: x[0])
    results = []
    for final_score, vec_score, kw_score, idx in candidates[:k]:
        c = chunks[idx]
        results.append({
            "score": final_score,
            "vector_score": vec_score,
            "keyword_score": kw_score,
            **c,
        })
    return results


def build_context(results):
    parts = []
    for r in results:
        parts.append(f"Source: {r['path']}\n{r['text']}")
    return "\n\n".join(parts)


def answer(question: str, k=DEFAULT_TOP_K):
    index, meta, chunks = load_state()
    results = hybrid_search(index, chunks, question, k=k)
    context = build_context(results)
    prompt = f"""Answer using only the context below. If the answer is not present, say you don't know.

Context:
{context}

Question: {question}"""
    resp = ollama.chat(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp["message"]["content"], results


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
