const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendBtn = document.getElementById("send-btn");
const fileCountEl = document.getElementById("file-count");
const statusEl = document.getElementById("status");
const emptyState = document.getElementById("empty-state");
const filesSearch = document.getElementById("files-search");
const filesList = document.getElementById("files-list");
const filesRefresh = document.getElementById("files-refresh");
const reindexBtn = document.getElementById("reindex-btn");
const uploadFileInput = document.getElementById("upload-file");
const uploadBtn = document.getElementById("upload-btn");
const uploadResult = document.getElementById("upload-result");
const uploadPreview = document.getElementById("upload-preview");
const uploadPreviewTitle = document.getElementById("upload-preview-title");
const uploadPreviewContent = document.getElementById("upload-preview-content");
const uploadSaveBtn = document.getElementById("upload-save-btn");
const uploadPane = document.getElementById("pane-upload");
const uploadForm = document.getElementById("upload-form");

const state = {
    history: [], // last few chat turns, sent with each request
    pendingUpload: null, // { file, markdown }
    files: [],
    thread: [], // { type: "user"|"bot", text } for the visible conversation
};

// History of questions so the user can recall them with the up/down arrow keys.
// Persisted to localStorage so it survives a page reload.
const questionHistoryKey = "kb-question-history";
const questionHistory = (() => {
    try {
        const raw = JSON.parse(localStorage.getItem(questionHistoryKey) || "[]");
        return Array.isArray(raw) ? raw.filter((x) => typeof x === "string") : [];
    } catch {
        return [];
    }
})();
function saveQuestionHistory() {
    try {
        localStorage.setItem(questionHistoryKey, JSON.stringify(questionHistory.slice(-100)));
    } catch {
        // storage unavailable; history just stays in memory
    }
}
let historyIndex = -1; // -1 = not navigating (showing the fresh/draft value)
let questionDraft = ""; // the value being edited before arrow-up navigation started

// Chat thread persistence across reloads.
const threadKey = "kb-thread";
function persistThread() {
    try {
        localStorage.setItem(threadKey, JSON.stringify(state.thread.slice(-200)));
    } catch {
        // storage unavailable; the conversation just stays in memory
    }
}
function updateBotThread(text) {
    if (state.thread.length && state.thread[state.thread.length - 1].type === "bot") {
        state.thread[state.thread.length - 1].text = text;
        persistThread();
    }
}
function restoreThread() {
    let raw;
    try {
        raw = JSON.parse(localStorage.getItem(threadKey) || "[]");
    } catch {
        raw = [];
    }
    if (!Array.isArray(raw)) return;
    for (const m of raw) {
        if (m && (m.type === "user" || m.type === "bot")) {
            addMessage(m.text || "", m.type);
        }
    }
}
function clearThread() {
    state.thread = [];
    state.history = [];
    persistThread();
    messagesEl.innerHTML = "";
    messagesEl.appendChild(emptyState);
    setStatus("");
    input.focus();
}

// Streaming / cancel state.
let streaming = false;
let currentController = null;

const tabs = {
    chat: document.getElementById("tab-chat"),
    files: document.getElementById("tab-files"),
    note: document.getElementById("tab-note"),
    upload: document.getElementById("tab-upload"),
};
const panes = {
    chat: document.getElementById("pane-chat"),
    files: document.getElementById("pane-files"),
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
    else if (name === "files") loadFiles();
}

// Markdown rendering (escapeHtml/renderInline/renderMarkdown) is provided by /static/render.js.

/* ---------- Messages ---------- */
function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addTime(el) {
    const t = document.createElement("span");
    t.className = "msg-time";
    t.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    el.appendChild(t);
}

function setBotText(el, text) {
    el._text = text || "";
    el.innerHTML = renderMarkdown(el._text);
}

function addMessage(text, type) {
    if (emptyState) emptyState.remove();
    const el = document.createElement("div");
    el.className = "message " + (type || "user");
    if (type === "bot") {
        setBotText(el, text || "");
    } else {
        el.textContent = text;
    }
    addTime(el);
    messagesEl.appendChild(el);
    scrollToBottom();
    if (type === "user" || type === "bot") {
        state.thread.push({ type, text: text || "" });
        persistThread();
    }
    return el;
}

