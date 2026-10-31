// The blocks a person copies to their coding agent (Richard, 10-18): each carries the guide, says how
// the app connects so a coding agent reading only the block has the whole picture, and has no
// licensing line. Their API facts are the gateway's own: no field it does not read. Every one asks
// for the key the same way, and none keeps a key the app already has (Richard, 10-18: every sheet
// makes a new key and the person pastes it). Each takes the "Set up a starter app" design's form
// (Richard, 10-19): a goal, numbered steps with the key one of them in the design's words, then the
// context.
import { API_BASE, CODERS, GUIDE, KEY_STEP, handPrompt, promptText, setupPrompt, starterPrompt, type SetupRef } from './prompts';

const A: SetupRef = { id: 'chrn_0123456789', name: 'Support replies', harness: 'hermes', model: 'gpt-5.4', instr: 'Answer customer questions from the help center.' };
const OWN_APP: [string, string][] = [
  ['Start in your codebase', handPrompt()],
  ['Migrate an existing agent', setupPrompt()],
  ['Connect your app', promptText(A)],
];
// a kit's own setup: the one launching the kit made in the workspace
const K: SetupRef = { id: 'chrn_kit0123456789', name: 'Super Mario', harness: 'System One', model: 'jev-1.13', instr: '' };
const KITS: [string, string, string][] = [['mario', 'kits/mario', 'Super Mario'], ['dashboard', 'kits/dashboard', 'Dashboards'], ['sheets', 'kits/sheets', 'Sheets'], ['harness-bot', 'kits/harness-bot', 'Harness Bot'], ['video', 'kits/video', 'Video'], ['slides', 'kits/slides', 'Slides']];
const KIT_TEXTS: [string, string][] = KITS.map(([k, f, t]) => [`Make the ${k} kit yours`, starterPrompt(K, f, t)]);
const KIT: [string, string] = KIT_TEXTS[1];
const PROMPTS = [...OWN_APP, ...KIT_TEXTS];
const ALL = PROMPTS;

describe.each(ALL)('%s', (_name, text) => {
  it('carries the guide', () => { expect(text).toContain(GUIDE); });
  it('has no licensing line', () => { expect(text).not.toMatch(/licens|\bMIT\b|commercial/i); });
  it('names no field the gateway does not read', () => { expect(text).not.toMatch(/user_id|metadata\.purpose|setup_check/); });
  it('has no dashes as punctuation', () => {
    expect(text).not.toMatch(/[—–]/);
    expect(text).not.toMatch(/ - |^- /m);
  });
  it('names nothing internal', () => { expect(text).not.toMatch(/vectorgraph|gremlin|cosmos|azure|\bACA\b|tenant|vault|blob/i); });
  it('names no hosted service: the API is this instance\u2019s own', () => {
    expect(text).not.toMatch(/HarnessRouter Cloud|api\.harnessrouter\.ai|credits/);
  });
  it('ends no line in a space', () => { expect(text).not.toMatch(/ \n/); });
});

describe.each(PROMPTS)('%s asks for the key the one way', (_name, text) => {
  it('carries the key step once, as a step of its own', () => {
    expect(text.split(KEY_STEP).length - 1).toBe(1);
    expect(text).toMatch(new RegExp('^(\\d+|[a-z])\\. ' + KEY_STEP.slice(0, 40), 'm'));
  });
  it('asks for it in a secure prompt, in the design’s words, and replaces a key already set', () => {
    expect(text).toContain('Open a secure secret prompt and ask me for my HarnessRouter API key. Store it as HR_API_KEY in my backend environment');
    expect(text).toContain('replacing the existing value if there is one (any key of this workspace works for every setup in it).');
    expect(text).toContain('Never ask me to paste it into this chat. Never print, log or commit it, and never send it to the browser.');
  });
  it('carries no key and no stand-in for one', () => {
    expect(text).not.toMatch(/sk-hr-|YOUR_API_KEY|<api key>/i);
  });
  it('never keeps a key the app already has', () => {
    expect(text).not.toMatch(/do not create a new key/i);
    expect(text).not.toMatch(/reuse (that client and )?the same HR_API_KEY/i);
    expect(text).not.toMatch(/HR_API_KEY already in/i);
    expect(text).not.toMatch(/before you (build|change anything), open a secure/);
  });
});

// Richard, 10-18: every setup gets the one prompt, an app that already calls another setup included
it('Connect your app reuses a client the backend already has, with this setup’s own Harness ID', () => {
  const text = promptText(A);
  expect(text).toContain('If my backend already has a HarnessRouter client, reuse it for this feature.');
  expect(text).not.toMatch(/already calls HarnessRouter for/);
});

