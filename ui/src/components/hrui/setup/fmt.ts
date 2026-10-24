// The design's formatting helpers (docs/uxuidesign/console-79: sec, clock, idle, ktok, cutWords,
// preview, plural), ported as written, plus the one reading of a task card's status the Tasks tab
// draws from. `ago` lives in ../setups.
import type { FeedTurn } from '@/lib/conversation';
import { RUNNING, TERMINAL_BAD, TERMINAL_OK, type TraceCard } from '@/lib/revamp-data';

/** "{ms} ms" under a second, else "{x.x} s". */
export function sec(ms: number): string {
  return ms < 1000 ? Math.round(ms) + ' ms' : (ms / 1000).toFixed(1) + ' s';
}

/** h:mm:ss */
export function clock(ms: number): string {
  const x = Math.max(0, Math.round(ms / 1000));
  const hh = Math.floor(x / 3600), m = Math.floor((x % 3600) / 60), s = x % 60;
  return hh + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
}

/** An idle gap between turns. */
export function idle(ms: number): string {
  const s = ms / 1000;
  if (s < 60) return s.toFixed(1) + ' s';
  if (s < 3600) return Math.round(s / 60) + ' min';
  if (s < 86400) return Math.round(s / 3600) + ' h';
  const d = Math.round(s / 86400);
  return d + (d > 1 ? ' days' : ' day');
}

export function ktok(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
}

export function preview(s: string): string {
  return String(s || '').replace(/\s+/g, ' ').trim().slice(0, 140);
}

/** Cut at a word boundary no longer than n, without a trailing , . ; : and with an ellipsis. */
export function cutWords(s: string, n: number): string {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  if (s.length <= n) return s;
  let out = '';
  s.split(' ').some((w) => {
    if ((out ? out.length + 1 : 0) + w.length > n) return true;
    out += (out ? ' ' : '') + w;
    return false;
  });
  return (out || s.slice(0, n)).replace(/[,.;:]$/, '') + '…';
}

export function plural(n: number, w: string): string {
  return n + ' ' + w + (n === 1 ? '' : 's');
}

/** The design's task states. A card says more ways than the design draws, so they fold here. */
export type TaskState = 'running' | 'done' | 'failed' | 'incomplete' | 'cancelled' | 'unknown';

export function stateOf(c: TraceCard | null | undefined): TaskState {
  const s = String(c?.status || '').toLowerCase();
  if (RUNNING.has(s) || s === 'queued' || s === 'created') return 'running';
  if (TERMINAL_OK.has(s)) return 'done';
  if (TERMINAL_BAD.has(s)) return 'failed';
  if (s === 'incomplete' || s === 'timeout' || s === 'max_turns') return 'incomplete';
  if (s === 'cancelled' || s === 'canceled' || s === 'stopped') return 'cancelled';
  return 'unknown';
}

/** A task's state as its row and its bar show it: the harness's feed first, which says a turn's
 *  start and end the moment they happen (lib/conversation feedTurnOf), then the card, which a read
 *  of the list can carry from before either. The card wins only where it is about the feed's own
 *  turn: a finished card naming the turn the feed saw start, or naming none (a turn that died, set
 *  right from the card written as it started), is an end the feed missed. A card still reading
 *  running after the feed saw its turn end is drawn finished until it says how it ended. */
export function liveStateOf(c: TraceCard | null | undefined, feed: FeedTurn | undefined): TaskState {
  const st = stateOf(c);
  if (!feed) return st;
  const rid = String(c?.last_response_id || '');
  // a finished card of the feed's own turn: the one its end wrote (naming that turn), or a turn that
  // died repaired from the card written as it started (which names none; no end ever reaches the feed)
  const ours = !rid || rid === feed.rid;
  if (feed.on) return ours && st !== 'running' && st !== 'unknown' ? st : 'running';
  return st === 'running' ? 'unknown' : st;
}

/** When a task last did something, in ms: its card's latest write (its start while it runs, else its
 *  latest settle). The gateway's cards carry no time of their own creation, so a task's list and its
 *  ranges read this one. */
export function createdMs(c: TraceCard): number {
  return (Number(c.finished_at) || 0) * 1000;
}

/** How long it ran, in ms, when the card says. */
export function durMs(c: TraceCard): number {
  const e = Number(c.elapsed);
  return Number.isFinite(e) && e > 0 ? e * 1000 : 0;
}
