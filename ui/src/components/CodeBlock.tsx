'use client';
// A code card: a quiet header (language + copy) over a light syntax-highlighted body.
import React, { useState } from 'react';
import { PrismAsync as SyntaxHL } from 'react-syntax-highlighter';
import oneLightTheme from 'react-syntax-highlighter/dist/esm/styles/prism/one-light';

export function CodeBlock({ code, lang = 'bash' }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  const label = lang === 'bash' || lang === 'sh' ? 'cURL' : lang === 'json' ? 'JSON'
    : lang === 'python' ? 'Python' : lang === 'javascript' || lang === 'js' ? 'Node' : lang.toUpperCase();
  return (
    <div className="apidoc-code">
      <div className="apidoc-code-head">
        <span className="apidoc-code-lang">{label}</span>
        <button className="apidoc-code-copy" onClick={() => { navigator.clipboard?.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>{copied ? 'Copied' : 'Copy'}</button>
      </div>
      <SyntaxHL language={lang} style={oneLightTheme}
        customStyle={{ margin: 0, padding: '14px 16px', background: 'transparent', fontSize: 12.5, lineHeight: 1.6, whiteSpace: 'pre', overflowX: 'auto' }}
        codeTagProps={{ style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: '#383A42' } }}>{code}</SyntaxHL>
    </div>
  );
}
