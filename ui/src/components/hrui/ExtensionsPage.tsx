'use client';
// Add-ons (docs/uxuidesign/console-79, view `library`: libraryView, libTabShow): what the setups of
// the current workspace can use, in four tabs: Plugins, Skills, Tools, Environments. Every row and
// count is read live: the plugin catalog with each plugin's state in the workspace, the setups' own
// skills and MCP servers, the workspace's environments. A count not read yet shows nothing. Every read
// ends (lib/settle.ts): a list that could not be read says so in its tab, with Try again, never a
// skeleton that waits forever.
import { useCallback, useEffect, useLayoutEffect, useState } from 'react';
import { listCustom, type CustomHarness } from '@/lib/harness';
import { readSettled } from '@/lib/settle';
import { useWorkspace } from '@/lib/workspace';
import { PagePic, partIcon } from './bricks';
import { usePlugins, PluginsTab } from './ext/PluginsTab';
import { SkillsTab, skillCount } from './ext/SkillsTab';
import { ToolsTab, toolCount } from './ext/ToolsTab';
import { EnvsTab, useEnvironments } from './ext/EnvsTab';
import { tabKeys } from './tabKeys';

type Tab = 'plugins' | 'skills' | 'tools' | 'envs';
const TABS: [Tab, string, string][] = [['plugins', 'Plugins', 'plugin'], ['skills', 'Skills', 'skill'], ['tools', 'Tools', 'mcp'], ['envs', 'Environments', 'tool']];
const TAB_KEYS = TABS.map(([k]) => k);
const isTab = (v: string | null): v is Tab => TABS.some((t) => t[0] === v);
/** The tab an address names: ?tab=envs, or ?tab=environments as an older console's link reads. */
export const tabOf = (v: string | null): Tab | null => (v === 'environments' ? 'envs' : isTab(v) ? v : null);

export function ExtensionsPage() {
  const { current, defaultId, loading } = useWorkspace();
  const workspace = current.id || defaultId;
  const [tab, setTab] = useState<Tab>('plugins');
  // the tab is in the address (?tab=skills), so a link can open one
  useEffect(() => { const t = tabOf(new URLSearchParams(window.location.search).get('tab')); if (t) setTab(t); }, []);
  const pick = (t: Tab) => {
    setTab(t);
    const q = new URLSearchParams(window.location.search);
    if (t === 'plugins') q.delete('tab'); else q.set('tab', t);
    const qs = q.toString();
    window.history.replaceState(window.history.state, '', window.location.pathname + (qs ? `?${qs}` : ''));
  };
  // on a phone the tab row slides: keep the chosen tab in view
  useLayoutEffect(() => {
    const b = document.querySelector<HTMLElement>('#hrui .lw-n .tabs.inline button.on'), r = b?.parentElement;
    if (b && r && r.scrollWidth > r.clientWidth) r.scrollLeft = Math.max(0, b.offsetLeft - r.offsetLeft - (r.clientWidth - b.offsetWidth) / 2);
  }, [tab]);

  // the workspace's setups: who uses what, and where its tools and skills live
  const [setups, setSetups] = useState<CustomHarness[] | null>(null);
  const [setupsFailed, setSetupsFailed] = useState(false);
  const reloadSetups = useCallback(async () => {
    try { setSetups(await readSettled((signal) => listCustom(signal))); setSetupsFailed(false); }
    catch { setSetupsFailed(true); }
  }, []);
  useEffect(() => { if (!loading) void reloadSetups(); }, [loading, workspace, reloadSetups]);
  const plugins = usePlugins(loading ? '' : workspace);
  const envs = useEnvironments(loading ? '' : workspace);
  // Skills and Tools are read from the setups: their read failing fails both tabs
  const retrySetups = () => { setSetupsFailed(false); void reloadSetups(); };

  const counts: Record<Tab, number | null> = {
    plugins: plugins.connectedCount,      // what Plugins lists as connected
    skills: setups ? skillCount(setups) : null,
    tools: setups ? toolCount(setups) : null,
    envs: envs.envs ? envs.envs.length : null,
  };

  return (
    <div className="scroll">
      <div className="list-wrap lw-n">
        <div className="list-top ph">
          <div>
            <h1>Add-ons</h1>
          </div>
          <PagePic kind="ext" />
        </div>
        <div className="tabs inline" role="tablist" aria-label="Add-ons" onKeyDown={(e) => tabKeys(e, TAB_KEYS, tab, pick)}>
          {TABS.map(([k, label, fam]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} tabIndex={tab === k ? 0 : -1} className={tab === k ? 'on' : ''} onClick={() => pick(k)}>
              <span className="tab-brick" aria-hidden="true" dangerouslySetInnerHTML={{ __html: partIcon('built', fam) }} />{label}{' '}
              <span className="count">{counts[k] ?? ''}</span>
            </button>
          ))}
        </div>
        {tab === 'plugins' ? <PluginsTab data={plugins} workspace={loading ? '' : workspace} /> : null}
        {tab === 'skills' ? <SkillsTab setups={setups} reload={reloadSetups} failed={setupsFailed} retry={retrySetups} /> : null}
        {tab === 'tools' ? <ToolsTab setups={setups} reload={reloadSetups} failed={setupsFailed} retry={retrySetups} /> : null}
        {tab === 'envs' ? <EnvsTab data={envs} setups={setups} reloadSetups={reloadSetups} /> : null}
      </div>
    </div>
  );
}
