// The custom-harness dimension: a harness a person configured, rather than a built-in one.
//
// The five per-model scenarios measure routing: the right connection, the right model, a session
// that survives a switch and a recycle. They say nothing about the configuration a person actually
// builds, which is where this product's own promise lives: your own skill, carrying your own
// script, and control over the tools the runtime brought with it. A harness that answers on every
// model and ignores the skill you wrote is not working.
//
//   BASE=https://your-instance HR_USER=… HR_PASS=… BASES=codex,claude-code,pi node custom-harness.mjs
//
// One turn per base, not per model: this tests what the harness carries, not where the turn routed.
// Costs one short turn each.
import { chromium } from 'playwright';
import crypto from 'node:crypto';

const BASE = process.env.BASE;
const BASES = (process.env.BASES || 'codex,claude-code,hermes,pi,dsh,opencode,kilo,qwen,gemini,cline,omp,goose,kimi,minimax,grok,aider,openhands,cheetahclaws,agentzero').split(',');   // every built-in chat harness, all nineteen (systemone runs decision models only)
const RESULTS = process.env.RESULTS || 'results-custom.json';
// A harness's other kind of tool is an MCP server. A self-contained instance hosts only the
// database and media servers, one needing a database and the other costing real money per call, so
// this half uses a public one: no key, no account, stable tool names. MCP_URL=off skips it (an
// instance with no egress is not a failing harness), and any other URL overrides it.
const MCP_URL = process.env.MCP_URL || 'https://mcp.deepwiki.com/mcp';
const MCP_NAME = process.env.MCP_NAME || 'deepwiki';
// What a call to it looks like in the record. Backends name MCP calls differently: some record the
// server and tool ("deepwiki.read_wiki_structure"), others only that an MCP tool was used ("mcp").
// The harness declares exactly ONE server, so either shape identifies it.
// What a tool call is named for the judge. omp dispatches MCP tools through its virtual
// filesystem: the model `write`s JSON to xd://mcp__<server>_<tool> and the result comes back as
// the write's result (measured 2026-09-08 on omp 18.1.13: two writes to
// xd://mcp__deepwiki_read_wiki_structure answered the wiki structure). A judge that reads only
// the name sees `write` and calls a served MCP turn a miss, so the call's arguments are read too.
// The same blindness has a second shape: a base that reaches its server through a DISPATCH tool.
// grok's call is always `use_tool {"tool_name": "deepwiki__read_wiki_structure"}`, so a judge reading
// the name alone saw `use_tool`, matched nothing, and scored a SERVED MCP turn a miss — four times on
// 2026-09-29, until the arguments were dumped by hand and the server's own answer was in the reply.
// So the label is the name PLUS the argument fields a dispatcher carries its target in. The name is
// kept in the label (rather than replaced) so a base that calls the tool directly still matches.
const toolLabel = (t) => {
  const name = String((t && t.name) || '');
  const raw = typeof (t && t.arguments) === 'string' ? t.arguments : JSON.stringify((t && t.arguments) || '');
  let a = {}; try { a = JSON.parse(raw || '{}') || {}; } catch { /* not json; the raw string still feeds xd:// below */ }
  const xd = /xd:\/\/(mcp__[A-Za-z0-9_]+)/.exec(raw || '');
  return [name, a.tool_name, a.tool, a.name, a.server, xd ? xd[0] : ''].filter(Boolean).map(String).join(' ');
};
const MCP_TOOL = new RegExp(`(^|[^a-z])mcp([^a-z]|$)|${MCP_NAME}|read_wiki_structure|read_wiki_contents|ask_question`, 'i');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TERMINAL = new Set(['done', 'completed', 'failed', 'incomplete', 'cancelled']);
const log = (s) => console.log(`${new Date().toISOString()} ${s}`);

