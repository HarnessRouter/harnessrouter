'use client';
// The files a conversation made: compact cards under the answer that made them (name, kind, Copy,
// Download; the card opens it; under two or more, Download all as one zip), and the preview beside
// the conversation that opens them, never their whole content printed into the chat (Richard,
// 2026-10-18: "like the original artifact view, the preview opens on the right"). Reads carry the
// sign-in (a bare src would be refused), so the preview fetches through harnessFetch, and
// spreadsheets parse with the console's own xlsx.
import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import { ArtifactPanel, FileCard } from 'reifyui/agent-chat';
import { authHeaders, containerFileUrl, downloadFile, fetchFileBlob, type RespFile } from '@/lib/chat';
import { harnessFetch } from '@/lib/hfetch';
import { isInternalOutput, type Msg } from '@/lib/conversation';
import { toast } from '../toast';

export type OpenFile = { key: string; name: string; url: string; path?: string; size?: number; turn?: number };

const TEXT = /\.(md|markdown|txt|json|csv|tsv|log|ya?ml|xml|html?|css|jsx?|tsx?|py|sh|sql|toml|ini|env)$/i;
const IMAGE = /\.(png|jpe?g|gif|webp|avif|bmp)$/i;
const THUMB_MAX = 8 * 1024 * 1024;   // a picture bigger than this shows its kind's icon instead

/** An image file's own picture, read with the sign-in into an object url (revoked when it goes). */
function useThumb(url: string, name: string): string | undefined {
  const [src, setSrc] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (!IMAGE.test(name)) return undefined;
    let alive = true, obj = '';
    fetchFileBlob(url).then((b) => { if (alive && b.size <= THUMB_MAX) { obj = URL.createObjectURL(b); setSrc(obj); } }).catch(() => { /* the icon stays */ });
    return () => { alive = false; if (obj) URL.revokeObjectURL(obj); };
  }, [url, name]);
  return src;
}

function Card({ f, active, onOpen }: { f: RespFile; active: boolean; onOpen: (key: string) => void }) {
  const url = containerFileUrl(f), name = base(f.filename), k = fileKey(f);
  const thumb = useThumb(url, name);
  return (
    <FileCard name={name} origin="" active={active} thumb={thumb}
      onPreview={() => onOpen(k)}
      onDownload={() => { downloadFile(url, name).catch(() => toast('The file could not be downloaded. Try again.')); }}
      onCopy={TEXT.test(name) ? async () => { const b = await fetchFileBlob(url); await navigator.clipboard.writeText(await b.text()); } : undefined} />
  );
}
const base = (n: string) => n.split('/').pop() || n;
export const fileKey = (f: RespFile) => f.file_id || f.filename;

/** Every file the conversation made, oldest first, once each: its path (folders in the preview's
 *  list), its size when the record says, and the turn that made it. */
export function filesOf(msgs: Msg[]): OpenFile[] {
  const seen = new Set<string>();
  const out: OpenFile[] = [];
  let turn = 0;
  for (const m of msgs) {
    if (m.role !== 'assistant') continue;
    turn += 1;
    if (m.status === 'running') continue;
    for (const f of m.files || []) {
      if (isInternalOutput(f.filename)) continue;
      const k = fileKey(f);
      if (seen.has(k)) continue;
      seen.add(k);
      const bytes = (f as RespFile & { bytes?: number }).bytes;
      out.push({ key: k, name: base(f.filename), url: containerFileUrl(f), path: f.filename, turn,
        ...(typeof bytes === 'number' ? { size: bytes } : {}) });
    }
  }
  return out;
}

/** One answer's files, as cards, and under them "Download all" when there are two or more. */
export function FileCards({ files, active, onOpen, zipName }: {
  files: RespFile[]; active?: string | null; onOpen: (key: string) => void;
  /** what the zip of this answer's files is named after: the task's title, else the setup's name */
  zipName?: string;
}) {
  const shown = files.filter((f) => !isInternalOutput(f.filename));
  if (!shown.length) return null;
  const zip = archiveOf(shown);
  return (
    <>
      <div className="pg-files">
        {shown.map((f) => <Card key={fileKey(f)} f={f} active={active === fileKey(f)} onOpen={onOpen} />)}
      </div>
      {zip ? <ZipAll url={zip.url} count={zip.count} name={zipFileName(zipName)} /> : null}
    </>
  );
}

// The server builds the zip before its first byte answers: a large one takes longer than the
// proxy helper's usual 30 s wait for an answer, so the zip read carries its own, longer bound.
const ZIP_WAIT_MS = 10 * 60 * 1000;
// the gateway takes at most this many ids in one archive (it reads only the first 200)
const ZIP_MAX_FILES = 200;

/** One answer's files as one zip: the task's own archive of exactly these file ids (the gateway's
 *  GET /v1/sessions/{sid}/files/archive?files=…, folders kept inside), read through the console's
 *  harness proxy with the sign-in, the same way a single file is. Only files the server holds have
 *  one: a recorded run's files come from /demos (they carry their own url), so none is offered
 *  there. Null below two files. */
