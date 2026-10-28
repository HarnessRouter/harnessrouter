/** @jest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

jest.mock('react-markdown', () => ({ __esModule: true, default: () => null }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => null }));
jest.mock('rehype-sanitize', () => ({ __esModule: true, default: () => null }));
jest.mock('reifyui/agent-chat', () => ({
  FileCard: ({ name }: { name: string }) => <div className="uic-filecard">{name}</div>,
  ArtifactPanel: () => null,
  AgentConversation: ({ children, composer }: { children?: React.ReactNode; composer?: React.ReactNode }) =>
    <div>{children}{composer}</div>,
  AgentComposer: () => null,
  AgentTurnView: ({ renderFiles }: { renderFiles?: () => React.ReactNode }) =>
    <div className="mock-turn">{renderFiles?.()}</div>,
  turnFromMessage: (m: { status?: string }) => ({ status: m.status || 'done', items: [] }),
  motionFor: () => '',
}), { virtual: true });

jest.mock('@/lib/chat', () => ({
  authHeaders: () => ({}),
  containerFileUrl: (f: { container_id: string; file_id: string; url?: string }) =>
    f.url || `/api/harness/v1/containers/${f.container_id}/files/${f.file_id}/content`,
  downloadFile: jest.fn(),
  fetchFileBlob: jest.fn(() => Promise.reject(new Error('no thumbnail'))),
  loadSessionTurns: jest.fn(async () => ({ turns: [] })),
}));
jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('@/lib/conversation', () => {
  const React = jest.requireActual('react') as typeof import('react');
  return {
    isInternalOutput: (n?: string) => n === 'AGENTS.md',
    useHarnessBus: () => {},
    useConversationTurn: () => {
      const [msgs, setMsgs] = React.useState(mockState.initial);
      mockState.setMsgs = setMsgs;
      return {
        msgs, busy: false, stopping: false, liveSessionId: '',
        send: jest.fn(async () => true), replay: jest.fn(() => () => {}),
        stop: () => {}, setMsgs, loadFailed: false, reload: () => {},
      };
    },
  };
});
jest.mock('@/lib/harness', () => ({
  ...jest.requireActual('@/lib/harness'),
  useModelCatalogRead: () => mockState.catalog,
  oobModels: () => ['gpt-5.4'],
  oobDefaultModel: () => 'gpt-5.4',
  modelAvailability: () => 'yes',
}));
jest.mock('@/lib/providers', () => ({
  providerById: () => null,
  useModelProviders: () => ({ connectionFor: () => null }),
}));
jest.mock('../toast', () => ({ toast: jest.fn() }));
jest.mock('../Skel', () => ({ Skel: () => null, SkLine: () => null, SkThread: () => null }));
jest.mock('../start/prompts', () => ({ API_BASE: 'https://box.example/api/harness' }));
jest.mock('../start/fork', () => ({
  inputHistory: async () => false, forkOffered: () => true, forkFiles: jest.fn(async () => []),
  forkInput: () => [], importedFirst: () => true, noteFork: jest.fn(),
}));
jest.mock('./TaskThread', () => ({ Md: () => null }));
jest.mock('@/components/HarnessLogo', () => ({ harnessLogoSrc: () => '' }));

import type { CustomHarness, ModelCatalog } from '@/lib/harness';
import type { Msg } from '@/lib/conversation';
import { rowOf } from '../setups';
import { Playground } from './Playground';

const mockState: {
  initial: Msg[];
  setMsgs?: (msgs: Msg[]) => void;
  catalog: { value: ModelCatalog | null; failed: boolean; retry: jest.Mock };
} = {
  initial: [],
  catalog: {
    value: { hermes: { default: 'gpt-5.4', models: ['gpt-5.4'], unavailable: [] } },
    failed: false,
    retry: jest.fn(),
  },
};

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const harness = {
  id: 'chrn_test', name: 'File test', base: 'hermes', defaultModel: 'gpt-5.4',
  systemPrompt: '', mcpServers: [], skills: [], createdAt: 1, source: 'test',
} as unknown as CustomHarness;

const initial: Msg[] = [
  { role: 'user', text: 'Create a report' },
  {
    role: 'assistant', blocks: [{ kind: 'text', text: 'Done.' }],
    files: [], status: 'done', elapsed: 12,
  },
];

let root: Root;
let el: HTMLElement;

beforeEach(() => {
  mockState.initial = initial;
  mockState.setMsgs = undefined;
  el = document.createElement('div');
  document.body.appendChild(el);
  root = createRoot(el);
});

afterEach(() => {
  act(() => root.unmount());
  el.remove();
});

test('a late produced file appears in the task UI without reloading', async () => {
  await act(async () => {
    root.render(
      <Playground
        r={rowOf(harness, 'Hermes', [], false)}
        onRan={() => {}}
        onBorn={() => {}}
        onPreview={() => {}}
        slot={{ key: 'file-test', resume: null, recorded: null }}
      />,
    );
  });

  expect(el.querySelector('.uic-filecard')).toBeNull();

  const setMsgs = mockState.setMsgs;
  expect(setMsgs).toBeDefined();

  await act(async () => {
    setMsgs?.([
      initial[0],
      {
        ...initial[1],
        role: 'assistant',
        files: [{
          container_id: 'hsess_test',
          file_id: 'file_report',
          filename: 'report.csv',
        }],
      } as Msg,
    ]);
  });

  expect(el.querySelector('.uic-filecard')?.textContent).toContain('report.csv');
});
