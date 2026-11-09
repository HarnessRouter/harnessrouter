// A record's text and its live document, one way and the other. Server only. Markdown is what a record keeps and an
// agent writes; a Y.Doc is what people edit together. The body is the fragment the editor binds to, under the same
// schema the editor uses, so what this builds is what the editor reads. The title is plain text beside it.
import { getSchema } from '@tiptap/core';
import { generateHTML, generateJSON } from '@tiptap/html';
import { Node as PmNode } from '@tiptap/pm/model';
import StarterKit from '@tiptap/starter-kit';
import { marked } from 'marked';
import TurndownService from 'turndown';
import { updateYFragment, yXmlFragmentToProsemirrorJSON } from 'y-prosemirror';
import * as Y from 'yjs';

const EXTENSIONS = [StarterKit];
const SCHEMA = getSchema(EXTENSIONS);
export const BODY = 'default';
export const TITLE = 'title';

const turndown = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-', emDelimiter: '*', strongDelimiter: '**', hr: '---' });
turndown.addRule('fencedWithLanguage', {
  filter: (node) => node.nodeName === 'PRE' && node.firstChild?.nodeName === 'CODE',
  replacement: (_c, node) => {
    const code = node.firstChild as unknown as { getAttribute(a: string): string | null; textContent: string };
    const lang = /language-(\S+)/.exec(code.getAttribute('class') || '')?.[1] || '';
    return `\n\n\`\`\`${lang}\n${code.textContent.replace(/\n$/, '')}\n\`\`\`\n\n`;
  },
});

const toPm = (md: string) => generateJSON(marked.parse(md || '', { async: false, gfm: true, breaks: false }) as string || '<p></p>', EXTENSIONS);
const toMd = (json: Parameters<typeof generateHTML>[0]) => turndown.turndown(generateHTML(json, EXTENSIONS) || '').replace(/\n{3,}/g, '\n\n').replace(/[ \t]+\n/g, '\n').trim();

/** Text as the editor would give it back, so that comparing two texts compares what they say. */
export const normal = (md: string): string => toMd(toPm(md));

export const readBody = (doc: Y.Doc): string => toMd(yXmlFragmentToProsemirrorJSON(doc.getXmlFragment(BODY)) as Parameters<typeof generateHTML>[0]);
export const readTitle = (doc: Y.Doc): string => doc.getText(TITLE).toString();

export interface Touched { text: Y.XmlText | null }

/** Turn the body into this text by changing only what differs, so a person typing elsewhere isn't disturbed and
 *  what changed reads as a peer's edit. Says where the first change landed. */
export function writeBody(doc: Y.Doc, md: string, origin: unknown): Touched {
  const frag = doc.getXmlFragment(BODY);
  const before = frag.toArray().map((x) => x.toString());
  const pm = PmNode.fromJSON(SCHEMA, toPm(md));
  doc.transact(() => updateYFragment(doc, frag, pm, { mapping: new Map(), isOMark: new Map() }), origin);
  const after = frag.toArray();
  const at = after.findIndex((x, i) => x.toString() !== before[i]);
  return { text: at < 0 ? null : lastText(after[at]) };
}

function lastText(node: unknown): Y.XmlText | null {
  if (node instanceof Y.XmlText) return node;
  if (node instanceof Y.XmlElement || node instanceof Y.XmlFragment) {
    const kids = node.toArray();
    for (let i = kids.length - 1; i >= 0; i -= 1) {
      const t = lastText(kids[i]);
      if (t) return t;
    }
  }
  return null;
}

export function writeTitle(doc: Y.Doc, next: string, origin: unknown): void {
  const t = doc.getText(TITLE);
  const cur = t.toString();
  if (cur === next) return;
  let s = 0;
  while (s < cur.length && s < next.length && cur[s] === next[s]) s += 1;
  let e = 0;
  while (e < cur.length - s && e < next.length - s && cur[cur.length - 1 - e] === next[next.length - 1 - e]) e += 1;
  doc.transact(() => {
    if (cur.length - s - e) t.delete(s, cur.length - s - e);
    if (next.length - s - e) t.insert(s, next.slice(s, next.length - e));
  }, origin);
}
