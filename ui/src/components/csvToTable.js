/**
 * Render delimited text as a small HTML table without changing cell values.
 * The delimiter is explicit so commas in TSV cells are never treated as separators.
 * @param {string} text
 * @param {string} delimiter
 * @returns {string}
 */
function csvToTable(text, delimiter = ",") {
  // Spreadsheet exports often include a UTF-8 BOM; it is metadata, not part of the first cell.
  text = text.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let i = 0; i < text.length && rows.length < 1000; i += 1) {
    const ch = text[i];

    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }

    if (ch === '"' && cell.length === 0) {
      quoted = true;
    } else if (ch === delimiter) {
      row.push(cell);
      cell = "";
    } else if (ch === "\r" || ch === "\n") {
      row.push(cell);
      // Match the previous preview behavior by ignoring physically blank lines.
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
      cell = "";
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
    } else {
      cell += ch;
    }
  }

  if (rows.length < 1000 && (cell.length > 0 || row.length > 0)) {
    row.push(cell);
    if (row.length > 1 || row[0] !== "") rows.push(row);
  }

  const esc = (value) =>
    value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return (
    "<table>" +
    rows
      .map((values, rowIndex) => {
        const tag = rowIndex === 0 ? "th" : "td";
        return `<tr>${values.map((value) => `<${tag}>${esc(value)}</${tag}>`).join("")}</tr>`;
      })
      .join("") +
    "</table>"
  );
}

module.exports = { csvToTable };
