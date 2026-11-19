import { useEffect, useState } from 'react';
import { Button, Modal, Popover } from 'antd';
import { CheckOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons';
import { AppApiError, appCreateWorkspace, appSelectWorkspace, appUpdateWorkspace } from './app-api';

export type WorkspaceSummary = { id: number; name: string; description: string };

interface Props {
  workspaces: WorkspaceSummary[];
  currentId: number | null;
  onReload: () => Promise<void>;
  onSelected: (id: number) => void;
}

const initialOf = (name: string) => Array.from(name.trim())[0]?.toUpperCase() || 'W';
const errorText = (cause: unknown) => cause instanceof AppApiError ? cause.message : '操作失败，请稍后重试。';

export function WorkspaceMenu({ workspaces, currentId, onReload, onSelected }: Props) {
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const current = workspaces.find(row => row.id === currentId);

  useEffect(() => {
    if (!settingsOpen) return;
    setName(current?.name || '');
    setDescription(current?.description || '');
    setError('');
  }, [settingsOpen, current?.name, current?.description]);

  const choose = async (id: number) => {
    if (id === currentId) return setOpen(false);
    setBusy(true);
    setError('');
    try {
      await appSelectWorkspace(id);
      onSelected(id);
      setOpen(false);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  const openSettings = () => {
    if (!current) return;
    setOpen(false);
    setSettingsOpen(true);
  };

  const openCreate = () => {
    setOpen(false);
    setName('');
    setDescription('');
    setError('');
    setCreateOpen(true);
  };

  const saveSettings = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!current || !name.trim()) return setError('工作区名称不能为空。');
    setBusy(true);
    setError('');
    try {
      await appUpdateWorkspace(current.id, name.trim(), description.trim());
      await onReload();
      setSettingsOpen(false);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  const createWorkspace = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim()) return setError('工作区名称不能为空。');
    setBusy(true);
    setError('');
    try {
      const created = await appCreateWorkspace(name.trim(), description.trim());
      await appSelectWorkspace(created.id);
      await onReload();
      onSelected(created.id);
      setCreateOpen(false);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  };

  const panel = <div className="workspace-menu-panel" role="dialog" aria-label="工作空间">
    <div className="workspace-menu-label">工作空间</div>
    <div className="workspace-menu-list">
      {workspaces.map(row => <button
        key={row.id}
        type="button"
        className="workspace-menu-item"
        aria-label={row.name}
        aria-current={row.id === currentId ? 'true' : undefined}
        disabled={busy}
        onClick={() => void choose(row.id)}
      >
        <span className="workspace-avatar" aria-hidden="true">{initialOf(row.name)}</span>
        <span className="workspace-copy"><strong>{row.name}</strong><small>{row.description || '暂无说明'}</small></span>
        {row.id === currentId && <span className="workspace-selected-check" aria-hidden="true"><CheckOutlined /></span>}
      </button>)}
      {!workspaces.length && <p className="workspace-status">暂无工作空间，请先新建。</p>}
    </div>
    {error && <p className="workspace-form-error" role="alert">{error}</p>}
    <div className="workspace-menu-divider" />
    <div className="workspace-menu-actions">
      <button type="button" className="workspace-menu-action" aria-label="工作区设置" disabled={!current || busy} onClick={openSettings}><SettingOutlined aria-hidden="true" /> 工作区设置</button>
      <button type="button" className="workspace-menu-action" aria-label="新建工作区" disabled={busy} onClick={openCreate}><PlusOutlined aria-hidden="true" /> 新建工作区</button>
    </div>
  </div>;

  return <>
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="rightTop"
      arrow={false}
      rootClassName="workspace-popover"
      content={panel}
    >
      <button className="workspace" aria-label="切换工作区" aria-haspopup="dialog" aria-expanded={open}>
        {current ? initialOf(current.name) : 'W'}
      </button>
    </Popover>

    <Modal
      open={settingsOpen}
      title="工作区设置"
      onCancel={() => setSettingsOpen(false)}
      footer={null}
      centered
      width={480}
      className="workspace-form-dialog"
    >
      <form className="workspace-menu-form workspace-dialog-form" onSubmit={event => void saveSettings(event)}>
        <p className="workspace-dialog-copy">修改当前工作空间的名称和说明。名称与说明用于标识工作区。</p>
        <label htmlFor="workspace-settings-name">工作区名称<input id="workspace-settings-name" value={name} onChange={event => setName(event.target.value)} /></label>
        <label htmlFor="workspace-settings-description">工作区说明<textarea id="workspace-settings-description" value={description} onChange={event => setDescription(event.target.value)} /></label>
        {error && <p className="workspace-form-error" role="alert">{error}</p>}
        <div className="workspace-form-actions"><Button onClick={() => setSettingsOpen(false)}>取消</Button><Button type="primary" htmlType="submit" loading={busy} disabled={!name.trim()}>保存工作区</Button></div>
      </form>
    </Modal>

    <Modal
      open={createOpen}
      title="新建工作区"
      onCancel={() => setCreateOpen(false)}
      footer={null}
      centered
      width={480}
      className="workspace-form-dialog"
    >
      <form className="workspace-menu-form workspace-dialog-form" onSubmit={event => void createWorkspace(event)}>
        <p className="workspace-dialog-copy">创建工作区后会切换到新空间。工作区之间隔离 Agent、模板、任务和对话。</p>
        <label htmlFor="workspace-create-name">新工作区名称<input id="workspace-create-name" autoFocus placeholder="例如：设计系统空间" value={name} onChange={event => setName(event.target.value)} /></label>
        <label htmlFor="workspace-create-description">新工作区说明<textarea id="workspace-create-description" placeholder="补充这个工作空间的用途" value={description} onChange={event => setDescription(event.target.value)} /></label>
        {error && <p className="workspace-form-error" role="alert">{error}</p>}
        <div className="workspace-form-actions"><Button onClick={() => setCreateOpen(false)}>取消</Button><Button type="primary" htmlType="submit" loading={busy} disabled={!name.trim()}>创建工作区</Button></div>
      </form>
    </Modal>
  </>;
}
