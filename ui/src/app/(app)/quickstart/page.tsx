'use client';
// Quickstart, "Connect a coding agent", per the v2 design: four steps on a rail. Copy AGENTS.md
// and paste it into your coding agent, ask it to build, hand it a workspace API key through its
// secure modal, then manage what it built under Agent harnesses. Progress is kept per browser.
// The API key is created HERE, shown once, and never stored beyond its last four characters.
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { harnessFetch } from '@/lib/hfetch';
import { getSession } from '@/lib/auth';
import { agentMd } from '@/lib/agentmd';
import { useWorkspace } from '@/lib/workspace';
import { track } from '@/lib/analytics';
import { useQuickstart, quickstartDone } from '@/lib/quickstart';

/** The coding agents people paste the guide into, with their own marks. */
const AGENTS = [
  { id: 'codex', name: 'Codex', logo: '/logos/codex.png' },
  { id: 'claude-code', name: 'Claude Code', logo: '/logos/claude.png' },
  { id: 'cursor', name: 'Cursor', logo: '/logos/cursor.svg' },
];
const NEXT = [
  { title: 'Create a harness', body: 'Prompt + runtime + model, reusable', href: '/harnesses' },
  { title: 'Run your first task', body: 'Send a message, watch the trace', href: '/harnesses?h=codex' },
  { title: 'Field an arena run', body: 'Compare configurations on one task', href: '/arena' },
];
const fmtKb = (bytes: number) => `${(bytes / 1024).toFixed(1)} kB`;

