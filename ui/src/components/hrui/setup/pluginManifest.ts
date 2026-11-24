// A plugin package's manifest, read in the browser before anything is sent (SetupSettings'
// installFolder). A malformed plugin.json is refused with the parser's own message after the fixed
// sentence, so two different mistakes read differently, and the parser's error stays as the cause.
export const NOT_JSON = 'Its plugin.json is not valid JSON.';

/** Parse a picked package's plugin.json, or throw `NOT_JSON` followed by the parser's message. */
export function parsePluginManifest<T>(content: string): T {
  try {
    return JSON.parse(content) as T;
  } catch (error) {
    const why = error instanceof Error ? error.message : String(error);
    throw new Error(`${NOT_JSON} ${why}`, { cause: error });
  }
}
