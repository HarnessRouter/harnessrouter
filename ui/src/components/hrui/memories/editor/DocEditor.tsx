// The block editor of a live record: rows you can drag, a command menu, and everyone's cursors. The document and
// the people in it come from the page (useLiveRecord), so this only draws and edits.
'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { EditorContent, useEditor, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Collaboration from '@tiptap/extension-collaboration';
import CollaborationCursor from '@tiptap/extension-collaboration-cursor';
import type { Awareness } from 'y-protocols/awareness';
import { peerColor } from './presence';
import { Fragment, type Node as ProseMirrorNode, type Schema } from '@tiptap/pm/model';
import { TextSelection } from '@tiptap/pm/state';
import { GripVertical, Plus } from 'lucide-react';
import type * as Y from 'yjs';
import styles from './DocEditor.module.css';

type InsertMode = 'above' | 'below';

interface SlashRange {
  from: number;
  to: number;
}

type CommandKind =
  | 'text'
  | 'heading1'
  | 'heading2'
  | 'heading3'
  | 'bulletList'
  | 'orderedList'
  | 'blockquote'
  | 'codeBlock'
  | 'divider';

interface CommandMenuItem {
  kind: CommandKind;
  label: string;
  markdown: string;
  keywords: string[];
}

type CommandMenuState =
  | {
      mode: 'slash';
      x: number;
      y: number;
      range: SlashRange;
      query: string;
    }
  | {
      mode: 'row';
      x: number;
      y: number;
      rowPos: number;
      insertMode: InsertMode;
      query: string;
    };

interface TopLevelBlock {
  index: number;
  pos: number;
  node: ProseMirrorNode;
}

interface RowAnchor {
  pos: number;
  nodeSize: number;
  top: number;
  height: number;
  lineHeight: number;
}

interface DropTarget {
  insertPos: number;
  top: number;
}

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

const BLOCK_SELECTOR = 'p, h1, h2, h3, h4, h5, h6, ul, ol, blockquote, pre, hr';
const COMMAND_MENU_WIDTH = 320;
const COMMAND_MENU_GAP = 8;
const COMMAND_MENU_MARGIN = 12;
const COMMAND_MENU_ESTIMATED_HEIGHT = 420;
const CURSOR_COLOR_PALETTE = [
  '#1e40af',
  '#c2410c',
  '#15803d',
  '#6d28d9',
  '#be123c',
  '#0e7490',
  '#1e3a8a',
  '#b45309',
  '#166534',
  '#7e22ce',
  '#991b1b',
  '#115e59',
  '#4338ca',
  '#4d7c0f',
  '#047857',
  '#86198f',
  '#7f1d1d',
  '#155e75',
  '#312e81',
  '#3f6212',
  '#0f766e',
  '#9d174d',
  '#075985',
  '#4c1d95',
  '#b91c1c',
  '#0369a1',
  '#334155',
  '#1f2937',
  '#5b21b6',
  '#0c4a6e',
  '#3b0764',
  '#a16207',
] as const;
const COMMAND_ITEMS: CommandMenuItem[] = [
  {
    kind: 'text',
    label: 'Text',
    markdown: '',
    keywords: ['text', 'paragraph', 'plain'],
  },
  {
    kind: 'heading1',
    label: 'Heading 1',
    markdown: '#',
    keywords: ['h1', 'heading', 'title'],
  },
  {
    kind: 'heading2',
    label: 'Heading 2',
    markdown: '##',
    keywords: ['h2', 'heading', 'section'],
  },
  {
    kind: 'heading3',
    label: 'Heading 3',
    markdown: '###',
    keywords: ['h3', 'heading', 'subsection'],
  },
  {
    kind: 'bulletList',
    label: 'Bulleted list',
    markdown: '-',
    keywords: ['list', 'bullet', 'unordered'],
  },
  {
    kind: 'orderedList',
    label: 'Numbered list',
    markdown: '1.',
    keywords: ['list', 'numbered', 'ordered'],
  },
  {
    kind: 'blockquote',
    label: 'Quote',
    markdown: '>',
    keywords: ['quote', 'blockquote'],
  },
  {
    kind: 'codeBlock',
    label: 'Code block',
    markdown: '```',
    keywords: ['code', 'snippet', 'pre'],
  },
  {
    kind: 'divider',
    label: 'Divider',
    markdown: '---',
    keywords: ['divider', 'separator', 'rule'],
  },
];

const slugify = (text: string) =>
  text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-');