export default function QuickstartPage() {
  const { current, defaultId } = useWorkspace();
  const [qs, update] = useQuickstart();
  const md = useMemo(() => agentMd(), []);
  const size = useMemo(() => fmtKb(new TextEncoder().encode(md).length), [md]);
  const preview = useMemo(() => md.split('\n').slice(0, 8).join('\n') + '\n\nRead the complete guide before implementing the integration…', [md]);
  const agent = AGENTS.find((a) => a.id === qs.agent) || AGENTS[0];

  const [minted, setMinted] = useState<string | null>(null);   // the one-time reveal, this visit only
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [keyCopied, setKeyCopied] = useState(false);

  const copyMd = async () => {
    try { await navigator.clipboard.writeText(md); track('agents_guide_copied'); update({ copied: true }); } catch { /* blocked */ }
  };
  async function createKey() {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const s = getSession();
      const org = s?.orgId || '';
      const member = s?.member?.email || s?.member?.id || '';
      const r = await harnessFetch(`/api/harness/v1/orgs/${encodeURIComponent(org)}/keys`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: 'Quickstart integration', member_id: member, workspace: current.id || '', workspace_name: current.name || '',
                               workspace_default: !current.id || current.id === defaultId }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Could not create the key');
      track('api_key_created', { surface: 'quickstart', is_first_key: null, workspace_is_default: !current.id || current.id === defaultId, workspace_id: current.id || null });
      setMinted(d.key); setKeyCopied(false);
      const k = String(d.key || '');
      update({ keyCreated: true, keyHint: `${k.slice(0, k.indexOf('-', 3) + 1 || 3)}••••${k.slice(-4)}` });
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const done = quickstartDone(qs);
  const allDone = done === 4;
  const oneState = qs.pasted ? 'done' : 'active';
  const twoState = qs.asked ? 'done' : 'active';
  const threeState = qs.keyCreated ? 'done' : 'active';
  const fourState = allDone ? 'done' : 'active';

  return (
    <section className="qs" id="view-quickstart">
      <header className="qs-head">
        <h1>Connect a coding agent</h1>
        <p>Copy the guide, paste it into your coding agent, then type the product you want to build. Your agent writes the product; HarnessRouter runs the agents behind it.</p>
        <div className="qs-progress">
          <span className="qs-progress-label">{allDone ? 'All steps done' : `${done} of 4 steps done`}</span>
          <span className="qs-bar"><span className={'qs-bar-fill' + (allDone ? ' is-done' : '')} style={{ width: `${Math.round((done / 4) * 100)}%` }} /></span>
          {allDone && <button type="button" className="qs-reset" onClick={() => { setMinted(null); update({ copied: false, pasted: false, asked: false, keyCreated: false, keyHint: '' }); }}>START OVER</button>}
        </div>
      </header>

      <div className="qs-body">
        <div className="qs-grid">
          {/* 01 */}
          <div className="qs-railcell"><span className="qs-rail" /><span className={'qs-marker is-' + oneState}>{qs.pasted ? '✓' : '01'}</span></div>
          <div className={'qs-card is-' + oneState}>
            <div className="qs-card-head">
              <div>
                <div className="qs-title">Paste AGENTS.md into your coding agent</div>
                <div className="qs-sub">Copy the official instructions and paste them into Codex, Claude Code, Cursor, or another coding agent.</div>
              </div>
              <a className="qs-link" href="/agents" target="_blank" rel="noreferrer">View official source</a>
            </div>
            <div className="qs-doc">
              <div className="qs-doc-head"><span className="qs-doc-name">AGENTS.MD</span><span className="qs-doc-meta">canonical · {size}</span></div>
              <pre className="qs-doc-body" aria-label="AGENTS.md preview">{preview}</pre>
            </div>
            <div className="qs-actions">
              <button type="button" className={'qs-copy' + (qs.copied ? ' is-done' : '')} onClick={() => void copyMd()}>{qs.copied ? 'Copied to clipboard' : 'Copy AGENTS.md'}</button>
              <div className="qs-chips" role="radiogroup" aria-label="Your coding agent">
                {AGENTS.map((a) => (
                  <button key={a.id} type="button" role="radio" aria-checked={a.id === agent.id} className={'qs-chip' + (a.id === agent.id ? ' is-on' : '')} onClick={() => update({ agent: a.id })}>
                    {/* eslint-disable-next-line @next/next/no-img-element -- the agent's own mark, a static asset */}
                    <img className="qs-chip-mark" src={a.logo} alt="" aria-hidden="true" /><span>{a.name}</span>
                  </button>
                ))}
              </div>
              <button type="button" className={'qs-confirm' + (qs.pasted ? ' is-done' : '')} disabled={!qs.copied} title={qs.copied ? undefined : 'Copy AGENTS.md first'}
                onClick={() => { if (qs.copied) { track('quickstart_pasted'); update({ pasted: true }); } }}>{qs.pasted ? 'Pasted' : 'Done pasting'}</button>
            </div>
          </div>

          {/* 02 */}
          <div className="qs-railcell"><span className="qs-rail" /><span className={'qs-marker is-' + twoState}>{qs.asked ? '✓' : '02'}</span></div>
          <div className={'qs-card is-' + twoState}>
            <div className="qs-card-head">
              <div>
                <div className="qs-title">Ask it to build</div>
                <div className="qs-sub">Describe the product or feature you want. The coding agent builds the product interface and connects your backend to server-side agents through HarnessRouter.</div>
              </div>
            </div>
            <div className="qs-kicker">In {agent.name}</div>
            <div className="qs-mock" aria-label={`What you type into ${agent.name}`}>
              <div className="qs-mock-file">
                {/* eslint-disable-next-line @next/next/no-img-element -- the agent's own mark, a static asset */}
                <span className="qs-mock-mark"><img src={agent.logo} alt="" aria-hidden="true" /></span>
                <div><div className="qs-mock-file-name">HarnessRouter AGENTS.md</div><div className="qs-mock-file-meta">Pasted text · {size}</div></div>
                <span className="qs-mock-x" aria-hidden="true">✕</span>
              </div>
              <div className="qs-mock-prompt">Build a product-launch video agent.</div>
              <div className="qs-mock-row">
                <span className="qs-mock-plus" aria-hidden="true">+</span>
                <span className="qs-mock-badge">{agent.name}</span>
                <span className="qs-mock-send" aria-hidden="true">↑</span>
              </div>
            </div>
            <div className="qs-actions">
              <button type="button" className={'qs-confirm' + (qs.asked ? ' is-done' : '')} onClick={() => { track('quickstart_asked'); update({ asked: true }); }}>{qs.asked ? 'Sent to my agent' : 'I sent this to my agent'}</button>
            </div>
          </div>

          {/* 03 */}
          <div className="qs-railcell"><span className="qs-rail" /><span className={'qs-marker is-' + threeState}>{qs.keyCreated ? '✓' : '03'}</span></div>
          <div className={'qs-card is-' + threeState}>
            <div className="qs-card-head">
              <div>
                <div className="qs-title">Add your API key securely</div>
                <div className="qs-sub">When the coding agent opens a secure secret modal, create a Workspace API key and paste it into that modal. The agent stores it as HR_API_KEY and continues the build.</div>
              </div>
            </div>
            <div className="qs-keyrow">
              <button type="button" className={'qs-keybtn' + (qs.keyCreated ? ' is-done' : '')} disabled={busy} onClick={() => void createKey()}>
                {busy ? 'Creating' : qs.keyCreated ? `Key created · ${qs.keyHint}` : 'Create API key'}
              </button>
              <span className="qs-keynote">{qs.keyCreated ? 'Shown once. Paste it into the agent’s secure modal.' : `Scoped to ${current.name}`}</span>
            </div>
            {err && <p className="qs-err" role="alert">{err}</p>}
            {minted && (
              <div className="qs-reveal ph-no-capture">
                <code>{minted}</code>
                <button type="button" className="qs-confirm" onClick={async () => { try { await navigator.clipboard.writeText(minted); setKeyCopied(true); } catch { /* blocked */ } }}>{keyCopied ? 'Copied' : 'Copy key'}</button>
              </div>
            )}
            <div className="qs-warn"><span aria-hidden="true">!</span><span>Paste the key only into the secure modal opened by your coding agent. Never paste it into normal chat, source files, AGENTS.md, browser code, logs, or screenshots.</span></div>
          </div>

          {/* 04 */}
          <div className="qs-railcell"><span className={'qs-marker is-' + fourState}>{allDone ? '✓' : '04'}</span></div>
          <div className={'qs-card is-' + fourState}>
            <div className="qs-title">Manage your harnesses</div>
            <div className="qs-sub">Signing in to Cloud brings you here. Every harness your agent creates shows up under Agent harnesses, with its tasks, traces, and settings.</div>
            <div className="qs-flow">
              <div className="qs-flow-box">Your product</div>
              <span className="qs-flow-arrow" aria-hidden="true">→</span>
              <div className="qs-flow-box is-cloud">HarnessRouter Cloud</div>
            </div>
            <div className="qs-flow-note">Tasks in · progress, files, artifacts, and results out. Hosted tasks run the selected harness in an isolated sandbox.</div>
            <div className="qs-actions qs-actions-last">
              <Link className="qs-open" href="/harnesses">Open Agent harnesses →</Link>
              <span className="qs-ce">Community Edition runs the same flow on your infrastructure.</span>
            </div>
          </div>
        </div>

        {allDone && (
          <div className="qs-done">
            <div className="qs-done-kicker">CONNECTED</div>
            <div className="qs-done-title">Your product can now run agents through HarnessRouter.</div>
            <div className="qs-next">
              {NEXT.map((n) => (
                <Link key={n.title} className="qs-next-card" href={n.href}><span className="qs-next-title">{n.title}</span><span className="qs-next-body">{n.body}</span></Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
