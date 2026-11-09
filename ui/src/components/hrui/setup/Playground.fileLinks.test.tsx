/** @jest-environment jsdom */
// #594: a reply's link to a file of its task opens the file beside the conversation, read with the
// sign-in, the way the file's card does, whether or not the task is shared. Md hands the clicked path
// up; the page opens the file the conversation made by its id, and any other path of the task through
// the signed-in read by path.
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { CustomHarness, ModelCatalog } from '@/lib/harness';

const FILE = { container_id: 'hsess_1', file_id: 'cfile_1', filename: 'out/hello-world.pptx' };
const MSGS = [
  { role: 'user', text: 'Build a one-slide deck and give me a download link.' },
  { role: 'assistant', blocks: [{ kind: 'text', text: '[Download hello-world.pptx](hello-world.pptx)' }], files: [FILE], status: 'done' },
];
jest.mock('@/lib/conversation', () => ({
  isInternalOutput: () => false,
  useHarnessBus: () => {},
  useConversationTurn: () => ({
    msgs: MSGS, busy: false, stopping: false, liveSessionId: 'hsess_1',
    send: () => Promise.resolve(true), stop: () => {}, setMsgs: () => {}, loadFailed: false, reload: () => {},
  }),
}));
jest.mock('@/lib/chat', () => ({
  loadSessionTurns: jest.fn(async () => ({ turns: [] })),
  containerFileUrl: (f: { container_id: string; file_id: string; url?: string }) => f.url || `/api/harness/v1/containers/${f.container_id}/files/${f.file_id}/content`,
  authHeaders: () => ({}), downloadFile: jest.fn(), fetchFileBlob: jest.fn(),
}));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })) }));
const CAT: ModelCatalog = { hermes: { default: 'gpt-5.4', models: ['gpt-5.4'], unavailable: [] } } as unknown as ModelCatalog;
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => ({ value: CAT, failed: false, retry: jest.fn() }),
  oobModels: () => ['gpt-5.4'], oobDefaultModel: () => 'gpt-5.4', modelAvailability: () => 'yes',
}));
jest.mock('@/lib/providers', () => ({ providerById: () => null, useModelProviders: () => ({ connectionFor: () => null }) }));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
jest.mock('react-markdown', () => ({ __esModule: true, default: () => null }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => null }));
jest.mock('rehype-sanitize', () => ({ __esModule: true, default: () => null }));
// what the page hands Md, for each reply it draws
const mockMd: { sid?: string; harnessId?: string; produced?: string[]; onOpen?: (path: string) => void }[] = [];
jest.mock('./TaskThread', () => ({ Md: (p: never) => { mockMd.push(p); return null; } }));
jest.mock('next/link', () => ({ __esModule: true, default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a> }));
jest.mock('./AgentTurns', () => ({
  AgentTurns: ({ msgs, md }: { msgs: { role: string; blocks?: { text: string }[] }[]; md: (t: string) => ReactNode }) => (
    <div>{msgs.filter((m) => m.role === 'assistant').map((m, i) => <div key={i}>{md(m.blocks?.[0]?.text || '')}</div>)}</div>
  ),
  harnessMark: () => ({ mark: null, motion: null }),
}));
jest.mock('../start/build', () => ({ useBuildOf: () => null, noteFirstSid: jest.fn(), retryBuild: jest.fn() }));
jest.mock('reifyui/agent-chat', () => ({
  AgentConversation: ({ children, composer }: { children?: ReactNode; composer?: ReactNode }) => <div>{children}{composer}</div>,
  AgentComposer: () => <div className="composer" />,
  ArtifactPanel: () => null, FileCard: () => null,
}), { virtual: true });

import { rowOf } from '../setups';
import { Playground } from './Playground';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const H = { id: 'chrn_t', name: 'Decks', base: 'hermes', defaultModel: 'gpt-5.4', systemPrompt: '', mcpServers: [], skills: [], createdAt: 1 } as unknown as CustomHarness;
let root: Root; let el: HTMLElement;
const flush = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
beforeEach(() => { mockMd.length = 0; el = document.createElement('div'); el.id = 'hrui'; document.body.appendChild(el); root = createRoot(el); });
afterEach(() => { act(() => root.unmount()); el.remove(); });

async function open(onPreview: jest.Mock) {
  await act(async () => {
    root.render(<Playground r={rowOf(H, 'Hermes', [], false)} onRan={() => {}} onBorn={() => {}} onPreview={onPreview} slot={{ key: 'k', resume: 'hsess_1' }} />);
  });
  await flush();
  const last = mockMd[mockMd.length - 1];
  expect(last).toBeTruthy();
  return last;
}

test("a reply's link to a file it made opens that file's preview, read by its id with the sign-in", async () => {
  const onPreview = jest.fn();
  const md = await open(onPreview);
  expect(md.sid).toBe('hsess_1');
  expect(md.harnessId).toBe('chrn_t');
  expect(md.produced).toEqual(['out/hello-world.pptx']);
  act(() => md.onOpen?.('out/hello-world.pptx'));
  expect(onPreview).toHaveBeenCalledTimes(1);
  const [files, key] = onPreview.mock.calls[0];
  expect(key).toBe('cfile_1');
  expect(files).toEqual([expect.objectContaining({ key: 'cfile_1', name: 'hello-world.pptx',
    url: '/api/harness/v1/containers/hsess_1/files/cfile_1/content' })]);
});

test('a link to another file of the task opens it by its path through the signed-in read, never the public one', async () => {
  const onPreview = jest.fn();
  const md = await open(onPreview);
  act(() => md.onOpen?.('site/index.html'));
  const [files, key] = onPreview.mock.calls[0];
  expect(key).toBe('path:site/index.html');
  const shown = files.find((f: { key: string }) => f.key === key);
  expect(shown.url).toBe('/api/harness/a/hsess_1/site/index.html');
  expect(shown.url).not.toContain('/workspace/');
});
