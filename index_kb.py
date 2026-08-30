from pathlib import Path
import json
import numpy as np
import faiss
import ollama

from kb_search import chunk_text, read_text

KB_DIR = Path("kb")
OUT_DIR = Path("output")
OUT_DIR.mkdir(exist_ok=True)

EMBED_MODEL = "nomic-embed-text"

def embed(text: str):
    resp = ollama.embed(model=EMBED_MODEL, input=text)
    return resp["embeddings"][0]

def main():
    items = []
    meta = {"files": {}, "next_id": 0}
    for path in KB_DIR.rglob("*.md"):
        text = read_text(path)
        file_ids = []
        for idx, chunk in enumerate(chunk_text(text)):
            cid = meta["next_id"]
            meta["next_id"] += 1
            file_ids.append(cid)
            items.append({
                "path": str(path),
                "chunk_id": cid,
                "text": chunk
            })
        meta["files"][str(path)] = file_ids

    vectors = np.array([embed(x["text"]) for x in items], dtype="float32")
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)

    faiss.normalize_L2(vectors)
    index.add(vectors)

    faiss.write_index(index, str(OUT_DIR / "kb_index.faiss"))
    (OUT_DIR / "kb_chunks.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "kb_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
