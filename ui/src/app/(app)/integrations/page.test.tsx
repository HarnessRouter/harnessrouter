/** @jest-environment jsdom */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Integrations from './page';
import { harnessFetch } from '@/lib/hfetch';

jest.mock('@/lib/hfetch', () => ({ harnessFetch: jest.fn() }));
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/lib/auth', () => ({ getSession: () => null }));
jest.mock('@/lib/chat', () => ({ authHeaders: () => ({}) }));
jest.mock('@/lib/edition', () => ({ SELF_HOSTED: true, PLATFORM_ADMIN_ORGS: [] }));

const doc = {
  integrations: [], model_map: {}, providers: ['custom'],
  catalog: [{ id: 'custom', label: 'Custom', base_url: null, secret: 'api_key',
    secret_label: 'API key', fields: [{ key: 'api_format', label: 'API format' }],
    models: [], canonicals: ['catalog-model'], backends: ['pi', 'codex'],
    format_backends: { openai: ['pi'], responses: ['codex'], anthropic: ['claude'] } }],
};

beforeEach(() => {
  jest.clearAllMocks();
  (harnessFetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => doc });
});

async function openCustom() {
  render(<Integrations />);
  await waitFor(() => expect(harnessFetch).toHaveBeenCalled());
  fireEvent.click(screen.getByText('Add Integration'));
  fireEvent.click(await screen.findByRole('button', { name: 'Custom' }));
}

test('saves arbitrary ids and wire-only rows, skipping empty rows', async () => {
  await openCustom();
  fireEvent.change(screen.getByLabelText('Name', { exact: true }), { target: { value: 'proxy' } });
  fireEvent.click(screen.getByText('Add model'));
  fireEvent.change(screen.getByLabelText('Model', { exact: true }), { target: { value: 'gpt-4.1-mini' } });
  expect(screen.getByLabelText('Model').tagName).toBe('INPUT');
  expect(document.querySelector('#custom-model-ids option')?.getAttribute('value')).toBe('catalog-model');
  fireEvent.click(screen.getByText('Add model'));
  fireEvent.change(screen.getAllByLabelText('Name on the wire')[1], { target: { value: 'wire-only-model' } });
  fireEvent.click(screen.getByText('Add model'));
  fireEvent.click(screen.getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(harnessFetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ method: 'PUT' })));
  const put = (harnessFetch as jest.Mock).mock.calls.find(([, opts]) => opts?.method === 'PUT');
  expect(JSON.parse(put![1].body).integrations[0].models).toEqual([
    { canonical: 'gpt-4.1-mini', provider_id: '' },
    { canonical: 'wire-only-model', provider_id: 'wire-only-model' },
  ]);
});

test('updates compatible bases from metadata when the format changes', async () => {
  await openCustom();
  expect(screen.getByText(/Compatible harness bases: pi\./)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('API format'), { target: { value: 'responses' } });
  expect(screen.getByText(/Compatible harness bases: codex\./)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('API format'), { target: { value: 'anthropic' } });
  expect(screen.getByText(/Compatible harness bases: claude\./)).toBeTruthy();
});