// Richard, 10-19: the design's form, a goal line, numbered steps, then the context they point to
describe.each(ALL)('%s takes the design’s form', (_name, text) => {
  it('opens with its goal, not a step, then numbered steps from 1', () => {
    const first = text.split('\n')[0];
    expect(first).not.toMatch(/^\d+\./);
    expect(first.length).toBeGreaterThan(20);
    expect(text).toMatch(/\n\n1\. Read the setup guide first: /);
    const nums = (text.match(/^\d+(?=\. )/gm) || []).map(Number);
    expect(nums).toEqual(nums.map((_, i) => i + 1));
  });
  it('ends with its context, after the steps', () => {
    const last = Math.max(...Array.from(text.matchAll(/^\d+\. /gm)).map((m) => m.index || 0));
    expect(text.indexOf('How it connects', last)).toBeGreaterThan(last);
  });
});

it('every block that adds the integration ends its steps by checking it with a real request', () => {
  for (const [, t] of OWN_APP) expect(t).toMatch(/\d\. Verify: send one real request/);
  for (const [, t] of KIT_TEXTS) expect(t).toContain('Verify: run one task in the app on my host and confirm a result comes back.');
});

it('a setup with no instructions says nothing about what it does', () => {
  expect(promptText({ ...A, instr: '' })).not.toContain('What it does');
  expect(promptText(A)).toContain('What it does (already set in the setup, for context only): ' + A.instr);
});

it('no coding agent is opened with the prompt: the agents are names and marks only', () => {
  for (const c of CODERS) expect(Object.keys(c).sort()).toEqual(['logo', 'name']);
});

describe.each(OWN_APP)('%s says how the app connects', (_name, text) => {
  it('keeps the key in the backend and the browser on the backend', () => {
    expect(text).toContain('My frontend talks only to my backend. It never calls HarnessRouter and never sees the key.');
    expect(text).toContain('POST ' + API_BASE + '/v1/responses');
    expect(text).toContain('HR_API_KEY from its own environment');
  });
  it('one task per request, follow-ups by previous_response_id', () => {
    expect(text).toContain('One user request is one task');
    expect(text).toContain('previous_response_id');
  });
  it('where results and files come back', () => {
    expect(text).toContain('GET /v1/responses/{id}');
    expect(text).toContain('download_url');
    expect(text).toContain('GET /v1/sessions/{session_id}/files');
  });
});

it('a setup the prompt knows is named by its Harness ID', () => {
  expect(promptText(A)).toContain('metadata.harness_id is "' + A.id + '"');
});

it('a kit app, as HarnessRouter serves it, connects through the console with no key', () => {
  const [, text] = KIT;
  const served = text.slice(text.indexOf('How it connects as HarnessRouter serves it (the default)'));
  expect(served).toContain('/kits/dashboard on the same origin as the console');
  expect(served).toContain('needs no API key and no login of its own');
  expect(served).not.toContain(API_BASE);
  expect(served).not.toContain('HR_API_KEY');
});

// Richard, 10-18: every block shown for a setup names it, a kit's setup included (launching a kit
// makes one), and says each request carries that Harness ID, never another setup's.
describe('every block shown for a setup names it', () => {
  it.each([
    ['Connect your app', promptText(A), A],
    ...KIT_TEXTS.map(([n, t]) => [n, t, K] as [string, string, SetupRef]),
  ])('%s contains the Harness ID it was given', (_n, text, s) => {
    expect(text).toContain(s.id);
  });
  it.each([
    ['Connect your app', promptText(A), A],
    ...KIT_TEXTS.map(([n, t]) => [n, t, K] as [string, string, SetupRef]),
  ])('%s names it in the setup block', (_n, text, s) => {
    expect(text).toContain('Harness ID: ' + s.id + '\nAgent harness: ' + s.harness + '\nModel: ' + s.model);
  });
  it.each(OWN_APP)('%s: each request carries the setup\u2019s own Harness ID, never another setup\u2019s', (_n, text) => {
    expect(text).toMatch(/metadata\.harness_id is .+ on every request the feature sends, never another setup\u2019s\./);
  });
  it('a setup with no model of its own says nothing about one', () => {
    expect(promptText({ ...A, model: '' })).not.toContain('Model:');
    expect(starterPrompt({ ...K, model: '' }, 'kits/mario')).not.toContain('Model:');
  });
});

