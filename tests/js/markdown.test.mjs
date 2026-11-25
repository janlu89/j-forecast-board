// SPDX-License-Identifier: Apache-2.0
// The chat's tiny Markdown renderer (md in src/j_forecast_board/static/app.js). Run: node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const APP = new URL("../../src/j_forecast_board/static/app.js", import.meta.url);

/** Load `esc` and `md` from the legacy script, which is not a module yet. */
function loadRenderer() {
  const source = readFileSync(APP, "utf8");
  const esc = source.match(/^const esc = .*$/m)[0].replace(/^const /, "var ");
  const start = source.indexOf("function md(src) {");
  assert.ok(start >= 0, "md() not found in app.js");
  let depth = 0;
  let end = start;
  for (; end < source.length; end++) {
    if (source[end] === "{") depth++;
    if (source[end] === "}" && --depth === 0) break;
  }
  const context = vm.createContext({});
  vm.runInContext(`${esc}\n${source.slice(start, end + 1)}`, context);
  return context.md;
}

const md = loadRenderer();

test("paragraph lines are joined with line breaks", () => {
  assert.equal(md("one\ntwo\n\nthree"), "<p>one<br>two</p><p>three</p>");
});

test("inline code, bold and italic", () => {
  assert.equal(md("use `x` **now** or *later*"), "<p>use <code>x</code> <b>now</b> or <i>later</i></p>");
});

test("HTML in the answer is escaped", () => {
  assert.equal(md('<script>alert("x")</script>'), "<p>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;</p>");
});

test("only http and https links become anchors", () => {
  assert.equal(
    md("[site](https://example.org) [bad](javascript:alert(1))"),
    '<p><a href="https://example.org" target="_blank" rel="noopener">site</a> [bad](javascript:alert(1))</p>',
  );
});

test("bulleted and numbered lists", () => {
  assert.equal(md("- a\n- b"), "<ul><li>a</li><li>b</li></ul>");
  assert.equal(md("1. a\n2. b"), "<ol><li>a</li><li>b</li></ol>");
});

test("headings render as h4", () => {
  assert.equal(md("## Title"), "<h4>Title</h4>");
});

test("tables skip the separator row", () => {
  assert.equal(
    md("| a | b |\n|---|:-:|\n| 1 | 2 |"),
    "<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
  );
});

test("code blocks are escaped and kept verbatim", () => {
  assert.equal(md("```\n<b>x</b>\n  y\n```"), "<pre><code>&lt;b&gt;x&lt;/b&gt;\n  y</code></pre>");
});

test("every prefix of a streamed answer renders quickly", () => {
  // A half-received table row once made the renderer loop forever.
  const answer = [
    "## Accuracy",
    "The model is **better** than the baseline on `MAPE`.",
    "| Model | MAPE | WAPE |",
    "|---|---:|---:|",
    "| Timestral-28M | 4.1% | 3.9% |",
    "| Naive weekly | 7.5% | 7.0% |",
    "",
    "- first point with *emphasis*",
    "- second point, see [docs](https://example.org)",
    "1. step one",
    "2. step two",
    "```",
    "code <here>",
    "```",
    "Done.",
  ].join("\n");
  for (let i = 0; i <= answer.length; i++) {
    const started = performance.now();
    md(answer.slice(0, i));
    const elapsed = performance.now() - started;
    assert.ok(elapsed < 50, `prefix of ${i} characters took ${elapsed.toFixed(1)} ms`);
  }
});