function addMeta(el, sources, latency) {
    if (!sources || sources.length === 0) return;
    const meta = document.createElement("div");
    meta.className = "meta";

    const row = document.createElement("div");
    row.className = "meta-row";
    const count = document.createElement("span");
    count.textContent = `Sources (${sources.length}) · ${latency} ms`;
    row.appendChild(count);
    row.appendChild(makeCopyBtn(el));
    meta.appendChild(row);

    // Group the per-chunk sources by file.
    const groups = new Map();
    for (const s of sources) {
        if (!groups.has(s.path)) groups.set(s.path, []);
        groups.get(s.path).push(s);
    }
    for (const [path, list] of groups) {
        const best = list.reduce((a, b) => (b.score > a.score ? b : a));
        const btn = document.createElement("button");
        btn.className = "source-link";
        btn.type = "button";
        btn.title = "Read / edit " + path;
        const chunksLabel = list.length > 1 ? ` · ${list.length} chunks` : "";
        btn.textContent = `• ${path} (score ${best.score.toFixed(3)})${chunksLabel}`;
        btn.addEventListener("click", () => openFile(best.rel_path || best.path, best.preview));
        meta.appendChild(btn);
    }
    el.appendChild(meta);
}

function makeCopyBtn(el) {
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.type = "button";
    btn.textContent = "Copy";
    btn.addEventListener("click", async () => {
        const text = el._text || el.innerText;
        try {
            await navigator.clipboard.writeText(text);
            btn.textContent = "Copied!";
        } catch {
            // Clipboard API unavailable (non-secure context); fall back.
            const ta = document.createElement("textarea");
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            const ok = document.execCommand("copy");
            ta.remove();
            btn.textContent = ok ? "Copied!" : "Copy failed";
        }
        setTimeout(() => (btn.textContent = "Copy"), 1500);
    });
    return btn;
}

/* ---------- Chat ---------- */
function updateSendBtn() {
    sendBtn.textContent = streaming ? "Stop" : "Send";
}

async function ask(question) {
    const controller = new AbortController();
    currentController = controller;
    streaming = true;
    updateSendBtn();
    addMessage(question, "user");
    input.value = "";
    const thinking = addMessage("Thinking…", "thinking");
    const botEl = document.createElement("div");
    botEl.className = "message bot";
    let started = false;
    let text = "";
    try {
        const res = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, history: state.history }),
            signal: controller.signal,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            thinking.remove();
            addMessage(err.detail || "Something went wrong.", "error");
            return;
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let idx;
            while ((idx = buffer.indexOf("\n\n")) !== -1) {
                const raw = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                for (const line of raw.split("\n")) {
                    if (!line.startsWith("data: ")) continue;
                    let payload;
                    try {
                        payload = JSON.parse(line.slice(6));
                    } catch {
                        continue;
                    }
                    if (payload.type === "token") {
                        if (!started) {
                            thinking.remove();
                            messagesEl.appendChild(botEl);
                            addTime(botEl);
                            started = true;
                            state.thread.push({ type: "bot", text: "" });
                        }
                        text += payload.text;
                        setBotText(botEl, text);
                        updateBotThread(text);
                        scrollToBottom();
                    } else if (payload.type === "reset") {
                        text = "";
                        setBotText(botEl, "");
                        updateBotThread("");
                    } else if (payload.type === "done") {
                        if (!started) {
                            thinking.remove();
                            messagesEl.appendChild(botEl);
                            addTime(botEl);
                            started = true;
                            state.thread.push({ type: "bot", text: "" });
                        }
                        if (!text) setBotText(botEl, "(no answer)");
                        updateBotThread(text || "(no answer)");
                        addMeta(botEl, payload.sources, payload.latency_ms);
                        scrollToBottom();
                    } else if (payload.type === "error") {
                        thinking.remove();
                        if (started && state.thread.length && state.thread[state.thread.length - 1].type === "bot") {
                            state.thread.pop();
                            persistThread();
                        }
                        if (started) botEl.remove();
                        addMessage(payload.detail || "Something went wrong.", "error");
                        return;
                    }
                }
            }
        }
        state.history.push({ role: "user", content: question });
        if (text) state.history.push({ role: "assistant", content: text });
        if (state.history.length > 12) state.history = state.history.slice(-12);
    } catch (e) {
        thinking.remove();
        if (started && state.thread.length && state.thread[state.thread.length - 1].type === "bot") {
            state.thread.pop();
            persistThread();
        }
        if (started) botEl.remove();
        if (!(e && e.name === "AbortError")) {
            addMessage("Network error: " + e.message, "error");
        }
    } finally {
        streaming = false;
        currentController = null;
        updateSendBtn();
        input.focus();
    }
}

/* ---------- File modal ---------- */
function openModal() {
    document.getElementById("file-modal").classList.add("open");
}

function closeModal() {
    document.getElementById("file-modal").classList.remove("open");
}

