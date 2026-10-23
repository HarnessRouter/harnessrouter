// A workspace's mark: its first letter on a colour picked from its name, the same six colours and
// the same pick as the design (avColor), so a workspace keeps its colour everywhere it appears.
const COLORS = ['#285aff', '#e5484d', '#18a058', '#8a63f7', '#d68a00', '#0f9c94'];

export function wsColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 997;
  return COLORS[h % 6];
}

export function WsBadge({ name, size }: { name: string; size: number }) {
  return (
    <span className="ws-badge" aria-hidden="true"
      style={{ background: wsColor(name), width: size, height: size, fontSize: Math.round(size * 0.45) }}>
      {name.charAt(0).toUpperCase()}
    </span>
  );
}

/** A person's initials and colour, as the design draws people (avatar). */
export function initials(n: string): string {
  return String(n).split(/[\s@._-]+/).filter(Boolean).map((x) => x.charAt(0)).join('').slice(0, 2).toUpperCase();
}

export function Avatar({ name }: { name: string }) {
  return <span className="av" style={{ background: wsColor(name) }} title={name}>{initials(name)}</span>;
}