// The token lives ONLY inside the script, never in SKILL.md and never in the prompt, so an answer
// that carries it came from the bundle rather than from the model's imagination.
const token = 'STAMP-' + crypto.randomBytes(6).toString('hex');
const SKILL = (name, nonce) => ({
  name,
  files: [
    { path: 'SKILL.md', content: [
        `---`, `name: ${name}`,
        `description: Report this harness's build stamp. Use it whenever a stamp is asked for.`,
        `---`, ``,
        `# Build stamp`, ``,
        `From the task's working directory, WITHOUT changing directory first, run this skill's`,
        `own \`stamp.py\` with python3, giving its full path:`, ``,
        '```bash', `python3 <this skill's directory>/stamp.py`, '```', ``,
        `It prints one line and writes \`stamp.txt\` beside the task's other outputs, which is why`,
        `it must run from the task's working directory rather than from this skill's.`, ``,
        `Reply with exactly the line it printed, and nothing else.`,
      ].join('\n') },
    // stamp.txt carries the harness's ENV nonce, which is nowhere in this bundle. A `script_ran`
    // judged on the file merely EXISTING was faked on 2026-09-29: with the shell withheld, minimax's
    // agent called `skill`, read this script, and hand-wrote stamp.txt carrying the bundle's token —
    // the claim passed with nothing executed. The nonce reaches the file only through a process that
    // really ran, so the two arms separate. The printed line keeps the bundle token, which is what
    // `skill_reached` reads.
    { path: 'stamp.py', content: [
        `# Writes the harness's env stamp beside the task's other outputs, and prints the bundle's.`,
        `import os, pathlib`,
        `stamp = ${JSON.stringify(token)}`,
        `pathlib.Path('stamp.txt').write_text(os.environ.get('STAMP_NONCE', 'NO-ENV') + '\\n')`,
        `print(stamp)`,
      ].join('\n') },
  ],
});

const b = await chromium.launch({ ignoreHTTPSErrors: !!process.env.IGNORE_TLS });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: !!process.env.IGNORE_TLS });
const page = await ctx.newPage();
const api = (path, init) => page.evaluate(async ([p, i]) => {
  const r = await fetch(p, i || {}); let j = null; try { j = await r.json(); } catch { /* not json */ }
  return { status: r.status, json: j };
}, [path, init]);
const results = {};

// The withheld tool must be one THIS base really has, and one the fixture does not need.
//
// Withholding a SHELL looks like the strongest choice and is the wrong one here: this dimension's
// other claim is that the skill's script RAN, and the script runs through the shell. Measured on grok
// 2026-09-30 with run_terminal_command withheld: stamp.txt was produced, `script_ran` was false
// because the file did not carry the env nonce, and the row could never pass. The two claims are not
// jointly satisfiable in one harness. That conflict was invisible while a fixed `WebSearch` — a tool
// no base has — was withheld, because the policy claim was then vacuous.
//
// So: withhold a real tool the fixture never uses. Execution, file and search tools are what the skill
// and the MCP turn need; anything else is fair game, preferred in this order. A base that publishes
// nothing else records the claim as unmeasurable rather than as a pass.
// What the fixture itself needs, by every naming a base has used here: something that EXECUTES (the
// skill's script), something that reads or writes FILES, whatever loads a SKILL, and the MCP path.
// Agent Zero names its file tool `text_editor` and its loader `skills_tool`, so a list written from
// grok's and minimax's names alone picked `text_editor` — the tool the fixture writes with.
const NEEDED_ID = /^(bash|shell|execute|run_command|run_terminal_command|terminal|code_execution_tool|python.*|node.*|read|read_file|write|write_file|edit|file_edit(or)?|text_editor|str_replace.*|create_file|view|search_replace|apply_patch|glob|grep|list_dir|ls|skills?_?tool|skill|task|search_tool|use_tool|mcp.*)$/i;
const PREFERRED = /^(todo_write|todowrite|todo|web_?fetch|web_?search|browser.*|board_.*|link_pr|goal|wait)$/i;
const pickDisabled = (tools) => {
  const names = (tools || []).map((t) => String((t && t.name) || t || '')).filter(Boolean);
  return names.find((n) => PREFERRED.test(n)) || names.find((n) => !NEEDED_ID.test(n)) || null;
};
const baseTools = {};

