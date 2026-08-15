from __future__ import annotations

import re
import json
from pathlib import Path
from typing import List, Dict

import faiss
import numpy as np
import ollama
from collections import Counter
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

OUT_DIR = Path("output")
INDEX_PATH = OUT_DIR / "kb_index.faiss"
META_PATH = OUT_DIR / "kb_meta.json"
CHUNKS_PATH = OUT_DIR / "kb_chunks.json"
EMBED_MODEL = "nomic-embed-text"
CHAT_MODEL = "llama3.2"
TOP_K = 5
WORD_RE = re.compile(r"\b\w+\b")


console = Console()


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

def hybrid_search(index, chunks, query, embed_fn, k=5, keyword_weight=0.35, vector_weight=0.65):
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


def answer(index, chunks, question: str):
    results = hybrid_search(index, chunks, question, embed)
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


def render_results(results):
    table = Table(title="Final answer")
    table.add_column("Score", justify="right")
    table.add_column("Source", overflow="fold")
    table.add_column("Preview", overflow="fold")
    for r in results:
        preview = r["text"].replace("\n", " ")[:160]
        table.add_row(f"{r['score']:.3f}", r["path"], preview)
    console.print(table)


def run_cli():
    index, meta, chunks = load_state()
    console.print(Panel.fit("       KB Chatbot         ", subtitle="type /help for commands"))
    session = PromptSession()
    while True:
        q = session.prompt("Ask> ").strip()
        if q in {"exit", "quit", "q", "bye ", "ex"}:
            break
        if q == "/help" or q == "/?" or q == "/h":
            console.print("Commands: /help, /sources, /reindex, exit")
            continue
        if q == "/sources" or q == "/s":
            console.print(f"Files indexed: {len(meta.get('files', {}))}")
            continue
        if q == "/reindex" or q == "/r":
            console.print("Reindex by rerunning kb_watch_incremental.py or your indexer.")
            continue
        
        with console.status("Thinking..."):
            text, results = answer(index, chunks, q)
        # render_results(results)
        console.print(Panel(Text(text), title="Answer", expand=False))


if __name__ == "__main__":
    run_cli()