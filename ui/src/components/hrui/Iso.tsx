// A brick tower drawing (tower.ts) placed in the page. The drawing is markup the design builds as a
// string; its only text (harness and model names) is escaped in tower.ts.
export function Iso({ svg, className }: { svg: string; className?: string }) {
  // without a class of its own the wrapper takes no box, so the drawing sizes to its container as
  // the design's does (it is the container's own child there)
  return <span className={className} style={className ? undefined : { display: 'contents' }} aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
}
