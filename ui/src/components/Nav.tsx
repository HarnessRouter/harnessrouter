'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  DEFAULT_WORKSPACE, currentWorkspace, listWorkspaces, saveWorkspaces, setCurrentWorkspace,
  type Workspace,
} from '@/lib/api';

/** Sidebar: the two surfaces, plus the workspace switcher.
 *
 *  Switching workspace changes the scope of every gateway call, so it forces a reload rather
 *  than trying to invalidate each page's state — cheap here, and it removes a whole class of
 *  "stale list from the previous workspace" bugs. */
export function Nav() {
  const path = usePathname();
  const [list, setList] = useState<Workspace[]>([DEFAULT_WORKSPACE]);
  const [ws, setWs] = useState(DEFAULT_WORKSPACE.id);

  useEffect(() => { setList(listWorkspaces()); setWs(currentWorkspace()); }, []);

  const onSwitch = (id: string) => {
    if (id === '__new') {
      const name = window.prompt('New workspace name');
      if (!name?.trim()) return;
      const id2 = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
        || `ws-${Date.now()}`;
      const next = [...listWorkspaces(), { id: id2, name: name.trim() }];
      saveWorkspaces(next);
      setCurrentWorkspace(id2);
      window.location.reload();
      return;
    }
    setCurrentWorkspace(id);
    window.location.reload();
  };

  const is = (p: string) => (path === p || path.startsWith(p + '/') ? 'active' : '');

  return (
    <nav className="nav">
      <div className="nav-brand">HarnessRouter</div>
      <Link href="/harnesses" className={is('/harnesses')}>Harnesses</Link>
      <Link href="/tasks" className={is('/tasks')}>Tasks</Link>

      <div className="nav-ws">
        <label htmlFor="ws">Workspace</label>
        <select id="ws" className="select" value={ws} onChange={(e) => onSwitch(e.target.value)}>
          {list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          <option value="__new">+ New workspace…</option>
        </select>
      </div>
    </nav>
  );
}
