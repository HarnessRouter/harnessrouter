// Right-pane preview for an output file. Renders inline for every common working file type:
// images, pdf, video, audio, Markdown, docx (mammoth), xlsx/xls/csv (SheetJS), code (Prism syntax
// highlight by extension), and Office docs with no browser renderer (pptx/ppt/odp/doc) via a
// server-side LibreOffice→PDF conversion (the /pdf sibling endpoint).
'use client';
import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PrismAsync as SyntaxHighlighter } from 'react-syntax-highlighter';
import oneLight from 'react-syntax-highlighter/dist/esm/styles/prism/one-light';
import { FileTypeIcon, extOf } from './FileTypeIcon';
import { harnessFetch } from '@/lib/hfetch';
import { authHeaders, downloadFile, fetchFileBlob } from '@/lib/chat';

const LANG: Record<string, string> = {
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
  py: 'python', rb: 'ruby', go: 'go', rs: 'rust', java: 'java', c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp',
  cs: 'csharp', php: 'php', swift: 'swift', kt: 'kotlin', scala: 'scala', sh: 'bash', bash: 'bash', zsh: 'bash',
  sql: 'sql', css: 'css', scss: 'scss', less: 'less', html: 'markup', htm: 'markup', xml: 'markup', svg: 'markup',
  json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'toml', ini: 'ini', r: 'r', jl: 'julia', lua: 'lua',
  pl: 'perl', dockerfile: 'docker', makefile: 'makefile', graphql: 'graphql', proto: 'protobuf', diff: 'diff',
};
function langOf(name: string): string { return LANG[extOf(name)] || 'text'; }

// Presentations / word docs render faithfully (colors/fonts/layout) via the server LibreOffice->PDF
// path. Spreadsheets render as a REAL interactive grid (SheetJS) with sheet tabs, a PDF of a sheet
// is the wrong mental model. CSV/TSV → a table (lossless).
const OFFICE_PDF = new Set(['pptx', 'ppt', 'pptm', 'odp', 'doc', 'docx', 'odt', 'rtf']);
const SHEET = new Set(['xls', 'xlsx', 'xlsm', 'xlsb', 'ods']);

function kindOf(name: string, mime: string): string {
  const e = extOf(name);
  if (mime.startsWith('image/') || /(png|jpe?g|gif|webp|svg|bmp|ico|avif)/.test(e)) return 'image';
  if (mime === 'application/pdf' || e === 'pdf') return 'pdf';
  if (mime.startsWith('video/') || ['mp4', 'webm', 'mov', 'm4v'].includes(e)) return 'video';
  if (mime.startsWith('audio/') || ['mp3', 'wav', 'ogg', 'm4a', 'flac'].includes(e)) return 'audio';
  if (e === 'csv' || e === 'tsv') return 'csv';
  if (e === 'md' || e === 'markdown') return 'markdown';
  if (SHEET.has(e)) return 'sheet';          // real spreadsheet grid (SheetJS), with sheet tabs
  if (OFFICE_PDF.has(e)) return 'office';     // server converts to pdf for a faithful render
  if (mime.startsWith('text/') || LANG[e] || /(txt|log|env|conf|cfg|gitignore)/.test(e)) return 'code';
  return 'binary';
}

const pdfUrlFor = (url: string) => url.replace(/\/content(\?|$)/, '/pdf$1');

