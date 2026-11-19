export function formatElapsed(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined || !Number.isFinite(milliseconds) || milliseconds < 0) return '';
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  if (seconds < 60) return `用时 ${seconds}秒`;
  return `用时 ${Math.floor(seconds / 60)}分钟 ${seconds % 60}秒`;
}
