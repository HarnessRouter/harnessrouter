// A SKILL.md's name and description, as the editor opens them, read the way the server reads them
// (gateway _plugin_frontmatter, runner _frontmatter: the same shapes are tested there).
import { frontmatterValue, joinSkillMd, splitSkillMd } from './skillMd';

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
    ['two paragraphs', 'description: >\n  Paragraph one.\n\n  Paragraph two.', 'Paragraph one. Paragraph two.'],
    ['hash inside a word', 'description: Writes C# and F#', 'Writes C# and F#'],
    ['comment only', 'description: #1 tool', ''],
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

  test('a blank line after the description stays among the other lines', () => {
    const s = splitSkillMd('---\nname: shop-tone\ndescription: >\n  One.\n\nlicense: MIT\n---\nBody\n');
    expect([s.description, s.rest]).toEqual(['One.', ['', 'license: MIT']]);
  });

  test('a long run of spaces reads in linear time, and only the first 64 KB is read', () => {
    const spaces = ' '.repeat(200_000);
    let t0 = performance.now();
    expect(frontmatterValue(`x${spaces}y`, [`${spaces}z`])).toBe(`x${spaces}y z`);
    expect(performance.now() - t0).toBeLessThan(50);
    t0 = performance.now();
    const huge = `---\nname: shop-tone\ndescription: x\n${`${spaces}\n`.repeat(50)}---\nBody\n`;
    expect(splitSkillMd(huge).description).toBe('');
    expect(performance.now() - t0).toBeLessThan(50);
  });
});
