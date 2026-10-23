// The plugin reads a page waits on go to the gateway's own routes and carry the read's signal, so a
// read that has no answer is cancelled at its end (lib/settle.ts) instead of holding a skeleton.
jest.mock('@/lib/harness', () => ({ gw: jest.fn(async () => ({})) }));

import { gw } from '@/lib/harness';
import { listPlugs, plugAttachments } from './plugs';

const call = gw as jest.Mock;

test('the catalog and who uses a plugin are read from /v1/plugs, with the signal', async () => {
  const ctl = new AbortController();
  await listPlugs(ctl.signal);
  expect(call).toHaveBeenLastCalledWith('GET', '/v1/plugs', undefined, ctl.signal);
  await plugAttachments('microsoft365', ctl.signal);
  expect(call).toHaveBeenLastCalledWith('GET', '/v1/plugs/microsoft365/attachments', undefined, ctl.signal);
});
