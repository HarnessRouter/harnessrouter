'use client';
// Monospace identifier chip with click-to-copy. Used for a Harness ID (chrn_… / built-in slug)
// wherever a user needs the value to paste into an integration. Stops row-navigation clicks so
// copying from inside a clickable table row never also opens the row.
import { useState } from 'react';

export function CopyId({ value, className = '' }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="mono-id is-empty">—</span>;
  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* clipboard blocked; the id text is still selectable */ }
  };
  return (
    <button
      type="button"
      className={`mono-id${className ? ' ' + className : ''}`}
      onClick={copy}
      title={copied ? 'Copied' : `Copy ${value}`}
      aria-label={copied ? 'Copied Harness ID' : `Copy Harness ID ${value}`}
    >
      <span className="mono-id-text">{value}</span>
      <iconify-icon className="mono-id-icon" icon={copied ? 'tabler:check' : 'tabler:copy'}></iconify-icon>
    </button>
  );
}