async function openFile(relPath, preview) {
    const pathEl = document.getElementById("file-path");
    const previewEl = document.getElementById("file-preview");
    const textEl = document.getElementById("file-content");
    const saveBtn = document.getElementById("file-save-btn");
    const deleteBtn = document.getElementById("file-delete-btn");
    const msgEl = document.getElementById("file-msg");
    pathEl.textContent = relPath;
    previewEl.hidden = !preview;
    previewEl.textContent = preview || "";
    textEl.value = "Loading…";
    msgEl.textContent = "";
    deleteBtn.disabled = false;
    saveBtn.disabled = true;
    openModal();
    try {
        const res = await fetch("/api/file?path=" + encodeURIComponent(relPath));
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load file");
        textEl.value = data.content;
        if (preview) {
            previewEl.textContent = `chunk: ${preview}`;
            // Highlight the matched chunk in the file.
            const start = textEl.value.indexOf(preview);
            if (start !== -1) {
                textEl.focus();
                textEl.setSelectionRange(start, start + preview.length);
            }
        }
        saveBtn.disabled = false;
    } catch (err) {
        previewEl.hidden = false;
        previewEl.textContent =
            "Couldn't load this file: " + err.message + " If it was moved or renamed, run Reindex, then retry.";
        textEl.value = "";
        msgEl.textContent = "";
        msgEl.className = "file-msg";
        saveBtn.disabled = true;
        deleteBtn.disabled = true;
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

async function deleteFile() {
    const relPath = document.getElementById("file-path").textContent.trim();
    if (!relPath) return;
    if (!confirm(`Delete ${relPath}? This cannot be undone.`)) return;
    const deleteBtn = document.getElementById("file-delete-btn");
    const msgEl = document.getElementById("file-msg");
    deleteBtn.disabled = true;
    msgEl.textContent = "Deleting…";
    msgEl.className = "file-msg";
    try {
        const res = await fetch("/api/file?path=" + encodeURIComponent(relPath), { method: "DELETE" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to delete");
        closeModal();
        const err = await waitForReindex();
        loadFiles();
        setStatus(err ? `Deleted (reindex error: ${err})` : "Deleted & reindexed.");
        setTimeout(() => setStatus(""), 4000);
    } catch (err) {
        msgEl.textContent = err.message;
        msgEl.className = "file-msg err";
    } finally {
        deleteBtn.disabled = false;
    }
}

/* ---------- Files tab ---------- */
async function loadFiles() {
    try {
        const res = await fetch("/api/sources");
        const data = await res.json();
        state.files = data.files || [];
        renderFiles();
    } catch {
        // ignore transient errors
    }
}

function renderFiles() {
    const q = filesSearch.value.trim().toLowerCase();
    const list = state.files
        .filter((f) => f.path.toLowerCase().includes(q))
        .sort((a, b) => a.path.localeCompare(b.path));
    filesList.innerHTML = "";
    if (list.length === 0) {
        const li = document.createElement("li");
        li.className = "files-empty";
        li.textContent = q ? "No matching files." : "No files indexed yet.";
        filesList.appendChild(li);
        return;
    }
    for (const f of list) {
        const li = document.createElement("li");
        li.className = "file-row";
        const nameBtn = document.createElement("button");
        nameBtn.className = "file-name";
        nameBtn.type = "button";
        nameBtn.textContent = f.path;
        nameBtn.addEventListener("click", () => openFile(f.path, null));
        const count = document.createElement("span");
        count.className = "file-chunks";
        count.textContent = f.chunks === 1 ? "1 chunk" : `${f.chunks} chunks`;
        li.appendChild(nameBtn);
        li.appendChild(count);
        filesList.appendChild(li);
    }
}

/* ---------- Upload (preview + drag & drop) ---------- */
function setResult(el, text, ok) {
    el.textContent = text;
    el.className = "result " + (ok ? "ok" : "err");
}

async function previewUpload(file) {
    if (!file) return;
    uploadBtn.disabled = true;
    setResult(uploadResult, "Converting…", true);
    try {
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch("/api/ingest/preview", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Conversion failed");
        state.pendingUpload = { file, markdown: data.markdown };
        uploadPreviewTitle.textContent = file.name;
        uploadPreviewContent.textContent = data.markdown;
        uploadPreview.hidden = false;
        uploadSaveBtn.disabled = false;
        setResult(uploadResult, "Preview ready — review it, then save.", true);
    } catch (err) {
        setResult(uploadResult, err.message, false);
    } finally {
        uploadBtn.disabled = false;
    }
}

async function saveUpload() {
    if (!state.pendingUpload) return;
    uploadSaveBtn.disabled = true;
    setResult(uploadResult, "Saving & indexing…", true);
    try {
        const formData = new FormData();
        formData.append("file", state.pendingUpload.file);
        const res = await fetch("/api/ingest/upload", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to save");
        const err = await waitForReindex();
        setResult(
            uploadResult,
            err ? `Saved → ${data.path} (reindex error: ${err})` : `Saved & indexed → ${data.path}`,
            !err,
        );
        state.pendingUpload = null;
        uploadPreview.hidden = true;
        uploadFileInput.value = "";
        loadFiles();
    } catch (err) {
        setResult(uploadResult, err.message, false);
    } finally {
        uploadSaveBtn.disabled = false;
    }
}

function initDragDrop() {
    ["dragover", "dragenter"].forEach((ev) =>
        uploadPane.addEventListener(ev, (e) => {
            e.preventDefault();
            uploadPane.classList.add("dragover");
        }),
    );
    ["dragleave", "drop"].forEach((ev) =>
        uploadPane.addEventListener(ev, (e) => {
            e.preventDefault();
            uploadPane.classList.remove("dragover");
        }),
    );
    uploadPane.addEventListener("drop", (e) => {
        const files = e.dataTransfer && e.dataTransfer.files;
        if (files && files.length) previewUpload(files[0]);
    });
}

/* ---------- Notes ---------- */
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
        err ? `Saved → ${savedPath} (reindex error: ${err})` : `Saved & indexed → ${savedPath}`,
        !err,
    );
    document.getElementById("note-content").value = "";
    document.getElementById("note-title").value = "";
    btn.disabled = false;
    loadFiles();
}

/* ---------- Reindex ---------- */
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

async function triggerReindex() {
    reindexBtn.disabled = true;
    setStatus("Reindexing…");
    try {
        const res = await fetch("/api/reindex", { method: "POST" });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            setStatus(err.detail || "Failed to start reindex.");
            return;
        }
        const err = await waitForReindex();
        setStatus(err ? `Reindex error: ${err}` : "Reindex complete.");
    } catch (e) {
        setStatus("Network error: " + e.message);
    } finally {
        reindexBtn.disabled = false;
        setTimeout(() => setStatus(""), 4000);
    }
}

/* ---------- Misc ---------- */
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

/* ---------- Wiring ---------- */
form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (streaming) {
        // The button reads "Stop" while an answer is streaming.
        if (currentController) currentController.abort();
        return;
    }
    const question = input.value.trim();
    if (!question || sendBtn.disabled) return;
    if (questionHistory[questionHistory.length - 1] !== question) questionHistory.push(question);
    saveQuestionHistory();
    historyIndex = -1;
    questionDraft = "";
    ask(question);
});

// Up/Down arrows recall previous questions (like a shell history).
input.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    if (questionHistory.length === 0) return;
    if (e.key === "ArrowUp") {
        if (historyIndex === -1) {
            questionDraft = input.value; // save what the user is currently typing
            historyIndex = questionHistory.length - 1;
        } else if (historyIndex > 0) {
            historyIndex--;
        }
        input.value = questionHistory[historyIndex];
    } else {
        // ArrowDown
        if (historyIndex === -1) return; // already at the fresh line
        if (historyIndex < questionHistory.length - 1) {
            historyIndex++;
            input.value = questionHistory[historyIndex];
        } else {
            historyIndex = -1; // back to where we started
            input.value = questionDraft || "";
        }
    }
    // Put the caret at the end.
    const len = input.value.length;
    input.setSelectionRange(len, len);
});

