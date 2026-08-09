'use client';

// Beautiful markdown rendering for trace messages + seeded docs — full GitHub-flavored markdown
// (tables, task lists, strikethrough, autolinks, fenced code) via react-markdown + remark-gfm,
// the same renderer the workbench chat uses, so message content reads as rich text everywhere.
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function Markdown({ text, className }) {
  return (
    <div className={'md' + (className ? ' ' + className : '')}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(text || '')}</ReactMarkdown>
    </div>
  );
}