// Did the script REALLY run? stamp.txt must exist AND carry the harness's env nonce, which appears
// nowhere the agent can read. Returns false when the file is absent, unreadable or holds anything else.
const scriptReallyRan = async (sid, files, nonce) => {
  if (!files.some((f) => String(f).includes('stamp.txt'))) return false;
  const list = await api(`/api/harness/v1/sessions/${sid}/files`);
  const item = ((list.json && (list.json.files || list.json.items)) || [])
    .find((f) => String(f.filename || f.name || '').includes('stamp.txt'));
  if (!item || !item.file_id) return false;
  const body = await page.evaluate(async (u) => {
    const r = await fetch(u); return r.ok ? await r.text() : null;
  }, `/api/harness/v1/containers/${sid}/files/${item.file_id}/content`).catch(() => null);
  return typeof body === 'string' && body.includes(nonce);
};

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' }); await sleep(2000);
  if (page.url().includes('/login')) {
    const set = async (sel, v) => page.$eval(sel, (el, x) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, x);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, v);
    await set('#sh-user', process.env.HR_USER || 'harnessrouter');
    await set('#sh-pass', process.env.HR_PASS);
    await page.click('button[type=submit]');
    await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 60000 });
  }
  await sleep(1500);

  // Each base's own tool ids, so the tool withheld below is one the base actually has.
  const basesResp = await api('/api/harness/v1/bases');
  for (const b of ((basesResp.json && basesResp.json.bases) || [])) baseTools[b.id] = b.tools || [];

  // Probe the public server once. If it is down, its rows are skipped and say so: a third party
  // being unreachable is not evidence about this product.
  let mcpUp = false;
  if (MCP_URL !== 'off') {
    const probe = await page.evaluate(async (u) => {
      try {
        const r = await fetch(u, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
          body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'matrix', version: '1' } } }) });
        return { ok: r.ok, status: r.status };
      } catch (e) { return { ok: false, status: String(e).slice(0, 80) }; }
    }, MCP_URL).catch(() => ({ ok: false, status: 'unreachable' }));
    mcpUp = !!probe.ok;
    log(`MCP ${MCP_URL} reachable=${mcpUp} (${probe.status})`);
  }

  for (const base of BASES) {
    const rec = { base, at: new Date().toISOString() };
    let hid = null;
    try {
      // A harness a person would build: its own skill (with its own script), and one inherited
      // tool switched off, which is the other half of what the Tools panel offers.
      // The withheld tool is taken from THIS base's own catalog. A fixed `WebSearch` was withheld
      // before, and minimax, kilo, qwen, gemini, cline, kimi and aider have no tool by that name —
      // so "the withheld tool went unused" was true of a tool that never existed, and read as a pass
      // on seven columns. Measured against a real tool the claim bites: grok's model reached the same
      // shell through `monitor` after its shell tool was withheld, and minimax's subagent did not
      // inherit the denial (2026-09-28/29).
      const disabledId = pickDisabled(baseTools[base]);
      const nonce = crypto.randomUUID();
      const created = await api('/api/harness/v1/harnesses', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: `matrix custom ${base}`, base,
          system_prompt: 'You follow your skills exactly.',
          skills: [SKILL('matrix-stamp', nonce)],
          // the stamp the script must read: it exists ONLY here, never in a prompt or a skill file
          env: { STAMP_NONCE: nonce },
          disabled_tools: disabledId ? [disabledId] : [],
          mcp_servers: MCP_URL === 'off' ? [] : [{ name: MCP_NAME, url: MCP_URL, transport: 'http' }],
        }),
      });
      rec.created = created.status;
      hid = created.json && (created.json.id || created.json.harness_id);
      if (!hid) { rec.why = `create failed: HTTP ${created.status}`; results[base] = rec; log(`CUSTOM ${base} FAIL ${rec.why}`); continue; }

      // the skill and the disabled tool must be what the server stored, not just what was sent
      const back = await api(`/api/harness/v1/harnesses/${hid}`);
      const h = back.json || {};
      rec.skill_stored = ((h.skills || []).some((s) => (s.name || s.id) === 'matrix-stamp'));
      rec.tool_disabled_stored = disabledId
        ? (h.disabledTools || h.disabled_tools || []).includes(disabledId) : null;
      rec.mcp_stored = MCP_URL === 'off' ? null
        : (h.mcpServers || h.mcp_servers || []).some((m) => String(m.name || '') === MCP_NAME);

      const t0 = Date.now();
      const turn = await api('/api/harness/v1/responses', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input: 'Report this harness build stamp.', stream: false, store: true,
                               metadata: { harness_id: hid } }),
      });
      rec.turn_status = turn.status;
      const sid = turn.json && (turn.json.session_id || (turn.json.metadata || {}).session_id);
      rec.sid = sid || null;
      if (!sid) { rec.why = `no session: HTTP ${turn.status}`; results[base] = rec; log(`CUSTOM ${base} FAIL ${rec.why}`); continue; }

      let last = null;
      for (let i = 0; i < 140; i++) {
        await sleep(3000);
        const feed = await api(`/api/harness/v1/sessions/${sid}/turns`);
        const turns = (feed.json && feed.json.turns) || [];
        const t = turns[turns.length - 1];
        if (t && TERMINAL.has(String(t.status)) && (t.assistant || t.error)) { last = t; break; }
      }
      // produced files are attached a few seconds AFTER the turn goes terminal
      for (let i = 0; i < 12 && last && !(last.files || []).length; i++) {
        await sleep(3000);
        const feed = await api(`/api/harness/v1/sessions/${sid}/turns`);
        const turns = (feed.json && feed.json.turns) || [];
        last = turns[turns.length - 1] || last;
      }
      rec.s = Math.round((Date.now() - t0) / 1000);
      rec.status = last && last.status;
      const answer = String((last && last.assistant) || '');
      const files = ((last && last.files) || []).map((f) => f.filename || f.name || '');
      const tools = ((last && last.tools) || []).map(toolLabel);
      // The tool NAMES, separately: the label above deliberately carries argument text for the MCP
      // judge, and the withheld-tool claim is an EXACT id comparison that such a label would break.
      const toolNames = ((last && last.tools) || []).map((t) => String((t && t.name) || ''));
      rec.files = files; rec.tools = tools;
      // a failed turn has to say why, or the row teaches nothing
      rec.error = String((last && (last.error || last.incomplete_reason)) || '').slice(0, 300);
      // the three claims, each read from the stored record
      rec.skill_reached = answer.includes(token);              // the bundle got to the agent
      rec.script_ran = await scriptReallyRan(sid, files, nonce);    // its script actually executed
      rec.disabled_tool = disabledId || null;
      rec.disabled_tool_unused = disabledId ? !toolNames.some((n) => n === disabledId) : null;
      // The MCP half, in the same harness and the same session: a second turn that can only be
      // answered by calling the declared server. Judged on the CALL, not on what it returned: a
      // public server's prose is not ours to pin, but a tool call is a fact in the record.
      if (MCP_URL !== 'off' && mcpUp && rec.skill_reached) {
        const m0 = Date.now();
        await api('/api/harness/v1/responses', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ input: `Use your ${MCP_NAME} tool to read the wiki structure of the repository modelcontextprotocol/servers, then reply with one topic it lists. Use the tool; do not answer from memory.`,
                                 stream: false, store: true, metadata: { harness_id: hid, session_id: sid } }),
        });
        let mlast = null;
        for (let i = 0; i < 100; i++) {
          await sleep(3000);
          const feed = await api(`/api/harness/v1/sessions/${sid}/turns`);
          const turns = (feed.json && feed.json.turns) || [];
          const t = turns[turns.length - 1];
          if (turns.length > 1 && t && TERMINAL.has(String(t.status)) && (t.assistant || t.error)) { mlast = t; break; }
        }
        const mtools = ((mlast && mlast.tools) || []).map(toolLabel);
        rec.mcp_s = Math.round((Date.now() - m0) / 1000);
        rec.mcp_status = mlast && mlast.status;
        rec.mcp_tools = mtools;
        rec.mcp_called = mtools.some((t) => MCP_TOOL.test(t));
        rec.mcp_error = String((mlast && (mlast.error || mlast.incomplete_reason)) || '').slice(0, 200);
      } else if (MCP_URL !== 'off' && !mcpUp) {
        rec.mcp_called = null; rec.mcp_error = 'skipped: the public MCP server was unreachable';
      }
      // the MCP half only counts against a row when it actually ran
      const mcpOk = MCP_URL === 'off' || rec.mcp_called === null || (rec.mcp_stored && rec.mcp_called);
      // null = this base publishes no tool to withhold, so the claim was not measurable here. It is
      // carried as null rather than folded into a pass: an unmeasurable claim is not a met one.
      const denyOk = rec.disabled_tool_unused === null || (rec.tool_disabled_stored && rec.disabled_tool_unused);
      rec.ok = !!(rec.skill_stored && rec.skill_reached && rec.script_ran && denyOk && mcpOk);
      rec.why = rec.ok ? '' : [
        rec.skill_stored ? '' : 'the skill was not stored on the harness',
        rec.disabled_tool_unused !== null && !rec.tool_disabled_stored ? `the disabled tool ${disabledId} was not stored` : '',
        rec.skill_reached ? '' : `the answer does not carry the skill's stamp: ${answer.slice(-160)}`,
        rec.script_ran ? '' : `the skill's script did not run: stamp.txt is absent or does not carry the harness's env nonce (files: ${files.join(',') || 'none'})`,
        rec.disabled_tool_unused === false ? `the withheld tool ${disabledId} was called: ${toolNames.join(',')}` : '',
        rec.error ? `the turn ended: ${rec.error}` : '',
        (MCP_URL !== 'off' && rec.mcp_called === false && !rec.mcp_stored) ? 'the MCP server was not stored on the harness' : '',
        (MCP_URL !== 'off' && rec.mcp_called === false && rec.mcp_stored)
          ? `the declared MCP server was never called (tools: ${(rec.mcp_tools || []).join(',') || 'none'})${rec.mcp_error ? '; ' + rec.mcp_error : ''}` : '',
      ].filter(Boolean).join('; ');
      log(`CUSTOM ${base} ${rec.ok ? 'ok' : 'FAIL'} ${rec.s}s mcp=${rec.mcp_called === null ? 'skipped' : rec.mcp_called} ${rec.why}`);
      if (sid) await api(`/api/harness/v1/sessions/${sid}`, { method: 'DELETE' });
    } catch (e) {
      rec.error = String(e).slice(0, 300); log(`CUSTOM ${base} ERROR ${rec.error}`);
    } finally {
      if (hid) await api(`/api/harness/v1/harnesses/${hid}`, { method: 'DELETE' }).catch(() => {});
      results[base] = rec;
      await page.evaluate(([p, r]) => fetch(p, { method: 'POST' }).catch(() => r), ['/noop', null]).catch(() => {});
    }
  }
  const fs = await import('node:fs');
  fs.writeFileSync(RESULTS, JSON.stringify(results, null, 1));
  const ok = Object.values(results).filter((r) => r.ok).length;
  log(`CUSTOM_DONE ${ok} of ${Object.keys(results).length} bases carried their own skill, script and tool policy`);
} finally { await b.close(); }
