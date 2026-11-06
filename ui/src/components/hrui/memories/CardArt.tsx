'use client';
// The picture at the top of a memory's card, in the same box as a setup's tower on Studio. It draws
// what the memory is, from what was read of it and nothing else:
//   · a schema of types: each type with its colour and icon where it sits, its name under it, and the
//     relations between types as lines named in mono, the way the Schema tab draws them;
//   · labels: the vocabulary as a row of chips, since labels name facts and do not relate;
//   · no schema: the first records it keeps, a row each, and how many more there are;
//   · nothing kept yet: the empty shape of a schema, dashed, like an unbuilt brick.
import { typeLabel, type LSchema } from './schemaModel';
import { MmIco } from './parts';

const W = 260, H = 200;
/** Rows drawn for a memory with no schema; more say "+N more". */
const ROWS = 5;
/** Records named on the card, when their titles were read. */
const TITLES = 3;
/** Chips drawn for a vocabulary; more say "+N". */
const CHIPS = 8;
// widths of the rows, so a list of records does not read as one block
const ROW_W = [88, 72, 80, 64, 76];

export function CardArt({ s, labels, records, recent, pending }: {
  s: LSchema | null | undefined; labels: boolean; records: number | null; recent?: string[] | null; pending?: boolean;
}) {
  // a schema still being read draws nothing yet, so the card does not change its picture once it comes
  if (pending) return null;
  const T = s?.types || [];
  if (T.length && labels) return <Vocabulary s={s as LSchema} />;
  if (T.length) return <SchemaArt s={s as LSchema} />;
  if (records && records > 0) return <Rows n={records} titles={recent} />;
  return <Ghost />;
}

