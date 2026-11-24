export type WorkspaceSelection = { workspaces: Array<{ id: number; name: string; description: string }>; selected_id: number | null };
export type WorkspaceRestoration = { status: 'loading' } | { status: 'ready'; value: WorkspaceSelection } | { status: 'error'; cause: unknown };

export function createWorkspaceRestorer(read: () => Promise<WorkspaceSelection>, publish: (state: WorkspaceRestoration) => void) {
  let generation = 0;
  return {
    invalidate() { generation++; },
    async load() {
      const serial = ++generation;
      publish({ status: 'loading' });
      try {
        const value = await read();
        if (serial === generation) publish({ status: 'ready', value });
        return serial === generation;
      } catch (cause) {
        if (serial === generation) publish({ status: 'error', cause });
        return false;
      }
    },
  };
}
