from pathlib import Path
import json
import re
import numpy as np
import faiss
import ollama

KB_DIR = Path("kb")
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
EMBED_MODEL = "nomic-embed-text"

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i:i+size]
        if chunk.strip():
            chunks.append(chunk)
        i += size - overlap
    return chunks

def embed(text: str):
    resp = ollama.embed(model=EMBED_MODEL, input=text)
    return resp["embeddings"][0]

def main():
    items = []
    for path in KB_DIR.rglob("*.md"):
        text = read_text(path)
        for idx, chunk in enumerate(chunk_text(text)):
            items.append({
                "path": str(path),
                "chunk_id": idx,
                "text": chunk
            })

    vectors = np.array([embed(x["text"]) for x in items], dtype="float32")
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)

    faiss.normalize_L2(vectors)
    index.add(vectors)

    faiss.write_index(index, str(OUT_DIR / "kb_index.faiss"))
    (OUT_DIR / "kb_chunks.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
