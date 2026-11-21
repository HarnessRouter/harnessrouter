// A picked package's plugin.json (issue #725): a malformed one is refused with the parser's own
// message after the fixed sentence, and the parser's error is the cause.
import { NOT_JSON, parsePluginManifest } from './pluginManifest';

const realParse = JSON.parse.bind(JSON);
afterEach(() => { jest.restoreAllMocks(); });

function refusalOf(content: string): { thrown: Error; caught: unknown } {
  let caught: unknown;
  jest.spyOn(JSON, 'parse').mockImplementationOnce((text: string) => {
    try { return realParse(text); } catch (e) { caught = e; throw e; }
  });
  try {
    parsePluginManifest(content);
  } catch (e) {
    return { thrown: e as Error, caught };
  }
  throw new Error('parsePluginManifest did not refuse');
}

test('the cause is the exact SyntaxError the parser threw', () => {
  const { thrown, caught } = refusalOf('{"name": "x"');
  expect(caught).toBeInstanceOf(SyntaxError);
  expect(thrown.cause).toBe(caught);
  expect(thrown.message).toBe(`${NOT_JSON} ${(caught as Error).message}`);
});

test('the fixed sentence is kept as it was, period included', () => {
  expect(NOT_JSON).toBe('Its plugin.json is not valid JSON.');
  const { thrown } = refusalOf('{"name": "x",}');
  expect(thrown.message.startsWith('Its plugin.json is not valid JSON. ')).toBe(true);
});

test('two different malformations read differently', () => {
  expect(refusalOf('{"name": "x"').thrown.message).not.toBe(refusalOf('{"name": "x",}').thrown.message);
});

test('a valid manifest comes back as it was written', () => {
  expect(parsePluginManifest<{ name: string; version: string }>('{"name":"demo-kit","version":"1.0.0"}'))
    .toEqual({ name: 'demo-kit', version: '1.0.0' });
});
