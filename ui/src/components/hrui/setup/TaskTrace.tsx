'use client';
// A task's Trace tab, laid out as the console's earlier trace (Richard, 2026-10-18): the events first,
// in the shared trace view (trace/TraceView), with how long the task ran in its head line. Every
// figure is the recorded trace's own.
import { TraceView, useTrace } from '../trace/TraceView';
import type { TraceCard } from '@/lib/revamp-data';
import { durMs, sec, type TaskState } from './fmt';

export function StatusPill({ st }: { st: TaskState }) {
  if (st === 'running') return <span className="pill run"><span className="dot run" />Running</span>;
  if (st === 'done') return <span className="pill ok">Completed</span>;
  if (st === 'failed') return <span className="pill bad">Failed</span>;
  if (st === 'incomplete') return <span className="pill bad">Incomplete</span>;
  if (st === 'cancelled') return <span className="pill neutral">Cancelled</span>;
  return null;
}

/** The trace of one task, in the setup's Tasks tab (the shared trace view, trace/TraceView). */
export function TraceBody({ card, st, openError }: {
  card: TraceCard; st: TaskState;
  /** select the last error once the events are in (a failed task picked while this tab shows) */
  openError: boolean;
}) {
  const sid = card.session_id;
  const running = st === 'running';
  const { rows, failed } = useTrace(sid, running);
  const d = durMs(card);
  return (
    <div className="trace trv-page">
      <TraceView sid={sid} rows={rows} failed={failed} running={running} openError={openError}
        head={d ? <span className="chip">{sec(d)}</span> : null} />
    </div>
  );
}
