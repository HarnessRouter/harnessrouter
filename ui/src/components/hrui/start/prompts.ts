// The text a person hands their coding agent (docs/uxuidesign/console-79: handPrompt, setupPrompt,
// starterPrompt, promptText). None of it carries a key: every prompt has the coding agent
// ask for the key in its own secure prompt.
//
// Where it differs from the design, on purpose:
// - The guide is named at harnessrouter.ai/agents.md, where it is public (the design's GitHub
//   address, HarnessRouter/harnessrouter/blob/main/AGENTS.md, is not published), and every block
//   carries it.
// - Every block is whole by itself (Richard, 10-18): a coding agent that reads only the block learns
//   how the person's frontend, backend and HarnessRouter fit (howItConnects), each line true of the
//   gateway today: POST /v1/responses with metadata.harness_id and previous_response_id, stream or
//   background with GET /v1/responses/{id}, a finished turn's files as container_file_citation
//   annotations (filename, download_url), GET /v1/sessions/{session_id}/files, and the response's
//   metadata.session_id. The design's metadata.user_id and metadata.purpose are left out: the
//   gateway reads neither, and request metadata is not echoed, so "their tasks can be found later"
//   was not true. The app keeps each task's ids with its own user instead.
// - No licensing line (Richard, 10-18): the kits' license holds by default, and the line confused
//   coding agents.
// - The API is this instance's own: the console's address under /api/harness, where a request that
//   carries an API key as its bearer goes straight through to the API (API_BASE).
// - Every block shown for a setup names it (Richard, 10-18): its Harness ID, agent harness and model
//   (setupLines), and says each request carries that Harness ID and never another setup's. A kit's
//   setup is a setup like any other (launching a kit makes one in the workspace), so the kit's block
//   names it too, and says how the kit's app already reaches it.
// - Every block asks for the key the same way (KEY_STEP; Richard, 10-18: every sheet makes a new
//   key, named, shown once, pasted). None tells the coding agent to keep a key it already has: the
//   person makes a new one in the sheet and pastes it, and it replaces any HR_API_KEY already set,
//   which is safe because any key of the workspace reaches every setup in it.
// - Every block takes the form of Richard's "Set up a starter app" design (10-19): a goal, numbered
//   steps (the key one of them, in the design's words), then the context the steps point to (how it
//   connects, where instructions live). Its prompt clones a starter app the repository does not have,
//   so the blocks keep their own steps (10-19: "No new app"); none lost a fact to the new form.

export const GUIDE = 'https://harnessrouter.ai/agents.md';
/** This instance's API, as an app outside the console reaches it: the console's own address under
 *  /api/harness (a request with an API key as its bearer goes straight through to the API). */
export const API_BASE = (typeof window !== 'undefined' && window.location?.origin ? window.location.origin : 'http://localhost:3000') + '/api/harness';
/** The public starter-kit repository: kits/ holds the kits' own apps. */
export const STARTER_REPO = 'https://github.com/HarnessRouter/starter-kit';
/** The kits whose app is in the starter-kit repository (the design's repoUrl list, which matches
 *  the repository's kits/ folder). */
const STARTER_KITS = /^(dashboard|video|mario|workplace|slides|sheets)$/;
/** The folder of a kit's app in the starter-kit repository, or '' when the kit has none there. */
export const starterFolder = (kit: string | undefined | null): string => (kit && STARTER_KITS.test(kit) ? `kits/${kit}` : '');

const HR_FILE = 'harnessrouter.json';
export const INSTR_RULE = 'Instructions are stored in the HarnessRouter setup, not in my app’s code or sent with every task. Keep a copy of the setup in my repo as ' + HR_FILE + ' (harness_id, name, base, model, instructions). To change it later, fetch the live setup first (it may have been edited in HarnessRouter), update ' + HR_FILE + ', then apply it with the HarnessRouter API.';
const GUIDE_STEP = 'Read the setup guide first: ' + GUIDE + ' (if you cannot open links, ask me to paste it).';
const NEW_OR_EXISTING = 'If this folder already has an app, add the feature there and keep its design and architecture. If it is empty, create a small web app for it first, and ask me which stack if it is unclear.';
/** How every block asks for the key, as one of its steps: the person makes a new one in the sheet's
 *  key step and pastes it into the coding agent's secure prompt. */
