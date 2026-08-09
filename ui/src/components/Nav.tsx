'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useDialog } from 'reifyui';
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
  const dialog = useDialog();
  const [list, setList] = useState<Workspace[]>([DEFAULT_WORKSPACE]);
  const [ws, setWs] = useState(DEFAULT_WORKSPACE.id);

  useEffect(() => { setList(listWorkspaces()); setWs(currentWorkspace()); }, []);

  const onSwitch = async (id: string) => {
    if (id === '__new') {
      // Keep the select showing the workspace we're actually in while the dialog is open, so a
      // cancel doesn't leave "+ New workspace…" selected.
      setWs(currentWorkspace());
      const name = await dialog.prompt({
        title: 'New workspace',
        label: 'Name',
        placeholder: 'Backend rewrite',
        help: 'A workspace scopes its own harnesses and tasks.',
        validate: (v) => {
          const t = v.trim();
          if (!t) return 'Give the workspace a name.';
          const slug = t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
          if (!slug) return 'Use at least one letter or number.';
          if (listWorkspaces().some((w) => w.id === slug)) return 'A workspace with that name already exists.';
          return null;
        },
      });
      if (!name?.trim()) return;
      const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      saveWorkspaces([...listWorkspaces(), { id: slug, name: name.trim() }]);
      setCurrentWorkspace(slug);
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
