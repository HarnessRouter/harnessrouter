// Mermaid diagram block, renders a ```mermaid fenced code block as an SVG diagram.
//
// Wired into the workbench markdown renderer so the model can emit a real diagram instead of a wall
// of `graph LR ...` source. mermaid is LAZY-loaded (dynamic import → its own chunk, only fetched when
// a diagram actually appears). Rendering is DEBOUNCED so a streaming fence renders once it settles
// (partial mermaid source throws until complete); on any parse error we fall back to the raw source.
'use client';
import React from 'react';

let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((mod) => {
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',   // sanitize labels, diagrams come from model output
        theme: 'default',
        fontFamily: 'inherit',
        flowchart: { useMaxWidth: true, htmlLabels: true },
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

let seq = 0;

export function Mermaid({ code }: { code: string }) {
  const hostRef = React.useRef<HTMLDivElement>(null);
  const [failed, setFailed] = React.useState(false);
  const idRef = React.useRef('mmd-' + (seq += 1));

  React.useEffect(() => {
    const src = (code || '').trim();
    if (!src) return undefined;
    let cancelled = false;
    const timer = setTimeout(() => {
      loadMermaid()
        .then((mermaid) => mermaid.render(`${idRef.current}-${seq += 1}`, src))
        .then(({ svg }) => {
          if (cancelled || !hostRef.current) return;
          hostRef.current.innerHTML = svg;
          setFailed(false);
        })
        .catch(() => { if (!cancelled) setFailed(true); });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [code]);

  if (failed) {
    return <pre className="wbx-mermaid-fallback"><code>{code}</code></pre>;
  }
  return <div className="wbx-mermaid" ref={hostRef} aria-label="diagram" />;
}