tabs.chat.addEventListener("click", () => switchTab("chat"));
tabs.files.addEventListener("click", () => switchTab("files"));
tabs.note.addEventListener("click", () => switchTab("note"));
tabs.upload.addEventListener("click", () => switchTab("upload"));

document.querySelectorAll(".hint-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
        input.value = btn.textContent.trim();
        form.requestSubmit();
    }),
);

document.getElementById("note-form").addEventListener("submit", submitNote);
uploadForm.addEventListener("submit", (e) => {
    e.preventDefault();
    previewUpload(uploadFileInput.files && uploadFileInput.files[0]);
});
uploadSaveBtn.addEventListener("click", saveUpload);

document.getElementById("file-close-btn").addEventListener("click", closeModal);
document.getElementById("file-save-btn").addEventListener("click", saveFile);
document.getElementById("file-delete-btn").addEventListener("click", deleteFile);
document.getElementById("file-modal").addEventListener("click", (e) => {
    if (e.target.id === "file-modal") closeModal();
});

// Escape closes the file modal.
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.getElementById("file-modal").classList.contains("open")) {
        closeModal();
    }
});

filesSearch.addEventListener("input", renderFiles);
filesRefresh.addEventListener("click", loadFiles);
reindexBtn.addEventListener("click", triggerReindex);
document.getElementById("clear-btn").addEventListener("click", clearThread);

updateSendBtn();
initDragDrop();
restoreThread();
loadSourceCount();
input.focus();