export const KEY_STEP = 'Open a secure secret prompt and ask me for my HarnessRouter API key. Store it as HR_API_KEY in my backend environment, replacing the existing value if there is one (any key of this workspace works for every setup in it). Never ask me to paste it into this chat. Never print, log or commit it, and never send it to the browser.';
/** Every block that adds the integration checks it the same way. */
const VERIFY = 'Verify: send one real request through my app’s own code path and confirm a result comes back.';

/** The migration line the person sends after the prompt: step 2 of the migration guide. */
export const MOVE_LINE = 'Migrate my current agent backend to HarnessRouter.';
/** Example answers that take turns under step 2 of the setup guide. */
export const HX_SAMPLES = ['Build a site generator agent product with user-facing UI.', 'Build a contract review agent product with user-facing UI.', 'Build a support reply agent product with user-facing UI.'];

/** How the person's app reaches HarnessRouter, in a few lines a coding agent can act on. `hid` is the
 *  Harness ID when the prompt knows it; otherwise the one the coding agent creates. */
function howItConnects(hid: string): string {
  return 'How it connects:\n' +
    'My frontend talks only to my backend. It never calls HarnessRouter and never sees the key.\n' +
    'My backend calls POST ' + API_BASE + '/v1/responses, sending HR_API_KEY from its own environment as Authorization: Bearer <key>.\n' +
    'One user request is one task: input is what my user typed, and metadata.harness_id is ' + (hid ? '"' + hid + '"' : 'the Harness ID of the feature’s own setup') + ' on every request the feature sends, never another setup’s. My backend sets the Harness ID; never take it from the browser.\n' +
    'Send previous_response_id, the id of the response it continues, only when my user follows up on the same result. Otherwise start a new task: a follow-up carries the earlier context and costs more.\n' +
    'A task can take minutes. Send stream: true and pass its events to my frontend as progress, or send background: true and poll GET /v1/responses/{id} until its status is completed, failed, incomplete or cancelled.\n' +
    'The finished response’s output holds the answer text, with each file the agent made as an annotation carrying its filename and download_url. GET /v1/sessions/{session_id}/files lists all of the task’s files (session_id is in the response’s metadata). My backend downloads them with the key and serves them to my frontend.\n' +
    'Save each task’s response id and session_id with my user’s own record, so my app can show their tasks and continue them.';
}

/** The setup guide's prompt: build a new agent feature in your app. */
export function handPrompt(): string {
  const hm = 'Agent harness: the one the guide recommends for this job. Model: the one the guide recommends.';
  return 'Build an agent-powered feature with HarnessRouter as its agent backend.\n' +
    'Start by asking me: What do you want to ship to your users? Ask me if anything else is unclear.\n\n' +
    '1. ' + GUIDE_STEP + '\n' +
    '2. ' + KEY_STEP + '\n' +
    '3. Build the feature in my app. ' + NEW_OR_EXISTING + ' Then add the HarnessRouter integration.\n' +
    '4. Create one `harness` resource through the HarnessRouter API. Set its `base` to the selected agent harness, then configure its model and instructions. ' + hm + ' Give it a clear name and the feature’s standing instructions. If one with that name already exists in my workspace, reuse it.\n' +
    '5. Call it from my backend as How it connects says below.\n' +
    '6. ' + VERIFY + '\n' +
    '7. Tell me its Harness ID.\n\n' + howItConnects('') + '\n\n' + INSTR_RULE;
}