export function FilePreview({ file, onClose }: { file: { url: string; name: string }; onClose: () => void }) {
  const { url, name } = file;
  const [st, setSt] = useState<{ kind: string; objUrl?: string; text?: string; html?: string; error?: string; sheets?: { name: string; html: string; filled: boolean }[] }>({ kind: 'loading' });
  const [activeSheet, setActiveSheet] = useState(0);
  useEffect(() => {
    let alive = true; let obj: string | undefined;
    setSt({ kind: 'loading' }); setActiveSheet(0);
    // Authenticated fetch (LIVE-B): a bare fetch carries no session, and the server rejects
    // headerless file reads, which used to render the error JSON as the "file content".
    harnessFetch(url, { headers: authHeaders() }).then(async (r) => {
      if (!r.ok) { if (alive) setSt({ kind: 'binary', error: 'Could not load this file.' }); return; }
      const mime = (r.headers.get('content-type') || '').toLowerCase();
      const kind = kindOf(name, mime);
      if (kind === 'office') {
        // The PDF rendition needs the same auth an <iframe src> can't carry, fetch to a blob URL.
        // Surface WHY it failed: a build without the document converter is a different problem
        // from a file that wouldn't convert, and "Could not load this file" said neither.
        try {
          const b = await fetchFileBlob(pdfUrlFor(url)); obj = URL.createObjectURL(b);
          if (alive) setSt({ kind: 'office', objUrl: obj });
        } catch (e) {
          const msg = String((e as Error)?.message || '');
          if (alive) {
            setSt({ kind: 'binary',
                    error: /501/.test(msg) ? 'Preview isn\u2019t available in this build \u2014 download to open it.'
                         : 'This file couldn\u2019t be rendered for preview.' });
          }
        }
        return;
      }
      if (kind === 'sheet') {
        try {
          const buf = await r.arrayBuffer();
          const XLSX = await import('xlsx');
          // cellStyles carries fills and column widths through; sheet_to_html already turns
          // merged ranges into colspan/rowspan.
          const wb = XLSX.read(buf, { type: 'array', cellStyles: true });
          const sheets = wb.SheetNames.map((n) => {
            const ws = wb.Sheets[n] || {};
            // sheet_to_html THROWS on a sheet with no '!ref' — i.e. an empty one — and that threw
            // away the whole workbook, not just that tab: the catch below dropped every sheet and
            // the pane rendered nothing at all. Tools routinely leave an empty default Sheet1 in
            // front of the real data, so this was most spreadsheets.
            const filled = Boolean(ws['!ref']);
            return { name: n, filled, html: filled ? XLSX.utils.sheet_to_html(ws, { id: '' }) : '' };
          });
          // Open on the first sheet that HAS something. Tools routinely leave an empty default
          // Sheet1 in front of the real one, and opening on it rendered an empty pane that reads
          // as a broken preview rather than as an empty tab.
          const first = sheets.findIndex((s) => s.filled);
          if (alive) {
            setActiveSheet(first < 0 ? 0 : first);
            setSt({ kind: 'sheet', sheets: sheets.length ? sheets : [{ name: 'Sheet1', html: '', filled: false }] });
          }
        } catch (e) {
          console.error('[preview] spreadsheet parse failed:', e);
          // Fall back to the server's PDF rendition. This used to set kind:'office' and NOTHING
          // else — and 'office' renders only when objUrl is set, so a workbook the parser choked
          // on produced a preview pane that stayed blank forever, with no error and no download
          // prompt. Fetch the rendition for real, and if that fails too, say so.
          try {
            const b = await fetchFileBlob(pdfUrlFor(url)); obj = URL.createObjectURL(b);
            if (alive) setSt({ kind: 'office', objUrl: obj });
          } catch {
            if (alive) setSt({ kind: 'binary',
              error: `This spreadsheet couldn\u2019t be read (${String((e as Error)?.message || 'parse failed').slice(0, 90)}). Download it to open it.` });
          }
        }
        return;
      }
      if (kind === 'code' || kind === 'markdown' || kind === 'csv') {
        const t = await r.text();
        if (!alive) return;
        if (kind === 'csv') setSt({ kind: 'csv', html: csvToTable(t) });
        else setSt({ kind, text: t.slice(0, 400000) });
      } else if (kind === 'binary') {
        if (alive) setSt({ kind: 'binary' });
      } else {
        const b = await r.blob(); obj = URL.createObjectURL(b);
        if (alive) setSt({ kind, objUrl: obj });
      }
    }).catch(() => { if (alive) setSt({ kind: 'binary', error: 'Could not load this file.' }); });
    return () => { alive = false; if (obj) URL.revokeObjectURL(obj); };
  }, [url, name]);

  return (
    <div className="fp-panel">
      <header className="fp-head">
        <span className="fp-ic"><FileTypeIcon name={name} size={18} /></span>
        <span className="fp-name" title={name}>{name}</span>
        <button className="fp-icbtn" title="Download" onClick={() => { downloadFile(url, name).catch(() => undefined); }}><IcDownload /></button>
        <button className="fp-icbtn" title="Close" onClick={onClose}><IcX /></button>
      </header>
      <div className="fp-body">
        {st.kind === 'loading' && <div style={{ padding: 18 }}><span className="sk" style={{ display: 'block', width: '100%', height: 220, borderRadius: 10 }} /></div>}
        {st.kind === 'image' && st.objUrl && <div className="fp-center"><img className="fp-img" src={st.objUrl} alt={name} /></div>}
        {st.kind === 'pdf' && st.objUrl && <iframe className="fp-pdf" src={st.objUrl} title={name} />}
        {st.kind === 'office' && st.objUrl && <iframe className="fp-pdf" src={st.objUrl} title={name} />}
        {st.kind === 'video' && st.objUrl && <div className="fp-center"><video className="fp-media" src={st.objUrl} controls /></div>}
        {st.kind === 'audio' && st.objUrl && <div className="fp-center"><audio src={st.objUrl} controls /></div>}
        {st.kind === 'markdown' && <div className="fp-doc"><ReactMarkdown remarkPlugins={[remarkGfm]}>{st.text || ''}</ReactMarkdown></div>}
        {st.kind === 'code' && (
          <SyntaxHighlighter language={langOf(name)} style={oneLight} showLineNumbers
            customStyle={{ margin: 0, padding: '16px 18px', background: '#FBFBFD', color: '#383A42', fontSize: 12.5, lineHeight: 1.6, whiteSpace: 'pre', overflowX: 'auto' }}
            lineNumberStyle={{ color: '#B0B4C0', minWidth: '2.4em', paddingRight: '14px' }}
            codeTagProps={{ style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', color: '#383A42', whiteSpace: 'pre' } }}>
            {st.text || ''}
          </SyntaxHighlighter>
        )}
        {st.kind === 'csv' && <div className="fp-sheet" dangerouslySetInnerHTML={{ __html: st.html || '' }} />}
        {st.kind === 'sheet' && st.sheets && (
          <div className="fp-xlsx">
            {st.sheets[activeSheet]?.filled
              ? <div className="fp-sheet" dangerouslySetInnerHTML={{ __html: st.sheets[activeSheet]?.html || '' }} />
              : <div className="fp-sheet fp-sheet-empty">This sheet is empty.</div>}
            {/* Always shown, even for a single sheet: the tab bar is what tells someone they are
                looking at a spreadsheet with other sheets in it, and hiding it on the one-sheet
                case is what made an empty first sheet look like a failed preview. */}
            <div className="fp-sheet-tabs">
              {st.sheets.map((s, i) => (
                <button key={i} className={'fp-sheet-tab' + (i === activeSheet ? ' on' : '') + (s.filled ? '' : ' empty')}
                  onClick={() => setActiveSheet(i)} title={s.filled ? s.name : `${s.name} (empty)`}>{s.name}</button>
              ))}
            </div>
          </div>
        )}
        {st.kind === 'binary' && (
          <div className="fp-center"><div className="fp-fallback">
            <FileTypeIcon name={name} size={64} />
            <p className="hr-meta" style={{ marginTop: 14 }}>{st.error || 'No inline preview for this file type.'}</p>
            <button className="hr-btn primary" style={{ marginTop: 8 }}
              onClick={() => { downloadFile(url, name).catch(() => undefined); }}>Download</button>
          </div></div>
        )}
      </div>
    </div>
  );
}

function csvToTable(text: string): string {
  const rows = text.split(/\r?\n/).filter((r) => r.length).slice(0, 1000);
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const split = (line: string) => {
    const out: string[] = []; let cur = ''; let q = false;
    for (const ch of line) {
      if (ch === '"') q = !q;
      else if ((ch === ',' || ch === '\t') && !q) { out.push(cur); cur = ''; }
      else cur += ch;
    }
    out.push(cur); return out;
  };
  return '<table>' + rows.map((r, i) => {
    const cells = split(r).map((c) => `<${i === 0 ? 'th' : 'td'}>${esc(c.replace(/^"|"$/g, ''))}</${i === 0 ? 'th' : 'td'}>`).join('');
    return `<tr>${cells}</tr>`;
  }).join('') + '</table>';
}

const IcDownload = () => <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></svg>;
const IcX = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>;
