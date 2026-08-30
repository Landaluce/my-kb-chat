const { test } = require("node:test");
const assert = require("node:assert/strict");

const { escapeHtml, renderInline, renderMarkdown } = require("./static/render.js");

test("escapeHtml escapes & < >", () => {
    assert.equal(escapeHtml("a<b & c>d"), "a&lt;b &amp; c&gt;d");
});

test("renderMarkdown renders headings", () => {
    assert.ok(renderMarkdown("# Title").includes("<h1>Title</h1>"));
    assert.ok(renderMarkdown("## Sub").includes("<h2>Sub</h2>"));
});

test("renderMarkdown renders paragraphs", () => {
    assert.equal(renderMarkdown("hello world"), "<p>hello world</p>");
});

test("renderMarkdown renders inline emphasis safely", () => {
    const html = renderMarkdown("**bold** and *italic*");
    assert.ok(html.includes("<strong>bold</strong>"));
    assert.ok(html.includes("<em>italic</em>"));
});

test("renderMarkdown renders inline code", () => {
    const html = renderMarkdown("run `pip install` now");
    assert.ok(html.includes("<code>pip install</code>"));
});

test("renderMarkdown renders fenced code blocks", () => {
    const html = renderMarkdown("```js\nconst x = 1;\n```");
    assert.ok(html.includes("<pre><code>"));
    assert.ok(html.includes("const x = 1;"));
});

test("renderMarkdown renders unordered and ordered lists", () => {
    const html = renderMarkdown("- a\n- b");
    assert.ok(html.includes("<ul><li>a</li><li>b</li></ul>"));
    const ol = renderMarkdown("1. first\n2. second");
    assert.ok(ol.includes("<ol><li>first</li><li>second</li></ol>"));
});

test("renderMarkdown renders blockquote", () => {
    assert.ok(renderMarkdown("> quoted").includes("<blockquote>quoted</blockquote>"));
});

test("renderMarkdown renders links with target", () => {
    const html = renderMarkdown("[docs](https://example.com)");
    assert.ok(html.includes('<a href="https://example.com" target="_blank" rel="noopener">docs</a>'));
});

test("renderMarkdown escapes HTML to avoid XSS", () => {
    const html = renderMarkdown("<script>alert(1)</script>");
    assert.ok(!html.includes("<script>"));
    assert.ok(html.includes("&lt;script&gt;"));
});

test("renderMarkdown does not inject JS in code fences", () => {
    const html = renderMarkdown("```html\n<img onerror=alert(1)>\n```");
    assert.ok(html.includes("&lt;img"));
    assert.ok(!html.includes("<img"));
});

test("renderMarkdown handles CRLF line endings", () => {
    const html = renderMarkdown("# Hi\r\n\r\nbody");
    assert.ok(html.includes("<h1>Hi</h1>"));
    assert.ok(html.includes("<p>body</p>"));
});