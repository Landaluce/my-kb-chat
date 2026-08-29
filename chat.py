from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession

import kb_search

console = Console()


def run_cli():
    kb_search.load_state()
    console.print(Panel.fit("       KB Chatbot         ", subtitle="type /help for commands"))
    session = PromptSession()
    while True:
        q = session.prompt("Ask> ").strip()
        if q in {"exit", "quit", "q", "bye ", "ex"}:
            break
        if q in {"/help", "/?", "/h"}:
            console.print("Commands: /help, /sources, /reindex, exit")
            continue
        if q in {"/sources", "/s"}:
            files = kb_search.file_summaries()
            console.print(f"Files indexed: {len(files)}")
            for f in files:
                console.print(f"  {f['path']} ({f['chunks']} chunks)")
            continue
        if q in {"/reindex", "/r"}:
            console.print("Reindex by rerunning kb_watch_incremental.py or your indexer.")
            continue

        with console.status("Thinking..."):
            text, results = kb_search.answer(q)
        console.print(Panel(Text(text), title="Answer", expand=False))


if __name__ == "__main__":
    run_cli()