/** The migration guide's prompt: move existing agents to HarnessRouter. */
export function setupPrompt(): string {
  return 'Help me move my existing agents to HarnessRouter, whether they run on a managed agent service or in my own code (an agent loop, framework or SDK). Keep my app’s behavior, UI and architecture.\n\n' +
    '1. ' + GUIDE_STEP + ' Then wait for me to say: ' + MOVE_LINE + '\n' +
    '2. ' + KEY_STEP + '\n' +
    '3. Find each agent my app runs, on a service or in my own code, and every place my backend calls it. Each one becomes one HarnessRouter setup (one `harness` resource) with the same instructions and tools.\n' +
    '4. For each feature, create one `harness` resource through the HarnessRouter API. Set its `base` to the agent harness that fits (see the guide), then configure its model and instructions: a clear name, the model that fits, and the feature’s standing instructions. If one with that name already exists in my workspace, reuse it and do not change its settings.\n' +
    '5. Replace the old call as How it connects says below, each feature with its own Harness ID.\n' +
    '6. Verify: send one real request per feature through my app’s own code path and confirm a result comes back.\n' +
    '7. Tell me which setups you created and their Harness IDs.\n\n' + howItConnects('') + '\n\n' + INSTR_RULE;
}

/** What a prompt needs to know about the setup it is for. */
export interface SetupRef { id: string; name: string; harness: string; model: string; instr: string }

/** The setup, as every block names it. A setup with no model of its own says nothing about one
 *  rather than guess. */
function setupLines(a: SetupRef): string {
  return 'Harness ID: ' + a.id + '\nAgent harness: ' + a.harness + (a.model ? '\nModel: ' + a.model : '');
}

/** The HarnessRouter repository: its image builds the kits' apps and serves them. */
export const OSS_REPO = 'https://github.com/HarnessRouter/harnessrouter';
/** The kits whose app has tests (`npm test` in its package.json). */
const KIT_TESTS = /^(dashboard|video|workplace|sheets)$/;

/** The kits whose app also calls setups other than the kit's own, as their READMEs and code say:
 *  a Sheets agent column runs the setup the column names (the app refuses the sheet's own), and a
 *  Workplace teammate is a setup the app creates and calls by the teammate's own id. */
const KIT_OTHERS: Record<string, string> = {
  sheets: 'One exception: an agent column runs the other setup its column names, never this one (the app refuses that).',
  workplace: 'One exception: each teammate is a setup of its own that the app creates, and the app calls a teammate with that teammate’s own Harness ID.',
};

/** Where each kit's app sets the address its calls go to, read from the starter-kit repository
 *  (a58e8a6, 2026-10-18) and the reifyui versions its kits lock (0.8.3, 0.11.2, 0.13.7, the same
 *  transport in each): configureKit({ kitId, base }) keeps a base (default /api/harness/v1, kept by a
 *  later call that gives none), every call goes to `${base}${path}`, kitHarness() picks the first of
 *  GET {base}/harnesses whose `kit` is the kit id, and streamTurn() POSTs {base}/responses with that
 *  id as metadata.harness_id. Video builds media addresses from its own BASE; Slides does not use
 *  reifyui/harness for calls at all (its own API constant and slidesHarness). */
const KIT_WIRING: Record<string, string> = {
  mario: 'configureKit is called in src/lib/game.js (give the first call the base; the second call keeps it).',
  dashboard: 'configureKit is called in src/lib/dash.js.',
  sheets: 'configureKit is called in src/lib/sh.js.',
  video: 'configureKit is called in src/lib/video.js, and src/lib/media.js has its own BASE "/api/harness/v1" for media addresses: change both.',
  workplace: 'configureKit is called in src/App.jsx.',
};

/** The backend path's step that points the app at the person's backend: what in the app changes. */
function pointAtBackend(kit: string, app: string): string {
  if (kit === 'slides') {
    return 'Point the app at my backend. This app makes its own calls: const API = "/api/harness/v1" in ' + app + '/src/lib/sl.js and in ' + app + '/src/lib/copilot.js sets where they go, slidesHarness() in sl.js looks the setup up with GET {API}/harnesses, and copilot.js sends POST {API}/responses with that setup’s id as metadata.harness_id. Set API in both files to a path on my backend, such as /api/hr, so the browser talks only to my backend.';
  }
  return 'Point the app at my backend. Every call the app makes goes through reifyui/harness: configureKit({ kitId, base }) sets where calls go (base is /api/harness/v1 on the same origin until it is set), kitHarness() looks the setup up with GET {base}/harnesses, and streamTurn() sends POST {base}/responses with that setup’s id as metadata.harness_id. In ' + app + ', ' + (KIT_WIRING[kit] || 'find where configureKit is called.') + ' Set base to a path on my backend, such as /api/hr, so the browser talks only to my backend.';
}

