declare module 'turndown' {
  interface Options { headingStyle?: string; codeBlockStyle?: string; bulletListMarker?: string; emDelimiter?: string; strongDelimiter?: string; hr?: string }
  interface RuleNode { nodeName: string; firstChild: { nodeName: string } | null }
  export default class TurndownService {
    constructor(options?: Options);
    addRule(name: string, rule: { filter: (node: RuleNode) => boolean; replacement: (content: string, node: RuleNode) => string }): void;
    turndown(html: string): string;
  }
}

declare module 'node-diff3' {
  export interface Region<T> { ok?: T[]; conflict?: { a: T[]; o: T[]; b: T[] } }
  export function diff3Merge<T>(a: T[], o: T[], b: T[], options?: { excludeFalseConflicts?: boolean }): Region<T>[];
}
