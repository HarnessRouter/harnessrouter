// Tasteful colored file-type glyphs (pdf red, docx blue, xlsx green, pptx orange, …) via
// react-file-icon, the standard library for this. One wrapper used by file cards + preview.
'use client';
import React from 'react';
import { FileIcon, defaultStyles } from 'react-file-icon';

export function extOf(name: string): string {
  const m = (name || '').toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : '';
}

export function FileTypeIcon({ name, size = 36 }: { name: string; size?: number }) {
  const ext = extOf(name);
  const style = (defaultStyles as Record<string, object>)[ext] || {};
  return (
    <span style={{ width: size, height: Math.round(size * 1.16), display: 'inline-block', flex: '0 0 auto' }}>
      <FileIcon extension={ext || undefined} {...style} />
    </span>
  );
}