/** "Make <kit> yours": the coding agent takes the kit's app from the starter-kit repository, written
 *  from that repository's own READMEs (Richard: no step a coding agent cannot follow). Each kit's
 *  README: the app is served by HarnessRouter at /kits/<kit>, same-origin with the console, "which is
 *  why it needs no API key and no login of its own"; working on it is cd app, npm install, npm test,
 *  npm run build. Its kit.json: the image builds it with npm ci && npm run build and serves its dist
 *  at /kits/<kit>. The open-source image's Dockerfile builds the kits from HR_KITS_REPO at HR_KITS_REF.
 *
 *  `a` is the kit's own setup: the one launch made in this workspace, whose page or kit page the
 *  sheet opens from (Richard, 10-18: a kit's setup is a fork like any other, so its block names it).
 *  How the app reaches it, from the kits' code (github.com/HarnessRouter/starter-kit, kits/<kit>/app,
 *  and reifyui/harness's kitHarness and streamTurn): no Harness ID is written into the app or any
 *  config. At start it looks up the setup launched from its kit id in the active workspace (the
 *  harness list's `kit` field, or the kit catalog's harnessId for Workplace), and sends that setup's
 *  id as metadata.harness_id on POST /api/harness/v1/responses. Launch keeps one such setup per
 *  workspace, so in this workspace that is `a`.
 *
 *  The console serves only the kits' own apps (built from the starter-kit repository for the whole
 *  deployment), never a person's changed copy, so a changed app runs on the person's host, two ways:
 *  - The backend path (recommended): the person's backend holds a key and forwards the app's calls
 *    to the same paths under API_BASE/v1, this instance's API, with the key as a bearer (every one
 *    of those routes resolves an API key). It answers the app's setup lookup with this setup alone (GET
 *    /v1/harnesses/{id} carries `kit`) and pins metadata.harness_id on POST /responses, so the
 *    changed app keeps calling `a`. Sheets and Workplace call other setups by design, so there the
 *    list stays and an id the browser names is kept when the key reaches it. A kit's auth.js asks
 *    the console's own session routes who is signed in; those are not API routes.
 *  - The image path: an image built from the person's fork of the kits, run as a HarnessRouter of
 *    its own, where the kit launched gets a setup of its own, which the app finds the same way. */
