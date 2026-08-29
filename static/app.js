const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendBtn = document.getElementById("send-btn");
const fileCountEl = document.getElementById("file-count");
const statusEl = document.getElementById("status");

const tabs = {
    chat: document.getElementById("tab-chat"),
    note: document.getElementById("tab-note"),
    upload: document.getElementById("tab-upload"),
};
const panes = {
    chat: document.getElementById("pane-chat"),
    note: document.getElementById("pane-note"),
    upload: document.getElementById("pane-upload"),
};

function switchTab(name) {
    Object.keys(tabs).forEach((k) => {
        tabs[k].classList.toggle("active", k === name);
        panes[k].classList.toggle("hidden", k !== name);
    });
    if (name === "chat") input.focus();
    else if (name === "note") document.getElementById("note-title").focus();
}

function addMessage(text, type) {
    const el = document.createElement("div");
    el.className = "message " + (type || "user");
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
}

function addMeta(el, sources, latency) {
    if (!sources || sources.length === 0) return;
    const meta = document.createElement("div");
    meta.className = "meta";
    const count = document.createElement("span");
    count.textContent = `Sources (${sources.length}) · ${latency} ms`;
    meta.appendChild(count);
    for (const s of sources) {
        const btn = document.createElement("button");
        btn.className = "source-link";
        btn.type = "button";
        btn.title = "Read / edit " + s.path;
        btn.textContent = `• ${s.path} (score ${s.score.toFixed(3)})`;
        btn.addEventListener("click", () => openFile(s.rel_path || s.path, s.preview));
        meta.appendChild(btn);
    }
    el.appendChild(meta);
}

async function openFile(relPath, preview) {
    const pathEl = document.getElementById("file-path");
    const previewEl = document.getElementById("file-preview");
    const textEl = document.getElementById("file-content");
    const saveBtn = document.getElementById("file-save-btn");
    const msgEl = document.getElementById("file-msg");
    pathEl.textContent = relPath;
    previewEl.hidden = false;
    previewEl.textContent = preview || "";
    textEl.value = "Loading…";
    msgEl.textContent = "";
    openModal();
    try {
        const res = await fetch("/api/file?path=" + encodeURIComponent(relPath));
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load file");
        textEl.value = data.content;
        if (preview) {
            previewEl.textContent = `chunk: ${preview}`;
        }
        saveBtn.disabled = false;
    } catch (err) {
        previewEl.hidden = true;
        textEl.value = "";
        msgEl.textContent = err.message;
        msgEl.className = "file-msg err";
        saveBtn.disabled = true;
    }
}

async function saveFile() {
    const relPath = document.getElementById("file-path").textContent.trim();
    const text = document.getElementById("file-content").value;
    const saveBtn = document.getElementById("file-save-btn");
    const msgEl = document.getElementById("file-msg");
    if (!relPath || !text) return;
    saveBtn.disabled = true;
    msgEl.textContent = "Saving…";
    msgEl.className = "file-msg";
    try {
        const res = await fetch("/api/file?path=" + encodeURIComponent(relPath), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: text }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save");
        msgEl.textContent = "Saved. Reindexing…";
        msgEl.className = "file-msg ok";
        const err = await waitForReindex();
        msgEl.textContent = err ? `Saved (reindex error: ${err})` : "Saved & indexed.";
        msgEl.className = "file-msg " + (err ? "err" : "ok");
    } catch (err) {
        msgEl.textContent = err.message;
        msgEl.className = "file-msg err";
    } finally {
        saveBtn.disabled = false;
    }
}

function openModal() {
    document.getElementById("file-modal").classList.add("open");
}

function closeModal() {
    document.getElementById("file-modal").classList.remove("open");
}

