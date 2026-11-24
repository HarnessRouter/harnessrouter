// A SKILL.md's name and description, as the editor opens them, read the way the server reads them
// (gateway _plugin_frontmatter, runner _frontmatter: the same shapes are tested there).
import { joinSkillMd, splitSkillMd } from './skillMd';

const fm = (lines: string) => `---\nname: shop-tone\n${lines}\nlicense: MIT\n---\nBody\n`;

describe('splitSkillMd reads a description as YAML does', () => {
  test.each([
    ['folded', 'description: >-\n  How the shop writes\n  to customers.', 'How the shop writes to customers.'],
    ['literal', 'description: |\n  Line one.\n  Line two.', 'Line one.\nLine two.'],
    ['console json', 'description: "Formats issues like #123 and says \\"done\\""', 'Formats issues like #123 and says "done"'],
    ['quoted + comment', 'description: "Quoted value" # note', 'Quoted value'],
    ['single quoted', "description: 'It''s the shop voice' # note", "It's the shop voice"],
    ['plain + comment', 'description: Writes replies # how', 'Writes replies'],
    ['plain continued', "description: Writes replies\n  in the shop's voice.", "Writes replies in the shop's voice."],
    ['plain on next lines', "description:\n  Writes replies in the shop's voice.", "Writes replies in the shop's voice."],
    ['quoted over two lines', 'description: "Runs over\n  two lines"', 'Runs over two lines'],
  ])('%s', (_label, lines, want) => {
    const s = splitSkillMd(fm(lines));
    expect(s.name).toBe('shop-tone');
    expect(s.description).toBe(want);
    expect(s.rest).toEqual(['license: MIT']);
    expect(s.body).toBe('Body\n');
  });

  test('a byte-order mark and Windows line ends', () => {
    const s = splitSkillMd('﻿---\r\nname: shop-tone\r\ndescription: Windows line ends\r\n---\r\nBody\r\n');
    expect([s.name, s.description, s.body]).toEqual(['shop-tone', 'Windows line ends', 'Body\r\n']);
  });

  test('saving writes back a file that reads the same, with no stray continuation line', () => {
    const s = splitSkillMd(fm("description: Writes replies\n  in the shop's voice."));
    const saved = joinSkillMd(s.name, s.description, s.rest, s.body);
    expect(saved).toBe(`---\nname: shop-tone\ndescription: "Writes replies in the shop's voice."\nlicense: MIT\n---\n\nBody\n`);
    expect(splitSkillMd(saved).description).toBe("Writes replies in the shop's voice.");
  });
});
