const LANGUAGE_LABELS: Record<string, string> = {
  bash: 'Bash',
  c: 'C',
  cpp: 'C++',
  cs: 'C#',
  css: 'CSS',
  diff: 'Diff',
  dockerfile: 'Dockerfile',
  go: 'Go',
  html: 'HTML',
  java: 'Java',
  js: 'JavaScript',
  json: 'JSON',
  jsx: 'JSX',
  md: 'Markdown',
  markdown: 'Markdown',
  php: 'PHP',
  py: 'Python',
  python: 'Python',
  rb: 'Ruby',
  ruby: 'Ruby',
  rust: 'Rust',
  sh: 'Shell',
  shell: 'Shell',
  sql: 'SQL',
  swift: 'Swift',
  text: 'Text',
  ts: 'TypeScript',
  tsx: 'TSX',
  xml: 'XML',
  yaml: 'YAML',
  yml: 'YAML',
};

const SYNTAX_LANGUAGES: Record<string, string> = {
  bash: 'bash', c: 'c', cpp: 'cpp', cs: 'csharp', css: 'css', diff: 'diff', dockerfile: 'docker',
  go: 'go', html: 'markup', java: 'java', js: 'javascript', json: 'json', jsx: 'jsx', md: 'markdown',
  markdown: 'markdown', php: 'php', py: 'python', python: 'python', rb: 'ruby', ruby: 'ruby',
  rust: 'rust', sh: 'bash', shell: 'bash', sql: 'sql', swift: 'swift', text: 'plaintext',
  ts: 'typescript', tsx: 'tsx', xml: 'markup', yaml: 'yaml', yml: 'yaml',
};

export function codeLanguageFromClass(className?: string): string {
  const match = /(?:^|\s)language-([\w-]+)/.exec(className || '');
  return match?.[1]?.toLowerCase() || '';
}

export function codeLanguageLabel(language?: string): string {
  const value = (language || '').trim().toLowerCase();
  if (!value) return '代码';
  return LANGUAGE_LABELS[value] || value.toUpperCase();
}

export function syntaxLanguage(language?: string): string {
  const value = (language || '').trim().toLowerCase();
  return SYNTAX_LANGUAGES[value] || 'plaintext';
}
