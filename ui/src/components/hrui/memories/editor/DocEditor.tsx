// The text of a live record: everyone who has it open edits it together and sees each other's cursors. The document
// and the people in it come from the page (useLiveRecord), so this only draws and edits.
//
// A record is a few sentences an agent wrote for another agent to read. So it is edited as text, with no block
// chrome: no insert button, no drag grip, no block menu. Markdown typed at the start of a line (#, -, 1., >) still
// becomes a heading or a list, the way agents write it.
//
// Its styles live in memories.css under #hrui. The console resets everything inside #hrui (`all:revert`, keyed on
// the ID), so a stylesheet of plain classes, a CSS module or the editor's own injected rules, never reaches in here.
'use client';

import { useEffect, useMemo } from 'react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Collaboration from '@tiptap/extension-collaboration';
import CollaborationCursor from '@tiptap/extension-collaboration-cursor';
import type { Awareness } from 'y-protocols/awareness';
import type * as Y from 'yjs';
import { peerColor } from './presence';

export interface DocEditorProps {
  /** The record's live document: its body is the 'default' fragment. */
  doc: Y.Doc;
  /** Who else is here. Anything with an awareness; the page owns the connection. */
  provider: { awareness: Awareness } | null;
  currentUser: { id: string; name: string };
  placeholder?: string;
  readOnly?: boolean;
  className?: string;
}

type Someone = { id?: unknown; name?: unknown } | null | undefined;

/** A person's color comes from who they are, the same on every record, not from the order they arrived in. */
const colorOf = (u: Someone) => {
  const id = typeof u?.id === 'string' ? u.id.trim().toLowerCase() : '';
  const name = typeof u?.name === 'string' ? u.name.trim().toLowerCase() : '';
  return peerColor(id ? `id:${id}` : name ? `name:${name}` : '__anonymous__');
};
const nameOf = (u: Someone) => (typeof u?.name === 'string' && u.name.trim() ? u.name : 'Someone');

/** #rrggbb at an alpha, for a selection tint in the person's color. */
const tint = (hex: string, alpha: number) => {
  const n = Number.parseInt(/^#[0-9a-f]{6}$/i.test(hex) ? hex.slice(1) : '1e40af', 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

export function DocEditor({ doc, provider, currentUser, placeholder = '', readOnly = false, className }: DocEditorProps) {
  const myColor = useMemo(() => colorOf(currentUser), [currentUser]);

  const editor = useEditor(
    {
      immediatelyRender: false,
      editable: !readOnly,
      extensions: [
        StarterKit.configure({ history: false }),
        Placeholder.configure({ placeholder }),
        Collaboration.configure({ document: doc }),
        ...(provider
          ? [
              CollaborationCursor.configure({
                provider,
                user: { id: currentUser.id, name: currentUser.name, color: myColor },
                render: (u) => {
                  const caret = document.createElement('span');
                  caret.className = 'collaboration-cursor__caret';
                  caret.style.borderColor = colorOf(u as Someone);
                  const label = document.createElement('span');
                  label.className = 'collaboration-cursor__label';
                  label.style.backgroundColor = colorOf(u as Someone);
                  label.textContent = nameOf(u as Someone);
                  caret.appendChild(label);
                  return caret;
                },
                selectionRender: (u) => ({
                  nodeName: 'span',
                  class: 'collaboration-cursor__selection',
                  style: `background-color: ${tint(colorOf(u as Someone), 0.2)}`,
                  'data-user': nameOf(u as Someone),
                }),
              }),
            ]
          : []),
      ],
    },
    [provider, doc, placeholder, currentUser.id, currentUser.name, myColor],
  );

  useEffect(() => {
    editor?.setEditable(!readOnly);
  }, [editor, readOnly]);

  if (!editor) return <p className="mm-muted">Opening…</p>;
  return <EditorContent editor={editor} className={`mm-ed${className ? ` ${className}` : ''}`} />;
}
