const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendBtn = document.getElementById("send-btn");
const fileCountEl = document.getElementById("file-count");

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
        const span = document.createElement("span");
        span.textContent = `• ${s.path} (score ${s.score.toFixed(3)})`;
        meta.appendChild(span);
    }
    el.appendChild(meta);
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

form.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (!question || sendBtn.disabled) return;
    ask(question);
});

loadSourceCount();
input.focus();
