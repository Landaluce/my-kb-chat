from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Lock

import faiss
import numpy as np
import ollama
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

KB_DIR = Path('kb')
OUT_DIR = Path('output')
OUT_DIR.mkdir(exist_ok=True)

INDEX_PATH = OUT_DIR / 'kb_index.faiss'
META_PATH = OUT_DIR / 'kb_meta.json'
CHUNKS_PATH = OUT_DIR / 'kb_chunks.json'
EMBED_MODEL = 'nomic-embed-text'

from kb_search import chunk_text, read_text

lock = Lock()

@dataclass
class ChunkRecord:
    chunk_id: int
    path: str
    text: str


def embed_texts(texts):
    resp = ollama.embed(model=EMBED_MODEL, input=texts)
    return np.array(resp['embeddings'], dtype='float32')


def new_index(dim: int):
    base = faiss.IndexFlatIP(dim)
    return faiss.IndexIDMap2(base)


def normalize(v):
    faiss.normalize_L2(v)
    return v


def load_state():
    if INDEX_PATH.exists() and META_PATH.exists() and CHUNKS_PATH.exists():
        index = faiss.read_index(str(INDEX_PATH))
        meta = json.loads(META_PATH.read_text(encoding='utf-8'))
        chunks = json.loads(CHUNKS_PATH.read_text(encoding='utf-8'))
        return index, meta, chunks
    return None, {'files': {}, 'next_id': 1}, []


def save_state(index, meta, chunks):
    faiss.write_index(index, str(INDEX_PATH))
    META_PATH.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    CHUNKS_PATH.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding='utf-8')


def rebuild_all():
    records = []
    ids = []
    texts = []
    meta = {'files': {}, 'next_id': 1}

    md_files = sorted(KB_DIR.rglob('*.md'))
    for path in md_files:
        file_text = read_text(path)
        file_chunks = chunk_text(file_text)
        file_ids = []
        for c in file_chunks:
            cid = meta['next_id']
            meta['next_id'] += 1
            file_ids.append(cid)
            ids.append(cid)
            texts.append(c)
            records.append(asdict(ChunkRecord(cid, str(path), c)))
        meta['files'][str(path)] = file_ids

    if not texts:
        index = new_index(384)
        save_state(index, meta, records)
        return index, meta, records

    vecs = normalize(embed_texts(texts))
    dim = vecs.shape[1]
    index = new_index(dim)
    index.add_with_ids(vecs, np.array(ids, dtype='int64'))
    save_state(index, meta, records)
    return index, meta, records


def remove_file(index, meta, chunks, path_str: str):
    ids = meta['files'].pop(path_str, [])
    if not ids:
        return index, meta, chunks
    sel = faiss.IDSelectorBatch(np.array(ids, dtype='int64'))
    try:
        index.remove_ids(sel)
    except Exception:
        return rebuild_all()
    chunks = [c for c in chunks if c['chunk_id'] not in set(ids)]
    return index, meta, chunks


def add_or_update_file(index, meta, chunks, path: Path):
    path_str = str(path)
    index, meta, chunks = remove_file(index, meta, chunks, path_str)
    if not path.exists() or path.suffix.lower() != '.md':
        return index, meta, chunks

    text = read_text(path)
    file_chunks = chunk_text(text)
    if not file_chunks:
        meta['files'][path_str] = []
        return index, meta, chunks

    ids = []
    for _ in file_chunks:
        cid = meta['next_id']
        meta['next_id'] += 1
        ids.append(cid)

    vecs = normalize(embed_texts(file_chunks))
    index.add_with_ids(vecs, np.array(ids, dtype='int64'))
    meta['files'][path_str] = ids
    for cid, chunk in zip(ids, file_chunks):
        chunks.append(asdict(ChunkRecord(cid, path_str, chunk)))
    return index, meta, chunks


class KBHandler(FileSystemEventHandler):
    def __init__(self, state):
        self.state = state

    def on_created(self, event):
        if not event.is_directory:
            self.process(Path(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self.process(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self.process(Path(event.dest_path))
            self.process(Path(event.src_path))

    def on_deleted(self, event):
        if not event.is_directory:
            with lock:
                index, meta, chunks = self.state['index'], self.state['meta'], self.state['chunks']
                index, meta, chunks = remove_file(index, meta, chunks, str(Path(event.src_path)))
                self.state.update(index=index, meta=meta, chunks=chunks)
                save_state(index, meta, chunks)
                print(f'deleted: {event.src_path}')

    def process(self, path: Path):
        if path.suffix.lower() != '.md':
            return
        time.sleep(0.2)
        with lock:
            index, meta, chunks = self.state['index'], self.state['meta'], self.state['chunks']
            index, meta, chunks = add_or_update_file(index, meta, chunks, path)
            self.state.update(index=index, meta=meta, chunks=chunks)
            save_state(index, meta, chunks)
            print(f'updated: {path}')


def main():
    index, meta, chunks = load_state()
    if index is None:
        index, meta, chunks = rebuild_all()
    state = {'index': index, 'meta': meta, 'chunks': chunks}

    observer = Observer()
    handler = KBHandler(state)
    observer.schedule(handler, str(KB_DIR), recursive=True)
    observer.start()
    print(f'Watching {KB_DIR.resolve()}')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    save_state(state['index'], state['meta'], state['chunks'])


if __name__ == '__main__':
    main()
