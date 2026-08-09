'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  ChatMessages, Composer, TaskList, createConversationStore, pumpResponsesStream, useDialog,
} from 'reifyui';
import {
  cancelTask, deleteTask, listHarnesses, listTasks, loadTurns, streamTurn,
  type Harness, type TaskCard,
} from '@/lib/api';

function TasksInner() {
  const params = useSearchParams();
  const dialog = useDialog();
  const [harnesses, setHarnesses] = useState<Harness[]>([]);
  const [harnessId, setHarnessId] = useState(params.get('h') || '');
  const [sid, setSid] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  // One conversation store per session id. ReifyUI owns the block state machine; we only feed
  // it the stream and re-render when it changes.
  const store = useMemo(() => createConversationStore(), []);
  const [, force] = useState(0);
  useEffect(() => store.subscribe(() => force((n) => n + 1)), [store]);

  useEffect(() => {
    listHarnesses().then((hs) => {
      setHarnesses(hs);
      setHarnessId((cur) => cur || hs[0]?.id || '');
    }).catch((e) => setErr(String(e.message || e)));
  }, []);

  // Load an existing conversation when a task is selected.
  useEffect(() => {
    if (!sid) { store.setState({ blocks: [], turns: [] }); return; }
    loadTurns(sid)
      .then((turns) => store.setState({ turns, blocks: [] }))
      .catch(() => setErr('could not load this task'));
  }, [sid, store]);

  const fetchPage = useCallback(
    (cursor: string) => listTasks(harnessId, cursor),
    [harnessId],
  );

  const send = async (text: string) => {
    if (!text.trim() || !harnessId) return;
    setBusy(true); setErr('');
    try {
      const res = await streamTurn({
        model: harnesses.find((h) => h.id === harnessId)?.defaultModel,
        input: text,
        metadata: { harness_id: harnessId },
        ...(sid ? { session_hint: sid } : {}),
      });
      if (!res.ok) throw new Error(`turn failed (${res.status})`);
      const newSid = res.headers.get('x-harness-session');
      if (newSid && newSid !== sid) setSid(newSid);
      await pumpResponsesStream({ response: res, store });
    } catch (e) {
      setErr(String((e as Error).message || e));
    } finally {
      setBusy(false);
      setNonce((n) => n + 1);   // refresh the list so the new/updated task appears
    }
  };

  const stop = async () => {
    if (!sid) return;
    try { await cancelTask(sid); } catch { /* the turn may have just finished */ }
    setNonce((n) => n + 1);
  };

  const removeTask = async (t: TaskCard) => {
    const ok = await dialog.confirm({
      title: 'Delete this task?',
      message: `"${t.title || 'Untitled task'}" and its conversation will be removed. This cannot be undone.`,
      destructive: true,
      confirmLabel: 'Delete',
    });
    if (!ok) return;
    try {
      await deleteTask(t.session_id);
      if (t.session_id === sid) setSid(null);
      setNonce((n) => n + 1);
    } catch (e) {
      setErr(String((e as Error).message || e));
    }
  };

  const harnessSelect = (
    <select className="select" value={harnessId}
            onChange={(e) => { setHarnessId(e.target.value); setSid(null); }}>
      {harnesses.length === 0 ? <option value="">No harnesses yet</option> : null}
      {harnesses.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
    </select>
  );

  return (
    <div className="task-split">
      <div className="task-list-pane">
        <TaskList
          fetchPage={fetchPage}
          selected={sid}
          onSelect={(id: string) => setSid(id)}
          onNew={() => setSid(null)}
          onDelete={removeTask}
          header={harnessSelect}
          refreshNonce={nonce}
          idKey="session_id"
          newLabel="New task"
          emptyLabel="No tasks on this harness yet"
        />
      </div>

      <div className="task-detail">
        <div className="task-detail-head">
          <strong style={{ fontSize: 13 }}>{sid ? 'Task' : 'New task'}</strong>
          <div className="spacer" />
          {busy ? <button className="btn" onClick={stop}>Stop</button> : null}
        </div>

        {err ? <div style={{ padding: '10px 18px' }}><div className="banner banner-err">{err}</div></div> : null}

        <div className="task-msgs">
          {harnesses.length === 0 ? (
            <div className="empty">Create a harness first — a task runs on one.</div>
          ) : (
            <ChatMessages store={store} />
          )}
        </div>

        <div className="task-composer">
          <Composer
            onSend={send}
            disabled={!harnessId || busy}
            placeholder={harnessId ? 'Describe the task…' : 'Create a harness first'}
          />
        </div>
      </div>
    </div>
  );
}

export default function TasksPage() {
  // useSearchParams needs a Suspense boundary under the app router.
  return (
    <Suspense fallback={<div className="empty">Loading…</div>}>
      <TasksInner />
    </Suspense>
  );
}