/** Types where they sit, joined by their relations. */
function SchemaArt({ s }: { s: LSchema }) {
  const T = s.types, many = T.length > 6;
  const r = many ? 11 : 15;
  const padX = 46, top = 26, bottom = many ? 34 : 40;
  const xs = T.map((t) => t.x), ys = T.map((t) => t.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const f = Math.min((W - 2 * padX) / Math.max(1, x1 - x0), (H - top - bottom) / Math.max(1, y1 - y0), 0.62);
  const ox = (W - (x1 - x0) * f) / 2, oy = top + (H - top - bottom - (y1 - y0) * f) / 2;
  const at = new Map(T.map((t) => [t.id, [ox + (t.x - x0) * f, oy + (t.y - y0) * f] as const]));
  return (
    <svg className="mm-art-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Schema: ${T.map((t) => typeLabel(t.name)).join(', ')}`}>
      <defs>
        <marker id="mm-ca-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0.8 7 4 0 7.2" fill="none" stroke="var(--faint)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
      </defs>
      {s.relations.map((rel) => {
        const a = at.get(rel.from), b = at.get(rel.to);
        if (!a || !b || rel.from === rel.to) return null;
        const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
        const ux = dx / len, uy = dy / len, gap = r + 3;
        const label = rel.name.toLowerCase(), lw = label.length * 6.6 + 10;
        const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
        return (
          <g key={rel.id}>
            <line x1={a[0] + ux * gap} y1={a[1] + uy * gap} x2={b[0] - ux * gap} y2={b[1] - uy * gap}
              stroke="var(--g-line, var(--line))" strokeWidth="1.4" markerEnd="url(#mm-ca-arrow)" />
            {!many && len > lw + 2 * gap ? (
              <g className="mm-ca-rel">
                <rect x={mx - lw / 2} y={my - 9} width={lw} height={18} rx={9} />
                <text x={mx} y={my + 4} textAnchor="middle">{label}</text>
              </g>
            ) : null}
          </g>
        );
      })}
      {T.map((t) => {
        const [x, y] = at.get(t.id) as readonly [number, number];
        const ic = many ? 11 : 15;
        return (
          <g key={t.id}>
            <circle cx={x} cy={y} r={r} fill={t.color} stroke="var(--surface)" strokeWidth="3" />
            <g transform={`translate(${x - ic / 2} ${y - ic / 2})`}><MmIco k={t.icon} size={ic} color="#fff" /></g>
            <text className="mm-ca-type" x={x} y={y + r + 15} textAnchor="middle">{typeLabel(t.name)}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Labels: names applied to facts, so a row of chips and no lines between them. */
function Vocabulary({ s }: { s: LSchema }) {
  const shown = s.types.slice(0, CHIPS), more = s.types.length - shown.length;
  return (
    <span className="mm-ca-chips" role="img" aria-label={`Labels: ${s.types.map((t) => typeLabel(t.name)).join(', ')}`}>
      {shown.map((t) => <span key={t.id} className="mm-ca-chip"><i style={{ background: t.color }} />{typeLabel(t.name)}</span>)}
      {more > 0 ? <span className="mm-ca-chip more">{`+${more}`}</span> : null}
    </span>
  );
}

/** The first records, a row each; without their titles, one quiet row a record. */
function Rows({ n, titles }: { n: number; titles?: string[] | null }) {
  const T = (titles || []).slice(0, TITLES);
  const shown = T.length || Math.min(n, ROWS), more = n - shown;
  return (
    <span className={`mm-ca-rows${T.length ? ' named' : ''}`} aria-hidden={!T.length}>
      {T.length
        ? T.map((t, i) => <span key={i} className="mm-ca-row"><i /><span>{t}</span></span>)
        : Array.from({ length: shown }, (_, i) => <span key={i} className="mm-ca-row"><i /><b style={{ width: `${ROW_W[i % ROW_W.length]}%` }} /></span>)}
      {more > 0 ? <small>{`+${more} more`}</small> : null}
    </span>
  );
}

/** Nothing kept yet: three types, dashed, not yet built. */
export function Ghost() {
  const P = [[90, 78], [170, 78], [130, 138]];
  return (
    <svg className="mm-art-svg mm-ca-ghost" viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      <line x1={106} y1={78} x2={154} y2={78} />
      <line x1={98} y1={92} x2={122} y2={124} />
      <line x1={162} y1={92} x2={138} y2={124} />
      {P.map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r={15} />)}
    </svg>
  );
}

/** The same picture, small, for a row of the list: the types and their relations as dots and lines,
 *  a vocabulary as a few chips' dots, records as lines, and nothing kept as an empty dashed ring. */
export function MiniArt({ s, labels, records }: { s: LSchema | null | undefined; labels: boolean; records: number | null }) {
  const T = s?.types || [], w = 36, h = 36;
  let inner: React.ReactNode;
  if (T.length && labels) {
    const shown = T.slice(0, 3);
    inner = shown.map((t, i) => <circle key={t.id} cx={w / 2 + (i - (shown.length - 1) / 2) * 9} cy={h / 2} r={3.4} fill={t.color} />);
  } else if (T.length) {
    const xs = T.map((t) => t.x), ys = T.map((t) => t.y), pad = 7;
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const f = Math.min((w - 2 * pad) / Math.max(1, x1 - x0), (h - 2 * pad) / Math.max(1, y1 - y0));
    const ox = (w - (x1 - x0) * f) / 2, oy = (h - (y1 - y0) * f) / 2;
    const at = new Map(T.map((t) => [t.id, [ox + (t.x - x0) * f, oy + (t.y - y0) * f] as const]));
    inner = (
      <>
        {s!.relations.map((r) => {
          const a = at.get(r.from), b = at.get(r.to);
          return a && b ? <line key={r.id} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="var(--line-strong, var(--faint))" strokeWidth="1" /> : null;
        })}
        {T.map((t) => { const p = at.get(t.id)!; return <circle key={t.id} cx={p[0]} cy={p[1]} r={3.6} fill={t.color} />; })}
      </>
    );
  } else if (records && records > 0) {
    inner = [0, 1, 2].slice(0, Math.min(3, records)).map((i) => (
      <g key={i}><circle cx={10} cy={11 + i * 7} r={1.6} fill="var(--faint)" /><rect x={14} y={10 + i * 7} width={[14, 11, 13][i]} height={2} rx={1} fill="var(--line-strong, var(--faint))" /></g>
    ));
  } else {
    inner = <circle cx={w / 2} cy={h / 2} r={8} fill="none" stroke="var(--line-strong, var(--faint))" strokeWidth="1.2" strokeDasharray="3 3" />;
  }
  return <svg className="mm-mini" viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true">{inner}</svg>;
}

/** What a new memory will be, before it exists: drawn dashed in the "next" blue, like a brick not yet
 *  built. The shape follows what its service does: a schema to design, labels to add, files, or records. */
export type Kind = 'schema' | 'labels' | 'files' | 'records' | null;
export function KindArt({ kind }: { kind: Kind }) {
  const w = 96, h = 80;
  let inner: React.ReactNode;
  if (kind === 'schema') {
    inner = (
      <>
        <line x1={34} y1={26} x2={62} y2={26} /><line x1={29} y1={33} x2={43} y2={51} /><line x1={67} y1={33} x2={53} y2={51} />
        <circle cx={26} cy={26} r={9} /><circle cx={70} cy={26} r={9} /><circle cx={48} cy={58} r={9} />
      </>
    );
  } else if (kind === 'labels') {
    inner = (
      <>
        <rect x={10} y={20} width={34} height={14} rx={7} /><rect x={50} y={20} width={36} height={14} rx={7} />
        <rect x={24} y={44} width={48} height={14} rx={7} />
      </>
    );
  } else if (kind === 'files') {
    inner = (
      <>
        <path d="M26 14h30l14 14v38H26z" /><path d="M56 14v14h14" />
        <line x1={34} y1={40} x2={62} y2={40} /><line x1={34} y1={48} x2={62} y2={48} /><line x1={34} y1={56} x2={52} y2={56} />
      </>
    );
  } else if (kind === 'records') {
    inner = [16, 34, 52].map((y) => <rect key={y} x={14} y={y} width={68} height={12} rx={5} />);
  } else {
    inner = <circle cx={w / 2} cy={h / 2} r={14} className="none" />;
  }
  return <svg className="mm-kind-svg" viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true">{inner}</svg>;
}