export function archiveOf(files: RespFile[]): { url: string; count: number } | null {
  const shown = files.filter((f) => !isInternalOutput(f.filename));
  const sid = shown[0]?.container_id || '';   // a file's container id IS its task's session id
  if (!sid || shown.some((f) => f.url || !f.file_id || f.container_id !== sid)) return null;
  const ids = [...new Set(shown.map((f) => f.file_id))];
  if (ids.length < 2 || ids.length > ZIP_MAX_FILES) return null;
  return {
    url: `/api/harness/v1/sessions/${encodeURIComponent(sid)}/files/archive?files=${encodeURIComponent(ids.join(','))}`,
    count: ids.length,
  };
}

/** "<name> files.zip", the name cleaned of what file systems refuse (\ / : * ? " < > |, control
 *  characters, leading dots, trailing dots and spaces) and kept short. */
export function zipFileName(name?: string | null): string {
  const kept = Array.from(String(name || ''), (c) => (c.charCodeAt(0) < 32 || c === '\u007f' || '\\/:*?"<>|'.includes(c) ? ' ' : c)).join('');
  const short = Array.from(kept.replace(/\s+/g, ' ').trim()).slice(0, 80).join('');
  const clean = short.replace(/^[.\s]+/, '').replace(/[.\s]+$/, '');
  return `${clean || 'Task'} files.zip`;
}

/** The server's own sentence, in the console's plain words: a clause it set off with a dash becomes
 *  its own sentence ("too large for one archive — download files individually" reads "Too large for
 *  one archive. Download files individually."). */
export function plainSentence(s: string): string {
  const parts = String(s || '').split(/\s+[—–-]+\s+|\s*[—–]\s*/).map((p) => p.trim().replace(/[.\s]+$/, '')).filter(Boolean);
  return parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('. ') + (parts.length ? '.' : '');
}

const TOO_LARGE = 'These files are too large for one zip. Download them one at a time.';
const NOT_ZIPPED = 'The files could not be downloaded as one zip. Try again, or download them one at a time.';

/** The toast's sentence for a refused zip: the server's own for one too large, else plain words. */
async function zipRefusal(r: Response): Promise<string> {
  if (r.status !== 413) return NOT_ZIPPED;
  let why = '';
  try { why = String(((await r.json()) || {}).detail || ''); } catch { /* no body */ }
  return plainSentence(why) || TOO_LARGE;
}

/** Fetch the zip with the sign-in, then save it. What it throws is the toast's sentence. */
async function downloadZip(url: string, name: string): Promise<void> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ZIP_WAIT_MS);
  let blob: Blob;
  try {
    const r = await harnessFetch(url, { headers: authHeaders(), signal: ctl.signal }).catch(() => null);
    if (!r) throw new Error(NOT_ZIPPED);
    if (!r.ok) throw new Error(await zipRefusal(r));
    blob = await r.blob().catch(() => { throw new Error(NOT_ZIPPED); });
  } finally {
    clearTimeout(timer);
  }
  const obj = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = obj;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(obj), 4000);
}

const DL = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></svg>;

/** The quiet action under an answer's cards: every one of its files in one zip. While the server
 *  prepares it the action says so; a refusal is a toast in plain words, and each card's own
 *  download keeps working. */
function ZipAll({ url, count, name }: { url: string; count: number; name: string }) {
  const [busy, setBusy] = useState(false);
  const go = () => {
    if (busy) return;
    setBusy(true);
    downloadZip(url, name)
      .catch((e: unknown) => toast(e instanceof Error ? e.message : NOT_ZIPPED))
      .finally(() => setBusy(false));
  };
  return (
    <button type="button" className="btn small line pg-zipall" onClick={go}
      aria-busy={busy || undefined} aria-disabled={busy || undefined}
      aria-label={busy ? undefined : `Download all ${count} files as one zip`}>
      {busy ? <span className="pg-zipall-spin" aria-hidden="true" /> : DL}
      <span>{busy ? 'Preparing the zip…' : `Download all (${count})`}</span>
    </button>
  );
}

const md = (text: string) => <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{text}</ReactMarkdown>;
const fetchFile = (u: string) => harnessFetch(u, { headers: authHeaders() });
const pdfOf = (u: string) => u.replace(/\/content(\?|$)/, '/pdf$1');
async function parseWorkbook(buf: ArrayBuffer) {
  const XLSX = await import('xlsx');
  const wb = XLSX.read(buf, { type: 'array' });
  return wb.SheetNames.map((n) => {
    const ws = wb.Sheets[n] || {};
    const filled = Boolean(ws['!ref']);
    return { name: n, filled, rows: filled ? (XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' }) as unknown[][]) : [] };
  });
}

/** The preview: docked beside the conversation, or a drawer from the right where the page is narrow. */
export function FilesPanel({ files, active, onSelect, onClose, overlay }: {
  files: OpenFile[]; active: string | null; onSelect: (key: string) => void; onClose: () => void; overlay: boolean;
}) {
  const list = useMemo(() => files, [files]);
  if (!active || !list.some((f) => f.key === active)) return null;
  return (
    <ArtifactPanel files={list} active={active} onSelect={onSelect} onClose={onClose} overlay={overlay}
      fetchFile={fetchFile} renderMarkdown={md} officePdfUrl={pdfOf} parseWorkbook={parseWorkbook}
      onDownload={(url, name) => { downloadFile(url, name).catch(() => toast('The file could not be downloaded. Try again.')); }} />
  );
}
