// A brick tower drawing (tower.ts) placed in the page. The drawing is markup the design builds as a
// string; its only text (harness and model names) is escaped in tower.ts.
import { useHtml } from './Markup';

const CONTENTS = { display: 'contents' } as const;

export function Iso({ svg, className }: { svg: string; className?: string }) {
  // without a class of its own the wrapper takes no box, so the drawing sizes to its container as
  // the design's does (it is the container's own child there). The same markup keeps the same drawing
  // across renders (Markup.tsx): a card is mostly this picture, and a press on it must open the card.
  const html = useHtml(svg);
  return <span className={className} style={className ? undefined : CONTENTS} aria-hidden="true" dangerouslySetInnerHTML={html} />;
}
