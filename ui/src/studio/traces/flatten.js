// flatten — canonical stream-json events -> ONE compact row per event, matching the managed-agent
// trace IA. The runner emits the Claude stream-json contract (codex normalized to it server-side),
// each event carrying a server-stamped `_ts`. We pair tool_use<->tool_result by id (the result is
// shown in the row's detail, never as its own row), group a message's parallel tool_uses into a
// single row, and drop scaffolding noise (init / turn.started / item.started). Content (markdown
// essay, tool-use JSON, tool-result) lives in the detail pane, not the list.

export function fmtK(n) {
  if (n == null) return '';
  const v = Number(n);
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v);
}
const pretty = (o) => { try { return JSON.stringify(o, null, 2); } catch { return String(o); } };
function resultText(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.map((c) => (typeof c === 'string' ? c : c.text || pretty(c))).join('\n');
  return content != null ? pretty(content) : '';
}
function toolRole(name) {
  const n = (name || '').toLowerCase();
  if (n === 'bash') return 'bash';
  if (n === 'write' || n === 'edit' || n === 'multiedit') return 'write';
  return 'tool';
}
// the lighter parameter preview shown after a single tool's name
function toolParam(input) {
  const inp = input || {};
  if (inp.command) return String(inp.command);
  if (Array.isArray(inp.changes))
    return inp.changes.map((ch) => `${ch.kind || 'edit'} ${ch.path || ''}`.trim()).filter(Boolean).join(', ');
  if (inp.file_path) return String(inp.file_path);
  if (inp.path) return String(inp.path);
  if (inp.question) return String(inp.question);
  if (inp.query) return String(inp.query);
  const k = Object.keys(inp)[0];
  if (!k) return '';
  const v = inp[k];
  return `${typeof v === 'object' ? JSON.stringify(v) : String(v)}`;
}
// distinct tool names with ×N for repeats, order-preserving: ["A","A","B"] -> "A ×2, B"
function toolNames(tools) {
  const order = [];
  const count = new Map();
  for (const t of tools) {
    const n = t.name || 'Tool';
    if (!count.has(n)) order.push(n);
    count.set(n, (count.get(n) || 0) + 1);
  }
  return order.map((n) => (count.get(n) > 1 ? `${n} ×${count.get(n)}` : n)).join(', ');
}

export function flatten(events) {
  // 1) index tool_results by tool_use_id (shown in the tool row's detail, not as a row)
  const results = new Map();
  for (const ev of events || []) {
    if (ev.type !== 'user') continue;
    const msg = ev.message || {};
    if (!Array.isArray(msg.content)) continue;
    for (const c of msg.content) {
      if (c.type === 'tool_result')
        results.set(c.tool_use_id, { text: resultText(c.content), is_error: !!c.is_error, ts: ev._ts, clipped: !!ev._clipped });
    }
  }
  // 2) build one compact row per event
  const rows = [];
  let lastAgentText = '';   // to suppress the result row's duplicate of the final agent message
  for (const ev of events || []) {
    const ts = ev._ts;
    const sub = ev.parent_tool_use_id || null;
    const side = !!ev.isSidechain;
    const clip = !!ev._clipped;   // this event's long strings were truncated by the compact load
    switch (ev.type) {
      case 'assistant': {
        const msg = ev.message || {};
        const u = msg.usage || {};
        const tokens = (u.input_tokens != null || u.output_tokens != null)
          ? { in: u.input_tokens, out: u.output_tokens } : null;
        const tools = [];
        for (const c of msg.content || []) {
          if (c.type === 'text' && (c.text || '').trim()) {
            lastAgentText = c.text;
            rows.push({ kind: 'agent', role: 'agent', label: 'Agent', text: c.text, md: true, tokens, ts, sub, side, clipped: clip });
          }
          else if (c.type === 'thinking' && (c.thinking || '').trim())
            rows.push({ kind: 'thinking', role: 'thinking', label: 'Thinking', text: c.thinking, md: false, ts, sub, side, clipped: clip });
          else if (c.type === 'tool_use') {
            const res = results.get(c.id);
            tools.push({ name: c.name || 'Tool', role: toolRole(c.name), input: c.input || {},
              result: res?.text, is_error: !!res?.is_error, id: c.id, rts: res?.ts, clipped: !!res?.clipped });
          }
        }
        if (tools.length) {
          const anyErr = tools.some((t) => t.is_error);
          const durs = tools.map((t) => (t.rts != null && ts != null ? t.rts - ts : null)).filter((x) => x != null);
          rows.push({
            kind: 'tool', role: anyErr ? 'tool' : (tools.length === 1 ? tools[0].role : 'tool'),
            label: toolNames(tools), param: tools.length === 1 ? toolParam(tools[0].input) : '',
            tools, is_error: anyErr, tokens, dur: durs.length ? Math.max(...durs) : null,
            ts, sub, side, tool_use_id: tools[0].id, clipped: clip || tools.some((t) => t.clipped),
          });
        }
        break;
      }
      case 'user': {
        const msg = ev.message || {};
        if (typeof msg.content === 'string') {
          if (msg.content.trim()) rows.push({ kind: 'user', role: 'user', label: 'User', text: msg.content, md: true, ts, sub, clipped: clip });
          break;
        }
        for (const c of msg.content || []) {
          if (c.type === 'text' && (c.text || '').trim())
            rows.push({ kind: 'user', role: 'user', label: 'User', text: c.text, md: true, ts, sub, clipped: clip });
          // tool_result is folded into its tool row (results map) — never its own row
        }
        break;
      }
      case 'result': {
        // The result event is the turn's terminal record (final text + usage + duration).
        const u = ev.usage || {};
        rows.push({
          kind: 'result', role: ev.is_error ? 'error' : 'result', label: ev.is_error ? 'Error' : 'Result',
          text: ev.result || '', md: true, is_error: !!ev.is_error,
          tokens: (u.input_tokens != null || u.output_tokens != null) ? { in: u.input_tokens, out: u.output_tokens } : null,
          dur: ev.duration_ms != null ? ev.duration_ms / 1000 : null, ts, clipped: clip,
        });
        break;
      }
      default:
        break; // drop system/init/turn.started/item.started scaffolding — not part of the clean IA
    }
  }
  // Coalesce consecutive agent/thinking rows into one. Token-level streaming emits many small
  // text-delta events (each an assistant text event), which would otherwise render as dozens of
  // one-word Agent rows; merge adjacent same-kind rows (same lane) back into the whole message.
  const merged = [];
  for (const r of rows) {
    const prev = merged[merged.length - 1];
    if (prev && (r.kind === 'agent' || r.kind === 'thinking') && prev.kind === r.kind
        && prev.sub === r.sub && prev.side === r.side) {
      prev.text = (prev.text || '') + (r.text || '');
      if (r.tokens) prev.tokens = r.tokens;      // keep the last usage stamp
      prev.clipped = prev.clipped || r.clipped;
    } else {
      merged.push({ ...r });
    }
  }
  return merged.map((r, i) => ({ ...r, i }));
}

// Group rows into a main lane + one lane per subagent (parent_tool_use_id), preserving order.
export function lanes(rows) {
  const main = [];
  const subs = new Map();
  for (const r of rows) {
    if (r.sub) {
      if (!subs.has(r.sub)) subs.set(r.sub, []);
      subs.get(r.sub).push(r);
    } else {
      main.push(r);
    }
  }
  return { main, subs };
}