const clamp = (value: number, min: number, max: number) => {
  if (Number.isNaN(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
};

const hexToRgba = (hex: string, alpha: number) => {
  const normalized = hex.replace('#', '').trim();
  const valid =
    normalized.length === 3 || normalized.length === 6
      ? normalized
      : '1e40af';
  const expanded =
    valid.length === 3
      ? `${valid[0]}${valid[0]}${valid[1]}${valid[1]}${valid[2]}${valid[2]}`
      : valid;
  const numeric = Number.parseInt(expanded, 16);
  if (Number.isNaN(numeric)) {
    return `rgba(30, 64, 175, ${alpha})`;
  }

  const r = (numeric >> 16) & 255;
  const g = (numeric >> 8) & 255;
  const b = numeric & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const resolvePresenceKey = (
  user: { id?: unknown; name?: unknown } | null | undefined
) => {
  if (user && typeof user.id === 'string' && user.id.trim()) {
    return `id:${user.id.trim().toLowerCase()}`;
  }
  if (user && typeof user.name === 'string' && user.name.trim()) {
    return `name:${user.name.trim().toLowerCase()}`;
  }
  return '__anonymous__';
};

const getSafeEditorView = (editor: Editor) => {
  const view = (editor as unknown as { view?: Record<string, unknown> }).view;
  if (!view) {
    return null;
  }
  if (!('dom' in view) || !view.dom) {
    return null;
  }
  if (typeof view.nodeDOM !== 'function') {
    return null;
  }
  return view;
};

const getNodeDOMSafe = (view: Record<string, unknown>, pos: number) => {
  const nodeDom = view.nodeDOM as ((position: number) => Node | null) | undefined;
  if (!nodeDom) {
    return null;
  }
  try {
    return nodeDom(pos);
  } catch {
    return null;
  }
};

const getPosAtCoordsSafe = (view: Record<string, unknown>, left: number, top: number) => {
  const posAtCoords = view.posAtCoords as
    | ((coords: { left: number; top: number }) => { pos: number } | null)
    | undefined;
  if (!posAtCoords) {
    return null;
  }
  try {
    return posAtCoords({ left, top });
  } catch {
    return null;
  }
};

const getTopLevelRowDom = (view: Record<string, unknown>, index: number, pos: number) => {
  const directNode = getNodeDOMSafe(view, pos);
  if (directNode instanceof HTMLElement) {
    return directNode;
  }

  const viewDom = view.dom;
  if (viewDom instanceof HTMLElement) {
    const fallbackChild = viewDom.children.item(index);
    if (fallbackChild instanceof HTMLElement) {
      return fallbackChild;
    }
  }

  return null;
};

const getTopLevelPositionByIndex = (doc: ProseMirrorNode, index: number) => {
  let position = 0;
  for (let i = 0; i < index; i += 1) {
    position += doc.child(i).nodeSize;
  }
  return position;
};

const getTopLevelBlockAtPos = (doc: ProseMirrorNode, pos: number): TopLevelBlock | null => {
  if (doc.childCount === 0) {
    return null;
  }

  const targetPos = clamp(pos, 0, Math.max(0, doc.content.size));
  let currentPos = 0;

  for (let index = 0; index < doc.childCount; index += 1) {
    const node = doc.child(index);
    const endPos = currentPos + node.nodeSize;

    if (targetPos < endPos || index === doc.childCount - 1) {
      return {
        index,
        pos: currentPos,
        node,
      };
    }

    currentPos = endPos;
  }
  return null;
};

const clampMenuPosition = (
  shellRect: DOMRect,
  x: number,
  y: number,
  estimatedHeight = COMMAND_MENU_ESTIMATED_HEIGHT,
  preferAbove = false
): {
  x: number;
  y: number;
} => {
  const clampedX = clamp(
    x,
    COMMAND_MENU_MARGIN,
    Math.max(COMMAND_MENU_MARGIN, shellRect.width - COMMAND_MENU_WIDTH - COMMAND_MENU_MARGIN)
  );
  const maxY = Math.max(COMMAND_MENU_MARGIN, shellRect.height - estimatedHeight - COMMAND_MENU_MARGIN);
  let desiredY = y;

  if (preferAbove) {
    desiredY = y - estimatedHeight - COMMAND_MENU_GAP * 2;
  } else if (desiredY > maxY) {
    const aboveCandidate = y - estimatedHeight - COMMAND_MENU_GAP * 2;
    if (aboveCandidate >= COMMAND_MENU_MARGIN) {
      desiredY = aboveCandidate;
    }
  }

  return {
    x: clampedX,
    y: clamp(desiredY, COMMAND_MENU_MARGIN, maxY),
  };
};

const buildNodesForCommand = (
  schema: Schema,
  command: CommandKind
): { nodes: ProseMirrorNode[]; selectionOffset: number } | null => {
  const paragraph = schema.nodes.paragraph;
  if (!paragraph) {
    return null;
  }

  if (command === 'text') {
    return {
      nodes: [paragraph.create()],
      selectionOffset: 1,
    };
  }

  if (command === 'heading1' || command === 'heading2' || command === 'heading3') {
    const heading = schema.nodes.heading;
    if (!heading) {
      return null;
    }
    const level = command === 'heading1' ? 1 : command === 'heading2' ? 2 : 3;
    return {
      nodes: [heading.create({ level })],
      selectionOffset: 1,
    };
  }

  if (command === 'bulletList' || command === 'orderedList') {
    const listItem = schema.nodes.listItem;
    const listNode = command === 'bulletList' ? schema.nodes.bulletList : schema.nodes.orderedList;
    if (!listItem || !listNode) {
      return null;
    }
    const item = listItem.create(null, paragraph.create());
    const list = command === 'orderedList' ? listNode.create({ order: 1 }, item) : listNode.create(null, item);
    return {
      nodes: [list],
      selectionOffset: 3,
    };
  }

  if (command === 'blockquote') {
    const blockquote = schema.nodes.blockquote;
    if (!blockquote) {
      return null;
    }
    return {
      nodes: [blockquote.create(null, paragraph.create())],
      selectionOffset: 2,
    };
  }

  if (command === 'codeBlock') {
    const codeBlock = schema.nodes.codeBlock;
    if (!codeBlock) {
      return null;
    }
    return {
      nodes: [codeBlock.create()],
      selectionOffset: 1,
    };
  }

  const horizontalRule = schema.nodes.horizontalRule;
  if (!horizontalRule) {
    return null;
  }
  const rule = horizontalRule.create();
  return {
    nodes: [rule, paragraph.create()],
    selectionOffset: rule.nodeSize + 1,
  };
};

const executeSlashCommand = (editor: Editor, command: CommandKind, range: SlashRange) => {
  editor.chain().focus().deleteRange(range).run();

  switch (command) {
    case 'text':
      editor.chain().focus().setParagraph().run();
      return;
    case 'heading1':
      editor.chain().focus().setHeading({ level: 1 }).run();
      return;
    case 'heading2':
      editor.chain().focus().setHeading({ level: 2 }).run();
      return;
    case 'heading3':
      editor.chain().focus().setHeading({ level: 3 }).run();
      return;
    case 'bulletList':
      editor.chain().focus().setParagraph().toggleBulletList().run();
      return;
    case 'orderedList':
      editor.chain().focus().setParagraph().toggleOrderedList().run();
      return;
    case 'blockquote':
      editor.chain().focus().setParagraph().toggleBlockquote().run();
      return;
    case 'codeBlock':
      editor.chain().focus().toggleCodeBlock().run();
      return;
    case 'divider':
      editor.chain().focus().setHorizontalRule().createParagraphNear().run();
      return;
    default:
      return;
  }
};

const resolveRowAnchorFromTarget = (
  editor: Editor,
  surfaceElement: HTMLElement,
  target: EventTarget | null
): RowAnchor | null => {
  let element: Element | null = null;
  if (target instanceof Element) {
    element = target;
  } else if (target instanceof Node) {
    element = target.parentElement;
  }
  if (!element) {
    return null;
  }

  const candidate = element.closest(BLOCK_SELECTOR);
  if (!(candidate instanceof HTMLElement)) {
    return null;
  }
  const coords = candidate.getBoundingClientRect();
  const midpointX = coords.left + coords.width / 2;
  const midpointY = coords.top + Math.min(6, coords.height / 2);
  return resolveRowAnchorFromPoint(editor, surfaceElement, midpointX, midpointY);
};

const resolveRowAnchorFromPoint = (
  editor: Editor,
  surfaceElement: HTMLElement,
  clientX: number,
  clientY: number
): RowAnchor | null => {
  const view = getSafeEditorView(editor);
  if (!view) {
    return null;
  }

  const positionByCoords = getPosAtCoordsSafe(view, clientX, clientY);
  if (positionByCoords?.pos != null) {
    const directHit = resolveRowAnchorFromPos(editor, surfaceElement, positionByCoords.pos);
    if (directHit) {
      return directHit;
    }
  }

  const surfaceRect = surfaceElement.getBoundingClientRect();
  const surfaceScrollTop = surfaceElement.scrollTop;
  let closest: { distance: number; row: RowAnchor } | null = null;
  let runningPos = 0;

  for (let index = 0; index < editor.state.doc.childCount; index += 1) {
    const node = editor.state.doc.child(index);
    const rowDom = getTopLevelRowDom(view, index, runningPos);
    if (rowDom instanceof HTMLElement) {
      const rowRect = rowDom.getBoundingClientRect();
      const distance =
        clientY < rowRect.top
          ? rowRect.top - clientY
          : clientY > rowRect.bottom
            ? clientY - rowRect.bottom
            : 0;

      const row: RowAnchor = {
        pos: runningPos,
        nodeSize: node.nodeSize,
        top: rowRect.top - surfaceRect.top + surfaceScrollTop,
        height: rowRect.height,
        lineHeight: Number.parseFloat(window.getComputedStyle(rowDom).lineHeight) || 24,
      };

      if (distance === 0) {
        return row;
      }
      if (!closest || distance < closest.distance) {
        closest = { distance, row };
      }
    }
    runningPos += node.nodeSize;
  }

  return closest?.row ?? null;
};

const resolveRowAnchorFromPos = (
  editor: Editor,
  surfaceElement: HTMLElement,
  pos: number
): RowAnchor | null => {
  const view = getSafeEditorView(editor);
  if (!view) {
    return null;
  }

  const domPos = clamp(pos, 0, Math.max(0, editor.state.doc.content.size));

  const topLevel = getTopLevelBlockAtPos(editor.state.doc, domPos);
  if (!topLevel) {
    return null;
  }

  const rowDom = getTopLevelRowDom(view, topLevel.index, topLevel.pos);
  if (!(rowDom instanceof HTMLElement)) {
    return null;
  }

  const rowRect = rowDom.getBoundingClientRect();
  const surfaceRect = surfaceElement.getBoundingClientRect();
  const surfaceScrollTop = surfaceElement.scrollTop;

  return {
    pos: topLevel.pos,
    nodeSize: topLevel.node.nodeSize,
    top: rowRect.top - surfaceRect.top + surfaceScrollTop,
    height: rowRect.height,
    lineHeight: Number.parseFloat(window.getComputedStyle(rowDom).lineHeight) || 24,
  };
};

const resolveSelectionRowAnchor = (
  editor: Editor,
  surfaceElement: HTMLElement
): RowAnchor | null => {
  const view = getSafeEditorView(editor);
  if (!view) {
    return null;
  }

  const { state } = editor;
  if (state.doc.childCount === 0) {
    return {
      pos: 0,
      nodeSize: 0,
      top: 0,
      height: 24,
      lineHeight: 24,
    };
  }

  const selectionIndex = clamp(state.selection.$from.index(0), 0, state.doc.childCount - 1);
  const selectionPos = getTopLevelPositionByIndex(state.doc, selectionIndex);
  const rowFromSelectionIndex = resolveRowAnchorFromPos(editor, surfaceElement, selectionPos);
  if (rowFromSelectionIndex) {
    return rowFromSelectionIndex;
  }

  const coordsAtPos = view.coordsAtPos as
    | ((position: number) => { left: number; right: number; top: number; bottom: number })
    | undefined;
  if (coordsAtPos) {
    try {
      const caret = coordsAtPos(state.selection.from);
      const caretX = Number.isFinite(caret.left) ? caret.left : caret.right;
      const caretY = (caret.top + caret.bottom) / 2;
      const rowByPoint = resolveRowAnchorFromPoint(editor, surfaceElement, caretX, caretY);
      if (rowByPoint) {
        return rowByPoint;
      }
    } catch {
      // Keep falling back through additional strategies.
    }
  }

  const domAtPos = view.domAtPos as ((position: number) => { node: Node; offset: number }) | undefined;
  if (domAtPos) {
    try {
      const { node } = domAtPos(state.selection.from);
      const target = node instanceof Element ? node : node.parentElement;
      const rowByTarget = resolveRowAnchorFromTarget(editor, surfaceElement, target);
      if (rowByTarget) {
        return rowByTarget;
      }
    } catch {
      // Continue with final fallback.
    }
  }

  return resolveRowAnchorFromPos(editor, surfaceElement, 0);
};

export function DocEditor({
  doc: ydoc,
  provider,
  currentUser,
  placeholder = 'Write here, or press / for commands',
  readOnly = false,
  className,
}: DocEditorProps) {
  const shellRef = useRef<HTMLDivElement | null>(null);
  const editorSurfaceRef = useRef<HTMLDivElement | null>(null);
  const commandMenuRef = useRef<HTMLDivElement | null>(null);
  const commandSearchInputRef = useRef<HTMLInputElement | null>(null);
  const draggingRowRef = useRef<RowAnchor | null>(null);

  const [commandMenu, setCommandMenu] = useState<CommandMenuState | null>(null);
  const [activeRow, setActiveRow] = useState<RowAnchor | null>(null);
  const [hoveredRow, setHoveredRow] = useState<RowAnchor | null>(null);
  const [draggingRow, setDraggingRow] = useState<RowAnchor | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);

  // A person's color comes from who they are, the same on every record, not from the order they arrived in.
  const resolveCursorColor = useCallback(
    (user: { id?: unknown; name?: unknown } | null | undefined) => peerColor(resolvePresenceKey(user)),
    []
  );

  const resolvedCurrentUserColor = useMemo(
    () =>
      resolveCursorColor({
        id: currentUser.id,
        name: currentUser.name,
      }),
    [currentUser.id, currentUser.name, resolveCursorColor]
  );

  const editor = useEditor(
    {
      immediatelyRender: false,
      editable: !readOnly,
      extensions: [
        StarterKit.configure({ history: false }),
        Placeholder.configure({ placeholder }),
        Collaboration.configure({ document: ydoc }),
        ...(provider
          ? [
              CollaborationCursor.configure({
                provider,
                user: {
                  id: currentUser.id,
                  name: currentUser.name,
                  color: resolvedCurrentUserColor,
                },
                render: (incomingUser) => {
                  const color = resolveCursorColor(
                    incomingUser as { id?: unknown; name?: unknown } | null | undefined
                  );
                  const name =
                    incomingUser && typeof incomingUser.name === 'string'
                      ? incomingUser.name
                      : 'User';

                  const cursor = document.createElement('span');
                  cursor.classList.add('collaboration-cursor__caret');
                  cursor.style.borderColor = color;

                  const label = document.createElement('span');
                  label.classList.add('collaboration-cursor__label');
                  label.style.backgroundColor = color;
                  label.textContent = name;

                  cursor.appendChild(label);
                  return cursor;
                },
                selectionRender: (incomingUser) => {
                  const color = resolveCursorColor(
                    incomingUser as { id?: unknown; name?: unknown } | null | undefined
                  );
                  const name =
                    incomingUser && typeof incomingUser.name === 'string'
                      ? incomingUser.name
                      : 'User';

                  return {
                    nodeName: 'span',
                    class: 'collaboration-cursor__selection',
                    style: [
                      `background-color: ${hexToRgba(color, 0.2)}`,
                      `box-shadow: inset 0 0 0 1px ${hexToRgba(color, 0.38)}`,
                    ].join('; '),
                    'data-user': name,
                  };
                },
              }),
            ]
          : []),
      ],
    },
    [
      provider,
      ydoc,
      placeholder,
      readOnly,
      currentUser.id,
      currentUser.name,
      resolvedCurrentUserColor,
      resolveCursorColor,
    ]
  );

  useEffect(() => {
    if (!editor) {
      return;
    }
    editor.setEditable(!readOnly);
  }, [editor, readOnly]);

  useEffect(() => {
    if (!editor || !shellRef.current || readOnly) {
      return;
    }

    const updateSlashMenu = () => {
      const shellRect = shellRef.current?.getBoundingClientRect();
      if (!shellRect) {
        return;
      }

      const { from, empty, $from } = editor.state.selection;
      if (!empty || !$from.parent.isTextblock) {
        setCommandMenu((previous) => (previous?.mode === 'slash' ? null : previous));
        return;
      }

      const textBeforeCursor = $from.parent.textContent.slice(0, $from.parentOffset);
      const match = /(^|\s)\/([a-zA-Z0-9-]*)$/.exec(textBeforeCursor);
      if (!match) {
        setCommandMenu((previous) => (previous?.mode === 'slash' ? null : previous));
        return;
      }

      const query = match[2] ?? '';
      const slashPos = from - query.length - 1;
      if (slashPos < 1) {
        setCommandMenu((previous) => (previous?.mode === 'slash' ? null : previous));
        return;
      }

      const caretCoords = editor.view.coordsAtPos(from);
      const caretBottomWithinShell = caretCoords.bottom - shellRect.top;
      const preferAbove = caretBottomWithinShell > shellRect.height * 0.62;
      const anchored = clampMenuPosition(
        shellRect,
        caretCoords.left - shellRect.left,
        caretBottomWithinShell + COMMAND_MENU_GAP,
        COMMAND_MENU_ESTIMATED_HEIGHT,
        preferAbove
      );

      setCommandMenu((previous) => {
        if (previous?.mode === 'row') {
          return previous;
        }
        return {
          mode: 'slash',
          x: anchored.x,
          y: anchored.y,
          range: {
            from: slashPos,
            to: from,
          },
          query,
        };
      });
    };

    updateSlashMenu();
    editor.on('update', updateSlashMenu);
    editor.on('selectionUpdate', updateSlashMenu);

    return () => {
      editor.off('update', updateSlashMenu);
      editor.off('selectionUpdate', updateSlashMenu);
    };
  }, [editor, readOnly]);

  useEffect(() => {
    if (!editor || !editorSurfaceRef.current) {
      return;
    }

    const updateActiveRowFromSelection = () => {
      if (!editorSurfaceRef.current) {
        return;
      }
      const row = resolveSelectionRowAnchor(editor, editorSurfaceRef.current);
      if (row) {
        setActiveRow(row);
      }
    };

    updateActiveRowFromSelection();
    editor.on('selectionUpdate', updateActiveRowFromSelection);
    editor.on('focus', updateActiveRowFromSelection);
    editor.on('update', updateActiveRowFromSelection);

    const editorDom = editor.view.dom;
    const scheduleSync = () => {
      window.requestAnimationFrame(updateActiveRowFromSelection);
    };
    editorDom.addEventListener('mouseup', scheduleSync);
    editorDom.addEventListener('keyup', scheduleSync);
    editorDom.addEventListener('input', scheduleSync);

    return () => {
      editor.off('selectionUpdate', updateActiveRowFromSelection);
      editor.off('focus', updateActiveRowFromSelection);
      editor.off('update', updateActiveRowFromSelection);
      editorDom.removeEventListener('mouseup', scheduleSync);
      editorDom.removeEventListener('keyup', scheduleSync);
      editorDom.removeEventListener('input', scheduleSync);
    };
  }, [editor]);

  useEffect(() => {
    if (commandMenu?.mode !== 'row') {
      return;
    }
    const id = window.requestAnimationFrame(() => {
      commandSearchInputRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(id);
    };
  }, [commandMenu]);

  useEffect(() => {
    if (!commandMenu || !commandMenuRef.current || !shellRef.current) {
      return;
    }

    const id = window.requestAnimationFrame(() => {
      if (!commandMenuRef.current || !shellRef.current) {
        return;
      }

      const shellRect = shellRef.current.getBoundingClientRect();
      const menuRect = commandMenuRef.current.getBoundingClientRect();
      const maxX = Math.max(
        COMMAND_MENU_MARGIN,
        shellRect.width - menuRect.width - COMMAND_MENU_MARGIN
      );
      const maxY = Math.max(
        COMMAND_MENU_MARGIN,
        shellRect.height - menuRect.height - COMMAND_MENU_MARGIN
      );

      const nextX = clamp(commandMenu.x, COMMAND_MENU_MARGIN, maxX);
      const nextY = clamp(commandMenu.y, COMMAND_MENU_MARGIN, maxY);

      if (Math.abs(nextX - commandMenu.x) > 0.5 || Math.abs(nextY - commandMenu.y) > 0.5) {
        setCommandMenu((previous) =>
          previous
            ? {
                ...previous,
                x: nextX,
                y: nextY,
              }
            : previous
        );
      }
    });

    return () => {
      window.cancelAnimationFrame(id);
    };
  }, [commandMenu]);

  const normalizedQuery = useMemo(() => {
    const raw = commandMenu?.query ?? '';
    return raw.replace(/^\//, '').trim().toLowerCase();
  }, [commandMenu?.query]);

  const filteredCommandItems = useMemo(() => {
    if (!normalizedQuery) {
      return COMMAND_ITEMS;
    }
    return COMMAND_ITEMS.filter((item) => {
      const haystacks = [item.label, item.markdown, ...item.keywords]
        .join(' ')
        .toLowerCase();
      return haystacks.includes(normalizedQuery);
    });
  }, [normalizedQuery]);

  const insertBlockAroundRow = useCallback(
    (command: CommandKind, rowPos: number, insertMode: InsertMode) => {
      if (!editor) {
        return;
      }
      const { state, view } = editor;
      const row = getTopLevelBlockAtPos(state.doc, rowPos);
      const payload = buildNodesForCommand(state.schema, command);
      if (!payload) {
        return;
      }

      const documentEnd = state.doc.content.size;
      const insertPos = row
        ? insertMode === 'above'
          ? row.pos
          : row.pos + row.node.nodeSize
        : documentEnd;

      let transaction = state.tr.insert(insertPos, Fragment.fromArray(payload.nodes));
      const selectionPos = clamp(insertPos + payload.selectionOffset, 1, transaction.doc.content.size);
      transaction = transaction.setSelection(
        TextSelection.near(transaction.doc.resolve(selectionPos), 1)
      );
      view.dispatch(transaction.scrollIntoView());
    },
    [editor]
  );

  const moveTopLevelRow = useCallback(
    (sourcePos: number, targetInsertPos: number) => {
      if (!editor) {
        return;
      }

      const { state, view } = editor;
      const sourceRow = getTopLevelBlockAtPos(state.doc, sourcePos);
      if (!sourceRow) {
        return;
      }

      const from = sourceRow.pos;
      const to = sourceRow.pos + sourceRow.node.nodeSize;
      if (targetInsertPos >= from && targetInsertPos <= to) {
        return;
      }

      const slice = state.doc.slice(from, to);
      let transaction = state.tr.delete(from, to);

      let adjustedInsertPos =
        targetInsertPos > from ? targetInsertPos - sourceRow.node.nodeSize : targetInsertPos;
      adjustedInsertPos = clamp(adjustedInsertPos, 0, transaction.doc.content.size);

      transaction = transaction.insert(adjustedInsertPos, slice.content);
      const selectionPos = clamp(adjustedInsertPos + 1, 1, transaction.doc.content.size);
      transaction = transaction.setSelection(
        TextSelection.near(transaction.doc.resolve(selectionPos), 1)
      );
      view.dispatch(transaction.scrollIntoView());
    },
    [editor]
  );

  const getCurrentSelectionRow = useCallback((): RowAnchor | null => {
    if (!editor || !editorSurfaceRef.current) {
      return null;
    }
    return resolveSelectionRowAnchor(editor, editorSurfaceRef.current);
  }, [editor]);

  const executeMenuCommand = useCallback(
    (command: CommandKind) => {
      if (!editor || !commandMenu) {
        return;
      }

      if (commandMenu.mode === 'slash') {
        executeSlashCommand(editor, command, commandMenu.range);
      } else {
        insertBlockAroundRow(command, commandMenu.rowPos, commandMenu.insertMode);
      }

      setCommandMenu(null);
      editor.commands.focus();
    },
    [commandMenu, editor, insertBlockAroundRow]
  );

  useEffect(() => {
    if (!commandMenu) {
      return;
    }

    const handleMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (commandMenuRef.current?.contains(target)) {
        return;
      }
      setCommandMenu(null);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setCommandMenu(null);
        return;
      }
      if (event.key === 'Enter' && filteredCommandItems.length > 0) {
        event.preventDefault();
        executeMenuCommand(filteredCommandItems[0].kind);
      }
    };

    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [commandMenu, executeMenuCommand, filteredCommandItems]);

  const openRowCommandMenu = useCallback(
    (row: RowAnchor, insertMode: InsertMode) => {
      const shellRect = shellRef.current?.getBoundingClientRect();
      const surfaceElement = editorSurfaceRef.current;
      const surfaceRect = surfaceElement?.getBoundingClientRect();
      if (!shellRect || !surfaceRect || !surfaceElement) {
        return;
      }

      const anchorX = surfaceRect.left - shellRect.left + 2;
      const visibleRowTop = row.top - surfaceElement.scrollTop;
      const anchorY = surfaceRect.top - shellRect.top + visibleRowTop + row.height + COMMAND_MENU_GAP;
      const preferAbove = visibleRowTop > surfaceElement.clientHeight * 0.58;
      const anchored = clampMenuPosition(
        shellRect,
        anchorX,
        anchorY,
        COMMAND_MENU_ESTIMATED_HEIGHT,
        preferAbove
      );

      setCommandMenu({
        mode: 'row',
        x: anchored.x,
        y: anchored.y,
        rowPos: row.pos,
        insertMode,
        query: '',
      });
    },
    []
  );

  const handleEditorMouseMove = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!editor || !editorSurfaceRef.current || readOnly || draggingRow) {
      return;
    }
    const surfaceRect = editorSurfaceRef.current.getBoundingClientRect();
    const sampleX = clamp(surfaceRect.left + 72, surfaceRect.left + 24, surfaceRect.right - 24);

    const rowByTarget = resolveRowAnchorFromTarget(editor, editorSurfaceRef.current, event.target);
    const row =
      rowByTarget ??
      resolveRowAnchorFromPoint(
        editor,
        editorSurfaceRef.current,
        sampleX,
        event.clientY
      );
    setHoveredRow(row ?? null);
    if (row) {
      setActiveRow(row);
    }
  };

  const handleEditorMouseLeave = () => {
    if (draggingRow) {
      return;
    }
    setHoveredRow(null);
  };

  const handleEditorMouseUp = () => {
    window.requestAnimationFrame(() => {
      setHoveredRow(null);
      const row = getCurrentSelectionRow();
      if (row) {
        setActiveRow(row);
      }
    });
  };

  const handleEditorKeyUp = () => {
    window.requestAnimationFrame(() => {
      setHoveredRow(null);
      const row = getCurrentSelectionRow();
      if (row) {
        setActiveRow(row);
      }
    });
  };

  const handleEditorScroll = () => {
    window.requestAnimationFrame(() => {
      setHoveredRow(null);
      const row = getCurrentSelectionRow();
      if (row) {
        setActiveRow(row);
      }
    });
  };

  const handleRowDragStart = (event: ReactDragEvent<HTMLButtonElement>, sourceRow: RowAnchor) => {
    if (readOnly) {
      return;
    }
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/x-doc-editor-row', String(sourceRow.pos));
    event.dataTransfer.setData('text/plain', '');
    draggingRowRef.current = sourceRow;
    setDraggingRow(sourceRow);
    setActiveRow(sourceRow);
    setDropTarget({
      insertPos: sourceRow.pos,
      top: sourceRow.top,
    });
    setCommandMenu(null);
  };

  const handleEditorDragOver = (event: ReactDragEvent<HTMLDivElement>) => {
    const activeDraggingRow = draggingRowRef.current ?? draggingRow;
    if (!editor || !editorSurfaceRef.current || !activeDraggingRow || readOnly) {
      return;
    }
    const view = getSafeEditorView(editor);
    if (!view) {
      return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';

    const surfaceRect = editorSurfaceRef.current.getBoundingClientRect();
    const surfaceScrollTop = editorSurfaceRef.current.scrollTop;
    const rowByTarget = resolveRowAnchorFromTarget(editor, editorSurfaceRef.current, event.target);
    const row =
      rowByTarget ??
      resolveRowAnchorFromPoint(
        editor,
        editorSurfaceRef.current,
        event.clientX,
        event.clientY
      );

    if (row) {
      const rowMidpoint = surfaceRect.top + (row.top - surfaceScrollTop) + row.height / 2;
      const insertBefore = event.clientY < rowMidpoint;
      setDropTarget({
        insertPos: insertBefore ? row.pos : row.pos + row.nodeSize,
        top: insertBefore ? row.top : row.top + row.height,
      });
      return;
    }

    const document = editor.state.doc;
    if (document.childCount === 0) {
      setDropTarget({ insertPos: 0, top: 0 });
      return;
    }

    const firstPos = getTopLevelPositionByIndex(document, 0);
    const lastIndex = document.childCount - 1;
    const lastPos = getTopLevelPositionByIndex(document, lastIndex);
    const lastNode = document.child(lastIndex);
    const firstDom = getTopLevelRowDom(view, 0, firstPos);
    const lastDom = getTopLevelRowDom(view, lastIndex, lastPos);

    if (firstDom instanceof HTMLElement && event.clientY < firstDom.getBoundingClientRect().top) {
      const rect = firstDom.getBoundingClientRect();
      setDropTarget({
        insertPos: firstPos,
        top: rect.top - surfaceRect.top + surfaceScrollTop,
      });
      return;
    }

    if (lastDom instanceof HTMLElement) {
      const rect = lastDom.getBoundingClientRect();
      setDropTarget({
        insertPos: lastPos + lastNode.nodeSize,
        top: rect.bottom - surfaceRect.top + surfaceScrollTop,
      });
    }
  };

  const handleEditorDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    const activeDraggingRow = draggingRowRef.current ?? draggingRow;
    if (!activeDraggingRow || readOnly) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (dropTarget) {
      moveTopLevelRow(activeDraggingRow.pos, dropTarget.insertPos);
    }
    draggingRowRef.current = null;
    setDraggingRow(null);
    setDropTarget(null);
    setHoveredRow(null);
  };

  const handleEditorDropCapture = (event: ReactDragEvent<HTMLDivElement>) => {
    if (!draggingRowRef.current || readOnly) {
      return;
    }
    event.preventDefault();
  };

  const handleEditorDragOverCapture = (event: ReactDragEvent<HTMLDivElement>) => {
    if (!draggingRowRef.current || readOnly) {
      return;
    }
    event.preventDefault();
  };

  const handleRowDragEnd = () => {
    draggingRowRef.current = null;
    setDraggingRow(null);
    setDropTarget(null);
  };

  if (!editor) {
    return (
      <div className={`${styles.shell} ${styles.shellLoading} ${className ?? ''}`}>
        <div className={styles.loading}>Opening this record…</div>
      </div>
    );
  }

  const liveSelectionRow = getCurrentSelectionRow();
  const fallbackFirstRow =
    !draggingRow &&
    !hoveredRow &&
    !liveSelectionRow &&
    !activeRow &&
    editorSurfaceRef.current
      ? resolveRowAnchorFromPos(editor, editorSurfaceRef.current, 0)
      : null;
  const controlRow = draggingRow ?? hoveredRow ?? liveSelectionRow ?? activeRow ?? fallbackFirstRow;
  const controlTop = controlRow
    ? controlRow.top + Math.max(0, Math.round((controlRow.lineHeight - 20) / 2))
    : 0;

  return (
    <div ref={shellRef} className={`${styles.shell} ${className ?? ''}`}>
      <div className={styles.layout}>
        <main className={styles.main}>
          <div
            ref={editorSurfaceRef}
            className={styles.editorSurface}
            onMouseMove={handleEditorMouseMove}
            onMouseLeave={handleEditorMouseLeave}
            onMouseUp={handleEditorMouseUp}
            onKeyUp={handleEditorKeyUp}
            onScroll={handleEditorScroll}
            onDragOverCapture={handleEditorDragOverCapture}
            onDropCapture={handleEditorDropCapture}
            onDragOver={handleEditorDragOver}
            onDrop={handleEditorDrop}
          >
            {!readOnly && controlRow ? (
              <div
                className={styles.rowControls}
                style={{ top: controlTop }}
              >
                <button
                  type="button"
                  className={styles.rowAddButton}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={(event) => {
                    event.preventDefault();
                    openRowCommandMenu(controlRow, event.altKey ? 'above' : 'below');
                  }}
                  aria-label="Insert block"
                >
                  <Plus size={12} strokeWidth={2.6} />
                </button>
                <button
                  type="button"
                  className={styles.rowDragButton}
                  draggable
                  onDragStart={(event) => handleRowDragStart(event, controlRow)}
                  onDragEnd={handleRowDragEnd}
                  aria-label="Drag to reorder row"
                >
                  <GripVertical size={13} strokeWidth={2.2} />
                </button>
              </div>
            ) : null}

            {!readOnly && draggingRow && dropTarget ? (
              <div className={styles.dropIndicator} style={{ top: dropTarget.top }} />
            ) : null}

            <EditorContent editor={editor} />
          </div>
        </main>
      </div>

      {commandMenu ? (
        <div
          ref={commandMenuRef}
          className={styles.commandMenu}
          style={{ left: commandMenu.x, top: commandMenu.y }}
        >
          <div className={styles.commandMenuSearchRow}>
            <input
              ref={commandSearchInputRef}
              className={styles.commandMenuSearch}
              value={
                commandMenu.mode === 'slash'
                  ? `/${commandMenu.query}`
                  : commandMenu.query
              }
              readOnly={commandMenu.mode === 'slash'}
              onChange={(event) => {
                if (commandMenu.mode !== 'row') {
                  return;
                }
                setCommandMenu({
                  ...commandMenu,
                  query: event.target.value,
                });
              }}
              placeholder="/Type to search"
            />
          </div>

          <div className={styles.commandMenuSectionTitle}>Basic blocks</div>

          <div className={styles.commandMenuList}>
            {filteredCommandItems.map((item) => (
              <button
                key={item.kind}
                type="button"
                className={styles.commandMenuItem}
                onClick={() => executeMenuCommand(item.kind)}
              >
                <span>{item.label}</span>
                <span>{item.markdown}</span>
              </button>
            ))}
            {filteredCommandItems.length === 0 ? (
              <div className={styles.commandMenuEmpty}>No matching blocks</div>
            ) : null}
          </div>

          <button
            type="button"
            className={styles.commandMenuClose}
            onClick={() => setCommandMenu(null)}
          >
            <span>Close menu</span>
            <span>esc</span>
          </button>
        </div>
      ) : null}

    </div>
  );
}
