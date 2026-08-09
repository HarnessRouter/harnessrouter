'use client';
// Shared shimmer-skeleton primitives, every loading state renders content-shaped skeletons
// instead of "Loading…" text (standing design rule). Styles live in revamp.css glue (.sk*).

/** One shimmering line. */
export function SkelLine({ w = '100%', h = 12, style }: { w?: number | string; h?: number; style?: React.CSSProperties }) {
  return <span className="sk" style={{ width: w, height: h, ...style }} />;
}

/** Table-body skeleton: `rows` rows of `cols` shimmering cells. */
export function SkelRows({ rows = 4, cols = 5, first = 160 }: { rows?: number; cols?: number; first?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="sk-tr">
          {Array.from({ length: cols }).map((__, c) => (
            <td key={c}><SkelLine w={c === 0 ? first : c === cols - 1 ? 28 : 64} /></td>
          ))}
        </tr>
      ))}
    </>
  );
}

/** List-item skeleton for the task list (title + sub line). */
export function SkelListItems({ rows = 5 }: { rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="sk-item">
          <SkelLine w={`${62 + ((i * 13) % 26)}%`} h={13} />
          <SkelLine w={90} h={10} style={{ marginTop: 8 }} />
        </div>
      ))}
    </>
  );
}

/** Full-page skeleton (header + blocks) for page-level gates. */
export function SkelPage() {
  return (
    <div className="page" aria-busy="true" aria-label="Loading">
      <div className="sk-page-head">
        <SkelLine w={260} h={26} />
        <SkelLine w={420} h={12} style={{ marginTop: 12 }} />
      </div>
      <div className="sk-blocks">
        <span className="sk sk-block" />
        <span className="sk sk-block" />
        <span className="sk sk-block tall" />
      </div>
    </div>
  );
}
