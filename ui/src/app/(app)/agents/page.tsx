'use client';
import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { agentMd } from '@/lib/agentmd';
import { ApiReference, CodeBlock } from '@/components/ApiReference';

const API_BASE = 'https://api.harnessrouter.ai';

const MD_COMPONENTS = {
  // Fenced code blocks (always wrapped in <pre><code>) render as the light CodeBlock card; inline
  // code keeps the default .hr-doc <code> chip.
  pre({ children }: { children?: React.ReactNode }) {
    const el = React.Children.toArray(children)[0] as React.ReactElement<{ className?: string; children?: React.ReactNode }> | undefined;
    const className = el?.props?.className || '';
    const m = /language-(\w+)/.exec(className);
    const code = String(el?.props?.children ?? '').replace(/\n$/, '');
    return <CodeBlock code={code} lang={m?.[1] || 'bash'} />;
  },
};

export default function AgentsPage() {
  const md = agentMd(API_BASE);
  const [copied, setCopied] = useState(false);

  // On the PAGE, the markdown's compact "## Runtime integration reference" section is replaced by
  // the premiere ApiReference components (the former workbench Integrate tab, merged here) —
  // rendering both would repeat every endpoint. The prose walkthrough (Step 0 key gate, boundary,
  // classification gate, Steps 1-4) renders in full before it, and the Done conditions after it.
  // The raw markdown keeps everything for Copy/Download, it's the agent-consumable format.
  const cutIdx = md.indexOf('\n## Runtime integration reference');
  const tailIdx = md.indexOf('\n## Done conditions');
  const head = cutIdx > 0 ? md.slice(0, cutIdx) : md;
  const tail = cutIdx > 0 && tailIdx > cutIdx ? md.slice(tailIdx) : '';

  const copy = async () => {
    try { await navigator.clipboard.writeText(md); setCopied(true); setTimeout(() => setCopied(false), 1600); }
    catch { /* clipboard blocked, the Download still works */ }
  };
  const download = () => {
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'AGENTS.md'; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="hr-page">
      <div className="hr-doc-head">
        <div>
          <h1 className="hr-doc-title">AGENTS.md</h1>
          <p className="hr-doc-sub">Drop this into your coding agent (Claude Code, Codex, …). It builds the
            agent feature into your product: your app&apos;s UI and server routes at build time, a configured
            HarnessRouter agent for the end-user tasks at runtime, then tests the whole thing through your app.</p>
        </div>
        <div className="hr-doc-actions">
          <button className="hr-btn" onClick={copy}>{copied ? 'Copied ✓' : 'Copy'}</button>
          <button className="hr-btn primary" onClick={download}>Download AGENTS.md</button>
        </div>
      </div>
      <div className="hr-doc">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{head}</ReactMarkdown>
        <ApiReference />
        {tail && <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{tail}</ReactMarkdown>}
      </div>
    </div>
  );
}
