'use client';
// Quickstart, "Connect a Coding Agent" in three steps. The AGENTS.md content is the primary
// copyable asset; the API key is created in a light modal HERE (name + one-time reveal), never a
// jump to the management page. The full doc stays at /agents as the single source of truth.
import { harnessFetch } from '@/lib/hfetch';
import { useMemo, useState } from 'react';
import { getSession } from '@/lib/auth';
import { agentMd } from '@/lib/agentmd';
import { useWorkspace } from '@/lib/workspace';

export default function QuickstartPage() {
  const { current, defaultId } = useWorkspace();
  const md = useMemo(() => agentMd(), []);
  const preview = useMemo(() => md.split('\n').slice(0, 8).join('\n') + '\n\nRead the complete guide before implementing the integration…', [md]);
  const [copied, setCopied] = useState(false);
  const [modal, setModal] = useState(false);
  const [keyName, setKeyName] = useState('Quickstart integration');
  const [minted, setMinted] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [keyCopied, setKeyCopied] = useState(false);

  const copyMd = async () => {
    try { await navigator.clipboard.writeText(md); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch { /* blocked */ }
  };

  async function mint() {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const s = getSession();
      const org = s?.orgId || '';
      const member = s?.member?.email || s?.member?.id || '';
      const r = await harnessFetch(`/api/harness/v1/orgs/${encodeURIComponent(org)}/keys`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name: keyName.trim() || 'Quickstart integration', member_id: member,
                              workspace: current.id || '', workspace_default: !current.id || current.id === defaultId }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Could not create the key');
      setMinted(d.key);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <section className="view is-active" id="view-quickstart">
      <div className="page">
        <div className="page-header">
          <div><h1>Connect a Coding Agent</h1><p>Paste the guide, describe what you want, then provide one Workspace API key through a secure modal.</p></div>
        </div>
        <div className="quickstart">
          <div className="quickstart-steps">
            <section className="quickstart-step">
              <span className="step-number">1</span>
              <h2>Paste into your coding agent</h2>
              <div className="quickstart-copy">
                <p>Copy the official instructions and paste them into Codex, Claude Code, or another coding agent.</p>
                <pre className="agent-preview" aria-label="AGENTS.md preview">{preview}</pre>
                <div className="quickstart-actions">
                  <button className="button primary" type="button" onClick={() => void copyMd()}><iconify-icon icon="tabler:copy"></iconify-icon>Copy full AGENTS.md</button>
                  <a className="button" href="/agents" target="_blank" rel="noreferrer">View official source</a>
                  <span className="copy-state" role="status" aria-live="polite">{copied ? 'Copied' : ''}</span>
                </div>
              </div>
            </section>
            <section className="quickstart-step">
              <span className="step-number">2</span>
              <h2>Ask it to build</h2>
              <div className="quickstart-copy">
                <p>Describe the product or feature you want. The coding agent will build the host product and add the server-side HarnessRouter integration.</p>
                <pre className="agent-preview" aria-label="Example build request">Build a contract-review app that lets users upload an agreement, streams progress, renders the result, and supports follow-up revisions.</pre>
              </div>
            </section>
            <section className="quickstart-step">
              <span className="step-number">3</span>
              <h2>Add your API key securely</h2>
              <div className="quickstart-copy">
                <p>When the coding agent opens a secure secret modal, create an API key for <span className="workspace-name">{current.name}</span> and paste it into that modal. The agent stores it as <code>HR_API_KEY</code> and continues the build.</p>
                <button className="button" type="button" onClick={() => { setMinted(null); setErr(''); setModal(true); }}><iconify-icon icon="tabler:key"></iconify-icon>Create API Key</button>
                <div className="security-note"><iconify-icon icon="tabler:shield-lock"></iconify-icon><span>Paste the key only into the secure modal opened by your coding agent. Never paste it into normal chat, source files, AGENTS.md, browser code, logs, or screenshots.</span></div>
              </div>
            </section>
          </div>
        </div>
      </div>

      {modal && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="qkTitle" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><h2 id="qkTitle">Create API Key</h2><p>Create a key for <span className="workspace-name">{current.name}</span> without leaving Quickstart.</p></div>
              <button className="icon-button modal-close" type="button" aria-label="Close dialog" onClick={() => setModal(false)}><iconify-icon icon="tabler:x"></iconify-icon></button>
            </div>
            {!minted ? (
              <div className="modal-body">
                <div className="field-stack">
                  <div className="field"><label htmlFor="qkName">Key name</label>
                    <input id="qkName" value={keyName} onChange={(e) => setKeyName(e.target.value)} autoFocus /></div>
                  {err && <div className="notice"><iconify-icon icon="tabler:alert-triangle"></iconify-icon><div><strong>Could not create</strong>{err}</div></div>}
                </div>
                <div className="modal-actions">
                  <button className="button" type="button" onClick={() => setModal(false)} disabled={busy}>Cancel</button>
                  <button className="button primary" type="button" onClick={() => void mint()} disabled={busy}>{busy ? 'Creating…' : 'Create API Key'}</button>
                </div>
              </div>
            ) : (
              <div className="modal-body">
                <div className="key-reveal"><code>{minted}</code><span>This key is shown once. Copy it now, then paste it into the secure modal opened by your coding agent.</span></div>
                <div className="security-note"><iconify-icon icon="tabler:shield-lock"></iconify-icon><span>Never paste this key into normal chat, source files, browser code, logs, or screenshots.</span></div>
                <div className="modal-actions">
                  <span className="copy-state" role="status" aria-live="polite">{keyCopied ? 'Copied' : ''}</span>
                  <button className="button" type="button" onClick={async () => { try { await navigator.clipboard.writeText(minted); setKeyCopied(true); } catch { /* blocked */ } }}>
                    <iconify-icon icon={keyCopied ? 'tabler:check' : 'tabler:copy'}></iconify-icon>{keyCopied ? 'Copied' : 'Copy API Key'}</button>
                  <button className="button primary" type="button" onClick={() => setModal(false)}>Done</button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
