/**
 * Markdown rendering (escape-first, XSS-safe).
 * Works in the browser (attaches global functions) and in Node for unit tests.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = factory();
    } else {
        const api = factory();
        root.escapeHtml = api.escapeHtml;
        root.renderInline = api.renderInline;
        root.renderMarkdown = api.renderMarkdown;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    function escapeHtml(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function renderInline(s) {
        return s
            .replace(/`([^`]+)`/g, (m, c) => `<code>${c}</code>`)
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/\*([^*]+)\*/g, "<em>$1</em>")
            .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    }

    function renderMarkdown(text) {
        const lines = text.replace(/\r\n/g, "\n").split("\n");
        let html = "";
        let i = 0;
        let inCode = false;
        let codeBuf = [];
        let listType = null;
        let listItems = [];
        const closeList = () => {
            if (listType) {
                html += `<${listType}>` + listItems.join("") + `</${listType}>`;
                listType = null;
                listItems = [];
            }
        };
        while (i < lines.length) {
            const line = lines[i];
            if (line.trim().startsWith("```")) {
                closeList();
                if (inCode) {
                    html += `<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`;
                    codeBuf = [];
                    inCode = false;
                } else {
                    inCode = true;
                }
                i++;
                continue;
            }
            if (inCode) {
                codeBuf.push(line);
                i++;
                continue;
            }
            const t = line.trim();
            if (!t) {
                closeList();
                i++;
                continue;
            }
            const heading = t.match(/^(#{1,4})\s+(.*)/);
            if (heading) {
                closeList();
                const lvl = heading[1].length;
                html += `<h${lvl}>${renderInline(escapeHtml(heading[2]))}</h${lvl}>`;
                i++;
                continue;
            }
            if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
                closeList();
                html += "<hr>";
                i++;
                continue;
            }
            const ul = t.match(/^[-*+]\s+(.*)/);
            if (ul) {
                if (listType !== "ul") {
                    closeList();
                    listType = "ul";
                }
                listItems.push(`<li>${renderInline(escapeHtml(ul[1]))}</li>`);
                i++;
                continue;
            }
            const ol = t.match(/^\d+\.\s+(.*)/);
            if (ol) {
                if (listType !== "ol") {
                    closeList();
                    listType = "ol";
                }
                listItems.push(`<li>${renderInline(escapeHtml(ol[1]))}</li>`);
                i++;
                continue;
            }
            if (t.startsWith(">")) {
                closeList();
                html += `<blockquote>${renderInline(escapeHtml(t.slice(1).trim()))}</blockquote>`;
                i++;
                continue;
            }
            closeList();
            html += `<p>${renderInline(escapeHtml(t))}</p>`;
            i++;
        }
        if (inCode) html += `<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`;
        closeList();
        return html;
    }

    return { escapeHtml, renderInline, renderMarkdown };
});