describe.each(KIT_TEXTS)('%s: the kit\u2019s own setup', (_n, text) => {
  it('is the one the app is already connected to, and every change keeps calling it', () => {
    expect(text).toContain('The app is already connected to Harness ID ' + K.id + '.');
    expect(text).toContain('metadata.harness_id on every request to POST /api/harness/v1/responses');
    expect(text).toContain('Every change must keep calling this setup');
    expect(text).toContain('never write another setup\u2019s Harness ID into the app');
  });
  it('says the id is found, not configured', () => {
    expect(text).toContain('The id is not written in the app\u2019s code or in any config file');
  });
  it('says an image the person builds has a setup of its own', () => {
    expect(text).toContain('launching the kit there makes a setup there with a Harness ID of its own');
  });
});

it('a kit whose app also calls other setups says which', () => {
  const by = Object.fromEntries(KIT_TEXTS.map(([n, t]) => [n, t]));
  expect(by['Make the sheets kit yours']).toContain('an agent column runs the other setup its column names');
  expect(by['Make the harness-bot kit yours']).toContain('each teammate is a setup of its own');
  expect(by['Make the mario kit yours']).not.toContain('One exception');
  expect(by['Make the mario kit yours']).toContain('kit id "mario"');
});

// A changed kit app on the person's own host keeps calling this setup through a backend that holds
// the key (the backend path), and this instance's API is the one it calls.
describe.each(KIT_TEXTS)('%s: the backend path', (_n, text) => {
  const cloud = text.slice(text.indexOf('Backend path (recommended)'), text.indexOf('Image path:'));
  it('names the Harness ID and HR_API_KEY', () => {
    expect(cloud).toContain(K.id);
    expect(cloud).toContain('HR_API_KEY');
    expect(cloud).toContain('my changed app keeps calling Harness ID ' + K.id + ' on this HarnessRouter');
  });
  it('keeps the key in the backend, from a secure prompt', () => {
    expect(cloud).toContain('Open a secure secret prompt');
    expect(cloud).toContain('Never print, log or commit it, and never send it to the browser.');
  });
  it('the browser talks only to the backend, which calls the API with this setup', () => {
    expect(cloud).toContain('so the browser talks only to my backend');
    expect(cloud).toContain(API_BASE + '/v1/responses');
    expect(cloud).toContain('Authorization: Bearer <key>');
  });
  it('comes before the image path, which makes its own setup, and the default is said after both', () => {
    expect(text.indexOf('Backend path (recommended)')).toBeLessThan(text.indexOf('Image path:'));
    expect(text.indexOf('Image path:')).toBeLessThan(text.indexOf('(the default)'));
    expect(text.slice(text.indexOf('Image path:'), text.indexOf('(the default)'))).toContain('a Harness ID of its own');
  });
  it('letters its steps in order, the key one of them', () => {
    const letters = (cloud.match(/^[a-z](?=\. )/gm) || []).join('');
    expect(letters).toBe('abcdefghi');
    expect(cloud).toContain('b. ' + KEY_STEP);
  });
});

it('the backend path says what in each kit app changes', () => {
  const by = Object.fromEntries(KIT_TEXTS.map(([n, t]) => [n, t]));
  expect(by['Make the mario kit yours']).toContain('kits/mario/app, configureKit is called in src/lib/game.js');
  expect(by['Make the mario kit yours']).toContain('kitHarness() looks the setup up with GET {base}/harnesses');
  expect(by['Make the mario kit yours']).toContain('it sets metadata.harness_id to "' + K.id + '", whatever the browser sent');
  expect(by['Make the mario kit yours']).toContain(API_BASE + '/v1/harnesses/' + K.id);
  expect(by['Make the dashboard kit yours']).toContain('configureKit is called in src/lib/dash.js');
  expect(by['Make the sheets kit yours']).toContain('leaving out any other setup whose kit is "sheets"');
  expect(by['Make the harness-bot kit yours']).toContain('configureKit is called in src/App.jsx');
  const slides = starterPrompt(K, 'kits/slides', 'Slides');
  expect(slides).toContain('const API = "/api/harness/v1" in kits/slides/app/src/lib/sl.js');
  expect(slides).not.toContain('reifyui/harness');
  expect(starterPrompt(K, 'kits/video', 'Video')).toContain('src/lib/media.js has its own BASE');
});

it('the API every block names is this instance\u2019s own address, under /api/harness', () => {
  expect(API_BASE).toMatch(/^https?:\/\/[^/]+\/api\/harness$/);
  expect(handPrompt()).toContain('POST ' + API_BASE + '/v1/responses');
});