async function ask(question) {
    addMessage(question, "user");
    input.value = "";
    sendBtn.disabled = true;
    const thinking = addMessage("Thinking…", "thinking");
    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
        });
        thinking.remove();
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            addMessage(err.detail || "Something went wrong.", "error");
            return;
        }
        const data = await res.json();
        const botEl = addMessage(data.answer, "bot");
        addMeta(botEl, data.sources, data.latency_ms);
    } catch (e) {
        thinking.remove();
        addMessage("Network error: " + e.message, "error");
    } finally {
        sendBtn.disabled = false;
        input.focus();
    }
}

async function loadSourceCount() {
    try {
        const res = await fetch("/api/sources");
        const data = await res.json();
        fileCountEl.textContent = data.files.length
            ? `Indexed files: ${data.files.length}`
            : "";
    } catch {
        fileCountEl.textContent = "";
    }
}

function setStatus(text) {
    statusEl.textContent = text || "";
}

function setResult(el, text, ok) {
    el.textContent = text;
    el.className = "result " + (ok ? "ok" : "err");
}

async function waitForReindex() {
    setStatus("Reindexing…");
    let done = false;
    let lastError = null;
    while (!done) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
            const res = await fetch("/api/reindex/status");
            const data = await res.json();
            if (!data.running) {
                done = true;
                lastError = data.error || null;
            }
        } catch {
            // transient poll failure; keep waiting
        }
    }
    setStatus("");
    loadSourceCount();
    return lastError;
}

async function submitNote(e) {
    e.preventDefault();
    const title = document.getElementById("note-title").value.trim();
    const content = document.getElementById("note-content").value;
    const btn = document.getElementById("note-btn");
    const result = document.getElementById("note-result");
    if (!content.trim()) {
        setResult(result, "Note is empty.", false);
        return;
    }
    btn.disabled = true;
    setResult(result, "Saving…", true);
    let savedPath;
    try {
        const res = await fetch("/api/ingest/note", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, content }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save note");
        savedPath = data.path;
    } catch (err) {
        setResult(result, err.message, false);
        btn.disabled = false;
        setStatus("");
        return;
    }
    const err = await waitForReindex();
    setResult(
        result,
        err
            ? `Saved → ${savedPath} (reindex error: ${err})`
            : `Saved & indexed → ${savedPath}`,
        !err,
    );
    document.getElementById("note-content").value = "";
    document.getElementById("note-title").value = "";
    btn.disabled = false;
}

async function submitUpload(e) {
    e.preventDefault();
    const fileInput = document.getElementById("upload-file");
    const file = fileInput.files && fileInput.files[0];
    const btn = document.getElementById("upload-btn");
    const result = document.getElementById("upload-result");
    if (!file) {
        setResult(result, "Choose a file first.", false);
        return;
    }
    btn.disabled = true;
    setResult(result, "Converting & saving…", true);
    let savedPath;
    try {
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch("/api/ingest/upload", {
            method: "POST",
            body: formData,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to upload");
        savedPath = data.path;
    } catch (err) {
        setResult(result, err.message, false);
        btn.disabled = false;
        setStatus("");
        return;
    }
    const err = await waitForReindex();
    setResult(
        result,
        err
            ? `Saved → ${savedPath} (reindex error: ${err})`
            : `Converted, saved & indexed → ${savedPath}`,
        !err,
    );
    fileInput.value = "";
    btn.disabled = false;
}

form.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (!question || sendBtn.disabled) return;
    ask(question);
});

tabs.chat.addEventListener("click", () => switchTab("chat"));
tabs.note.addEventListener("click", () => switchTab("note"));
tabs.upload.addEventListener("click", () => switchTab("upload"));

document.getElementById("note-form").addEventListener("submit", submitNote);
document.getElementById("upload-form").addEventListener("submit", submitUpload);

document.getElementById("file-close-btn").addEventListener("click", closeModal);
document.getElementById("file-save-btn").addEventListener("click", saveFile);
document.getElementById("file-modal").addEventListener("click", (e) => {
    if (e.target.id === "file-modal") closeModal();
});

loadSourceCount();
input.focus();
