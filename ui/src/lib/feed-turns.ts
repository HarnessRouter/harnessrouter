// Each turn start and end a harness feed in this tab reports (lib/conversation useHarnessBus), with the
// harness it is of: Studio reads that setup's row again on each. Its own module, so a page that only
// listens does not load the conversation code with it.
type FeedTurnFn = (sid: string, harness: string, on: boolean) => void;
const subs = new Set<FeedTurnFn>();

/** Listen to every turn start and end the feeds in this tab report. Returns the unsubscribe. */
export function onFeedTurn(fn: FeedTurnFn): () => void {
  subs.add(fn);
  return () => { subs.delete(fn); };
}

/** A feed saw a turn of `harness` start (`on`) or end. */
export function emitFeedTurn(sid: string, harness: string, on: boolean): void {
  subs.forEach((f) => { try { f(sid, harness, on); } catch { /* one listener never stops the rest */ } });
}
