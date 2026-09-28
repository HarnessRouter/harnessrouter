const { test } = require("@jest/globals");
const assert = require("node:assert/strict");
const { csvToTable } = require("./csvToTable");

test("CSV preserves quoted delimiters, escaped quotes, and multiline fields", () => {
  const html = csvToTable('name,note\r\nAlice,"hello, ""world""\r\nagain"\r\n');
  assert.equal(
    html,
    '<table><tr><th>name</th><th>note</th></tr><tr><td>Alice</td><td>hello, "world"\r\nagain</td></tr></table>',
  );
});

test("TSV uses tabs as separators and keeps commas inside a cell", () => {
  const html = csvToTable("name\tnote\nAlice\thello, world", "\t");
  assert.equal(
    html,
    "<table><tr><th>name</th><th>note</th></tr><tr><td>Alice</td><td>hello, world</td></tr></table>",
  );
});

test("HTML metacharacters in values are escaped", () => {
  const html = csvToTable('name,note\nAlice,"<script>&"');
  assert.equal(
    html,
    "<table><tr><th>name</th><th>note</th></tr><tr><td>Alice</td><td>&lt;script&gt;&amp;</td></tr></table>",
  );
});

test("UTF-8 BOM is not included in the first header", () => {
  const html = csvToTable("\uFEFFname,note\nAlice,ok");
  assert.equal(
    html,
    "<table><tr><th>name</th><th>note</th></tr><tr><td>Alice</td><td>ok</td></tr></table>",
  );
});

test("preview remains capped at 1000 logical rows", () => {
  const input = [
    "h",
    ...Array.from({ length: 1002 }, (_, i) => String(i)),
  ].join("\n");
  assert.equal((csvToTable(input).match(/<tr>/g) || []).length, 1000);
});
