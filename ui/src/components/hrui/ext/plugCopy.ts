// What the console says about each plugin and how it draws it. The catalog itself, which plugins this
// instance serves, their fields, tools, prices and states are the server's (GET /v1/plugs); these are
// only the words and marks beside them. A plugin the server serves that has no entry here is still
// listed, by its own label, with its initial for a mark and no line under it.

/** Each service by its own mark (public/plugs). `app`: an app icon that carries its own ground. */
export const MARK: Record<string, { src: string; app?: boolean }> = {
  github: { src: '/plugs/github.svg' }, vercel: { src: '/plugs/vercel.svg' }, microsoft365: { src: '/plugs/microsoft365.svg' },
  insforge: { src: '/plugs/insforge.png', app: true }, browser: { src: '/plugs/browser.svg' },
};

/** A plugin's one line, on its row and its tile. */
export const BLURB: Record<string, string> = {
  browser: 'A real web browser: open pages, read them, click, type, and take screenshots',
  github: 'Your own repository: files, branches, pull requests',
  vercel: 'Your own Vercel project: deployments and domains',
  insforge: 'Your own InsForge backend: tables and records',
  microsoft365: 'Your own SharePoint, OneDrive, Outlook and directory, as each signed-in person',
};

/** A plugin's paragraph, under the title of its sheet. */
export const ABOUT: Record<string, string> = {
  browser: 'Connect the browser so an agent can open a public page, read what is on it, fill in forms, click through, wait for things to appear and take screenshots that are kept with the task. Each task gets its own browser, opened when the agent first needs it and closed when the task ends. Private and local addresses are never reached, and you can limit the sites an agent may visit.',
  github: 'Connect a repository of your own GitHub account or organization with a token you create there. An agent can then read files, make commits on a branch, open pull requests and merge them in that repository and nowhere else. The token is tried against the repository before it is kept, stored securely, and never handed to the agent.',
  vercel: 'Connect a project of your own Vercel account or team with a token you create there. An agent can then read the project, trigger deployments from a branch and watch them go live. The token is tried against the project before it is kept, stored securely, and never handed to the agent.',
  insforge: 'Connect a backend project of your own InsForge account with its API key and address. An agent can then read and write its tables and check its health. The key is tried against the backend before it is kept, stored securely, and never handed to the agent.',
  microsoft365: 'Connect your organization’s own Microsoft Entra application. Each person then signs in with Microsoft once, and an agent working for them reads their SharePoint sites, OneDrive, mail and calendar exactly as they may; or run it as the application itself for unattended work. The application’s secret is checked at Entra before it is kept, stored securely, and never handed to the agent.',
};

/** How each field the server names for a plugin (its `secrets_needed` and `config_fields`) is labelled,
 *  with the hint under it. A field with no entry is shown by its own name. */
export const FIELD: Record<string, { label: string; hint?: string; kind?: 'text' | 'mode' }> = {
  token: { label: 'Access token', hint: 'Created in the service’s settings; tried there before it is kept.' },
  api_key: { label: 'API key' },
  client_secret: { label: 'Client secret', hint: 'From the Entra application’s certificates and secrets.' },
  repo: { label: 'Repository (owner/name)', hint: 'Agents can reach this repository and nothing else.' },
  owner: { label: 'Owner', hint: 'Left empty, the owner in the repository name.' },
  default_branch: { label: 'Default branch', hint: 'Left empty, main.' },
  project: { label: 'Project', hint: 'The project’s name or id at the service.' },
  project_id: { label: 'Project id' },
  team_id: { label: 'Team id', hint: 'For a project that belongs to a team.' },
  url: { label: 'Address', hint: 'The backend’s https address.' },
  region: { label: 'Region' },
  tenant_id: { label: 'Directory (tenant) id' },
  client_id: { label: 'Application (client) id' },
  mode: { label: 'Identity', kind: 'mode' },
};

/** Microsoft 365's two identities, as its Identity field offers them (delegated is the server's default). */
export const M365_MODES: [string, string][] = [
  ['delegated', 'Each person signs in with Microsoft (recommended)'],
  ['application', 'The application itself (unattended)'],
];

/** The fields a plugin cannot connect without. */
export const REQUIRED: Record<string, string[]> = {
  github: ['token', 'repo'], vercel: ['token', 'project'], insforge: ['api_key', 'url'], microsoft365: ['client_secret', 'tenant_id', 'client_id'],
};

/** Settings that are not fields of the connect form: the browser's site lists have their own section,
 *  and a record's own bookkeeping (who signed in, the directory's name) is shown, never typed. */
export const HIDDEN_FIELDS = new Set(['allow_domains', 'deny_domains', 'proxy', 'accounts', 'directory']);

/** The names a connected plugin shows back, in the order they read best. Never a secret. */
export const SHOWN: Record<string, [string, string][]> = {
  github: [['repo', 'Repository'], ['owner', 'Owner'], ['default_branch', 'Default branch']],
  vercel: [['project', 'Project'], ['project_id', 'Project id'], ['team_id', 'Team']],
  insforge: [['url', 'Address'], ['project', 'Project'], ['region', 'Region']],
  microsoft365: [['directory', 'Directory'], ['tenant_id', 'Directory id'], ['client_id', 'Application id'], ['mode', 'Identity']],
};