export function starterPrompt(a: SetupRef, folder: string, title: string = a.name): string {
  const kit = folder.replace(/^kits\//, '');
  const app = folder + '/app';
  const others = !!KIT_OTHERS[kit];
  const pin = others
    ? 'The backend keeps this setup as the app’s own. This app also calls other setups (the exception above), so the backend answers GET /harnesses with the list from GET ' + API_BASE + '/v1/harnesses, leaving out any other setup whose kit is "' + kit + '", so the app’s lookup by kit id lands on this one. On POST /responses it keeps a Harness ID the browser names from that list, and sets metadata.harness_id to "' + a.id + '" when the browser names none.'
    : 'The backend carries the fixed Harness ID: it answers GET /harnesses with {"harnesses": [this setup]}, read from GET ' + API_BASE + '/v1/harnesses/' + a.id + ', so the app’s lookup by kit id lands on it, and on every POST /responses it sets metadata.harness_id to "' + a.id + '", whatever the browser sent.';
  const cloud = [
    'Add a small backend that serves the app.',
    KEY_STEP,
    pointAtBackend(kit, app),
    'The backend forwards each call the app makes to the same path under ' + API_BASE + '/v1 (for example POST /api/hr/responses goes to POST ' + API_BASE + '/v1/responses), sending HR_API_KEY as Authorization: Bearer <key>, and passes a streamed reply through as it arrives. Forward only the paths the app calls.',
    pin,
    app + '/src/lib/auth.js asks the console who is signed in. That is a console page, not part of the API: answer it from my backend for my own signed in user, or the app runs with nobody signed in.',
    'Anyone who can open the app can run tasks on my provider keys through the backend, so put my own sign in in front of it before I share the address.',
    'The build expects to be served under /kits/' + kit + '/ (the base in vite.config.js). Serve it there, or change that base.',
    'Verify: run one task in the app on my host and confirm a result comes back.',
  ].map((t, i) => String.fromCharCode(97 + i) + '. ' + t).join('\n');
  return 'Make the ' + title + ' starter kit app my own. It runs on this setup in my HarnessRouter workspace, launched from the kit:\n' +
    setupLines(a) + '\n\n' +
    '1. ' + GUIDE_STEP + ' Where it describes a backend with an API key, that is the backend path below; as HarnessRouter serves the app, it needs neither.\n' +
    '2. Clone ' + STARTER_REPO + ' and open ' + folder + '. Read its README.md first: kit.json names the agent the kit needs and where its app is served, and the app itself is in ' + app + '.\n' +
    '3. Work on the app: cd ' + app + ', then npm install' + (KIT_TESTS.test(kit) ? ', npm test' : '') + ' and npm run build. Every change must keep calling this setup: keep the kit id "' + kit + '" and its lookup (How it connects, below), and never write another setup’s Harness ID into the app.' + (others ? ' ' + KIT_OTHERS[kit] : '') + '\n' +
    '4. Serve my changed version. HarnessRouter serves only the kit’s own app at /kits/' + kit + ', not a copy I change, so the changed app runs on a host of mine or in an image I build. Ask me which way, and suggest the backend path.\n\n' +
    'Backend path (recommended): my changed app keeps calling Harness ID ' + a.id + ' on this HarnessRouter.\n' + cloud + '\n\n' +
    'Image path: build the HarnessRouter image (' + OSS_REPO + ') from my fork of the starter kits: docker build --build-arg HR_KITS_REPO=<my fork’s git URL> --build-arg HR_KITS_REF=<my branch> . The image runs npm ci && npm run build in each kit’s app folder and serves it at /kits/<kit>. Run as a new HarnessRouter, launching the kit there makes a setup there with a Harness ID of its own, and the app finds that one the same way. Harness ID ' + a.id + ' is the setup on this HarnessRouter.\n\n' +
    'How it connects as HarnessRouter serves it (the default): the app is a browser app with no backend of its own. HarnessRouter serves it at /kits/' + kit + ' on the same origin as the console, and my signed-in console session goes with every request it makes, so it needs no API key and no login of its own. Never put a key in the app’s browser code.\n' +
    'The app is already connected to Harness ID ' + a.id + '. The id is not written in the app’s code or in any config file: when the app starts, it looks up the setup launched from its kit id "' + kit + '" in my workspace, which is this one, and sends that setup’s id as metadata.harness_id on every request to POST /api/harness/v1/responses.';
}

/** "Connect your app": the coding agent adds one API call to the person's own app. Every setup gets
 *  this one prompt, an app that already calls another setup included (Richard, 10-18): its existing
 *  client is reused, and the feature keeps its own Harness ID. */
export function promptText(a: SetupRef): string {
  return 'Add an agent-powered feature to my app that sends tasks to this setup in my HarnessRouter workspace:\n' +
    setupLines(a) + (a.instr ? '\nWhat it does (already set in the setup, for context only): ' + a.instr : '') + '\n\n' +
    '1. ' + GUIDE_STEP + '\n' +
    '2. Find my app. ' + NEW_OR_EXISTING + ' If my backend already has a HarnessRouter client, reuse it for this feature.\n' +
    '3. ' + KEY_STEP + '\n' +
    '4. Call this setup from my backend as How it connects says below.\n' +
    '5. Add an input, a submit button, progress, error handling and a result view with its files.\n' +
    '6. ' + VERIFY + '\n\n' +
    howItConnects(a.id) + '\n\n' +
    INSTR_RULE;
}

/** The coding agents a prompt is pasted into, named with their marks beside every Copy prompt. No
 *  sheet opens one with the prompt (Richard, 10-18): every sheet copies, the same way. */
export const CODERS = [
  { name: 'Claude Code', logo: '/logos/claude.png' },
  { name: 'Codex', logo: '/logos/codex.png' },
];
