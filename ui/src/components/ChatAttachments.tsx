'use client';
// The attachment and output-file cards a conversation renders.
//
// These live here because TWO surfaces show them — Tasks and Arena — and the second one grew its
// own thinner versions instead of these: a text pill with an × where an image thumbnail belongs,
// and a bare row where the output card belongs. One definition, so a column in an arena is the
// same card as a task, because it is the same card.
import React, { useState } from 'react';
import { FileTypeIcon } from '@/components/FileTypeIcon';
import { containerFileUrl, downloadFile, type RespFile } from '@/lib/chat';

const Svg = ({ s = 16, children }: { s?: number; children: React.ReactNode }) => (
  <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);
export const IcDl = () => (
  <Svg s={16}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></Svg>
);

/** One attached input file: a thumbnail when it is an image, an icon card when it is not. */
export function AttachCard({ name, dataUri, onRemove }: { name: string; dataUri?: string; onRemove?: () => void }) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  const isImg = /^(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(ext) && !!dataUri && dataUri.startsWith('data:image');
  return (
    <div className={'wbx-attach' + (isImg ? ' img' : '')}>
      {onRemove && <button className="wbx-attach-x" title="Remove" onClick={onRemove}>×</button>}
      {isImg
        /* ph-no-capture: src is the uploaded file itself, inlined as a data URI. Attribute
           masking already blanks it; blocking the element keeps the whole thing out. */
        ? <img className="wbx-attach-thumb ph-no-capture" src={dataUri} alt={name} />
        : <><span className="wbx-attach-ic"><FileTypeIcon name={name} size={26} /></span>
            <span className="wbx-attach-meta"><span className="wbx-attach-name">{name}</span>
              <span className="wbx-attach-ext">{ext.toUpperCase() || 'FILE'}</span></span></>}
    </div>
  );
}

/** The output files of one assistant turn, plus a zip-them-all row once there are several. */
export function OutputFiles({ files, onPreview }: {
  files: RespFile[]; onPreview: (p: { url: string; name: string }) => void;
}) {
  // the archive is refused, with the names, when a cited file is no longer there; the row says so
  const [zipErr, setZipErr] = useState('');
  if (!files.length) return null;
  const zipUrl = `/api/harness/v1/sessions/${encodeURIComponent(files[0].container_id)}`
    + `/files/archive?files=${encodeURIComponent(files.map((f) => f.file_id).join(','))}`;
  return (
    <div className="wbx-files">
      {files.map((f, j) => (
        <div key={j} className="wbx-filecard"
          onClick={() => onPreview({ url: containerFileUrl(f), name: f.filename })}>
          <span className="wbx-filecard-ic"><FileTypeIcon name={f.filename} size={30} /></span>
          <span className="wbx-filecard-meta">
            <span className="wbx-filecard-name">{f.filename}</span>
            <span className="wbx-filecard-sub">{(f.filename.split('.').pop() || 'file').toUpperCase()} · output</span>
          </span>
          {/* Authed download (LIVE-B): a bare href carries no session and is rejected. */}
          <button className="wbx-filecard-dl" title="Download" type="button"
            onClick={(e) => { e.stopPropagation(); downloadFile(containerFileUrl(f), f.filename).catch(() => undefined); }}><IcDl /></button>
          <span className="wbx-filecard-open">Preview</span>
        </div>
      ))}
      {/* One-click zip of THIS turn's outputs (folder hierarchy preserved inside the archive).
          Only worth a row when there's more than one file. */}
      {files.length > 1 && (
        <button className="wbx-zipall" type="button"
          onClick={(e) => { e.stopPropagation(); setZipErr(''); downloadFile(zipUrl, 'outputs.zip').catch((err: unknown) => setZipErr(err instanceof Error ? err.message : 'Could not build the archive.')); }}>
          <IcDl /> Download all ({files.length}) as .zip
        </button>
      )}
      {zipErr && <div className="wbx-zipall-err" role="alert">{zipErr}</div>}
    </div>
  );
}
