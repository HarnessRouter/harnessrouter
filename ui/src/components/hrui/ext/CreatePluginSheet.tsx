"use client";
import { useRef, useState } from 'react';
import { unzipSync } from 'fflate';
import { gw, getCustom, pluginSchemas, type CustomHarness } from '@/lib/harness';
import { Sheet, SheetTop } from '../Sheet';

export function CreatePluginSheet({ setups, onCreated, onClose }: {
  setups: CustomHarness[] | null; onCreated: () => Promise<void>; onClose: () => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [instructions, setInstructions] = useState('');
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const packageRef = useRef<HTMLInputElement | null>(null);


  function safePath(path: string) {
    return path.replaceAll('\\', '/').split('/').filter((part) => part && part !== '.' && part !== '..').join('/');
  }

  async function packageFiles(file: File) {
    const archive = unzipSync(new Uint8Array(await file.arrayBuffer()));
    const entries: { path: string; content_b64: string; executable?: boolean }[] = [];
    for (const [rawPath, bytes] of Object.entries(archive)) {
      const path = safePath(rawPath);
      if (!path || rawPath.endsWith('/') || !bytes.length) continue;
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      entries.push({ path, content_b64: btoa(binary), ...(path.startsWith('bin/') ? { executable: true } : {}) });
    }
    if (!entries.some((entry) => entry.path.startsWith('bin/'))) throw new Error('压缩包中需要至少包含一个 bin/ 下的 CLI 文件。');
    return entries;
  }

  async function create() {
    if (busy) return;
    const cleanName = name.trim();
    if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(cleanName) || cleanName.length > 64 || /--|\.\./.test(cleanName)) {
      setError('名称需为 1–64 个小写字母、数字、连字符或句点，以字母或数字开头和结尾，不能连续使用连字符或句点。'); return;
    }
    if (!description.trim() || !instructions.trim() || !target) { setError('请填写描述、使用说明并选择目标配置。'); return; }
    const packageFile = packageRef.current?.files?.[0] || null;
    if (!packageFile || !packageFile.name.toLowerCase().endsWith('.zip')) { setError('请先选择 ZIP 压缩包。'); return; }
    setBusy(true); setError('');
    try {
      const current = await getCustom(target);
      if (!current) throw new Error('目标配置已不存在，请重新选择。');
      if ((current.plugins || []).some((plugin) => plugin.name === cleanName)) throw new Error('目标配置已有同名插件，请使用其他名称。');
      const schemas = await pluginSchemas();
      if (!schemas.length) throw new Error('当前网关未提供可用的插件格式。');
      const manifest = { $schema: schemas[0], name: cleanName, version: '1.0.0', description: description.trim() };
      const skill = `---\nname: ${cleanName}\ndescription: ${JSON.stringify(description.trim())}\n---\n\n${instructions.trim()}\n`;
      const files = [
        { path: 'plugin.json', content: JSON.stringify(manifest, null, 2) },
        { path: `skills/${cleanName}/SKILL.md`, content: skill },
        ...(await packageFiles(packageFile)),
      ];
      await gw('PUT', `/v1/harnesses/${encodeURIComponent(target)}/plugin`, { name: cleanName, files });
    } catch (e) { setError(e instanceof Error ? e.message : '创建失败，请重试。'); setBusy(false); return; }
    await onCreated().catch(() => {});
    setBusy(false); onClose();
  }

  return <Sheet onClose={onClose} labelledBy="create-plugin-title" busy={busy}>
    <SheetTop id="create-plugin-title" title="创建插件" sub="将使用说明和 CLI 打包为插件，安装到所选智能体配置。" onClose={onClose} />
    <div className="set-f"><label htmlFor="plugin-name">插件名称</label><input id="plugin-name" className="set-in" value={name} maxLength={64} placeholder="例如 weekly-report" onChange={(e) => setName(e.target.value)} disabled={busy} /></div>
    <div className="set-f"><label htmlFor="plugin-description">描述</label><input id="plugin-description" className="set-in" value={description} onChange={(e) => setDescription(e.target.value)} disabled={busy} /></div>
    <div className="set-f"><label htmlFor="plugin-instructions">使用说明</label><textarea id="plugin-instructions" className="set-in" rows={8} value={instructions} onChange={(e) => setInstructions(e.target.value)} disabled={busy} placeholder="描述插件的使用场景、执行步骤和输出要求" /></div>
    <div className="set-f"><label htmlFor="plugin-package">插件 ZIP 压缩包</label><input id="plugin-package" ref={packageRef} className="set-in" type="file" accept=".zip,application/zip" disabled={busy} /><p className="set-help">请在压缩包中放入 bin/cli 文件，其他文件可放在 files/ 或自定义目录。</p></div>
    <div className="set-f"><label htmlFor="plugin-target">安装到配置</label><select id="plugin-target" className="set-in" value={target} onChange={(e) => setTarget(e.target.value)} disabled={busy || !setups?.length}><option value="">{setups === null ? '正在加载配置…' : setups.length ? '选择智能体配置' : '请先在工作台创建配置'}</option>{setups?.map((setup) => <option key={setup.id} value={setup.id}>{setup.name}</option>)}</select></div>
    {error ? <p role="alert" className="keywarn">{error}</p> : null}
    <div className="sheet-actions"><button type="button" className="btn primary" disabled={busy || !setups?.length} onClick={() => void create()}>{busy ? '创建中…' : '创建插件'}</button><button type="button" className="btn" disabled={busy} onClick={onClose}>取消</button></div>
  </Sheet>;
}
