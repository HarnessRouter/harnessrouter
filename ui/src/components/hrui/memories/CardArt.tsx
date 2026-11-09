'use client';
// The small drawings of the Memories pages that aren't a memory's own picture (that is its cover or its brick, MemoryArt.tsx):
//   · Ghost: nothing kept yet, the empty shape of a schema, dashed, like an unbuilt brick;
//   · KindArt: what a new memory will be with an engine, before it exists;
//   · StarterArt: a starting schema, small, on the button that starts from it.
import type { LSchema } from './schemaModel';
import { MmIco } from './parts';

const W = 260, H = 200;

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

/** A starting schema, small, on the button that starts from it: its types in their colours and icons where they sit,
 *  and the relations between them; one dashed type for starting blank. */
export function StarterArt({ s }: { s: LSchema | null }) {
  const w = 120, h = 64, r = 9, pad = 14;
  if (!s || !s.types.length) {
    return <svg className="mm-starter-svg" viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><circle cx={w / 2} cy={h / 2} r={r + 2} className="ghost" /></svg>;
  }
  const T = s.types, xs = T.map((t) => t.x), ys = T.map((t) => t.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const f = Math.min((w - 2 * pad) / Math.max(1, x1 - x0), (h - 2 * pad) / Math.max(1, y1 - y0));
  const ox = (w - (x1 - x0) * f) / 2, oy = (h - (y1 - y0) * f) / 2;
  const at = new Map(T.map((t) => [t.id, [ox + (t.x - x0) * f, oy + (t.y - y0) * f] as const]));
  return (
    <svg className="mm-starter-svg" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      {s.relations.map((rel) => {
        const a = at.get(rel.from), b = at.get(rel.to);
        return a && b ? <line key={rel.id} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="var(--line-strong, var(--faint))" strokeWidth="1.2" /> : null;
      })}
      {T.map((t) => {
        const [x, y] = at.get(t.id) as readonly [number, number];
        return (
          <g key={t.id}>
            <circle cx={x} cy={y} r={r} fill={t.color} stroke="var(--bg)" strokeWidth="2" />
            <g transform={`translate(${x - 5.5} ${y - 5.5})`}><MmIco k={t.icon} size={11} color="#fff" /></g>
          </g>
        );
      })}
    </svg>
  );
}
