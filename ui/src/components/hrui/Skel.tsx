// Loading, drawn as the thing that is loading (Richard, 2026-10-18: "let's all use skeleton for
// loading on all places"). Every piece is the design's own shimmer line (.pl-sk) laid out in the
// shape of the content it stands for, so the page does not jump when the content lands. A screen
// reader hears one "Loading" per skeleton, not the shapes.
import type { CSSProperties, ReactNode } from 'react';

/** One shimmer bar. `w` and `h` are CSS lengths (numbers are px). */
export function SkLine({ w = '100%', h = 12, r, style }: { w?: number | string; h?: number; r?: number; style?: CSSProperties }) {
  return <span className="pl-sk" aria-hidden="true" style={{ width: w, height: h, ...(r != null ? { borderRadius: r } : null), ...style }} />;
}

/** The wrapper every skeleton sits in: busy for assistive tech, invisible text naming what loads. */
export function Skel({ label = 'Loading', children, className, style }: { label?: string; children: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <div className={`hrui-skel${className ? ` ${className}` : ''}`} role="status" aria-busy="true" style={style}>
      <span className="sr">{label}</span>
      {children}
    </div>
  );
}

/** Setup cards (Studio's card grid): the tower area, then name, harness line and three figures. */
export function SkCards({ n = 3 }: { n?: number }) {
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="card hrui-skel-card" aria-hidden="true">
          <div className="card-tower"><SkLine w="46%" h={150} r={14} style={{ margin: '0 auto' }} /></div>
          <div className="card-body">
            <SkLine w="55%" h={14} />
            <SkLine w="70%" h={11} style={{ marginTop: 10 }} />
            <SkLine w="40%" h={11} style={{ marginTop: 8 }} />
            <div className="hrui-skel-stats"><SkLine w="80%" h={22} /><SkLine w="80%" h={22} /><SkLine w="80%" h={22} /></div>
          </div>
        </div>
      ))}
    </>
  );
}

/** List rows: a leading mark, a title and a second line, and `cols` short figures on the right. */
export function SkRows({ n = 5, cols = 0, lead = true }: { n?: number; cols?: number; lead?: boolean }) {
  return (
    <div className="hrui-skel-rows" aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="hrui-skel-row">
          {lead ? <SkLine w={28} h={28} r={8} /> : null}
          <div className="hrui-skel-grow"><SkLine w={`${48 + ((i * 17) % 30)}%`} h={13} /><SkLine w={`${30 + ((i * 11) % 25)}%`} h={10} style={{ marginTop: 8 }} /></div>
          {Array.from({ length: cols }, (_, j) => <SkLine key={j} w={56} h={12} />)}
        </div>
      ))}
    </div>
  );
}

/** A page's top: title and its line. */
export function SkHead({ title = '38%', sub = '56%' }: { title?: string; sub?: string }) {
  return (
    <div className="hrui-skel-head" aria-hidden="true">
      <SkLine w={title} h={30} r={8} />
      <SkLine w={sub} h={13} style={{ marginTop: 14 }} />
    </div>
  );
}

/** A chart panel: figures across the top, then the bars' area. */
export function SkChart({ figures = 4, height = 220 }: { figures?: number; height?: number }) {
  return (
    <div className="hrui-skel-chart" aria-hidden="true">
      <div className="hrui-skel-figs">
        {Array.from({ length: figures }, (_, i) => <div key={i}><SkLine w="50%" h={10} /><SkLine w="70%" h={26} style={{ marginTop: 10 }} /></div>)}
      </div>
      <SkLine w="100%" h={height} r={12} style={{ marginTop: 22 }} />
    </div>
  );
}

/** A conversation: a request on the right, an answer's meta line and paragraphs on the left. */
export function SkThread() {
  return (
    <div className="hrui-skel-thread" aria-hidden="true">
      <SkLine w="46%" h={42} r={18} style={{ marginLeft: 'auto' }} />
      <SkLine w="28%" h={11} style={{ marginTop: 26 }} />
      <SkLine w="92%" h={12} style={{ marginTop: 14 }} />
      <SkLine w="86%" h={12} style={{ marginTop: 9 }} />
      <SkLine w="64%" h={12} style={{ marginTop: 9 }} />
    </div>
  );
}
