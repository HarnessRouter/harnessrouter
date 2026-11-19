import test from 'node:test';
import assert from 'node:assert/strict';
import { codeLanguageFromClass, codeLanguageLabel, syntaxLanguage } from '../src/markdown.ts';

test('code fences expose a stable language label for the content header', () => {
  assert.equal(codeLanguageFromClass('language-ts extra'), 'ts');
  assert.equal(codeLanguageFromClass('no-language'), '');
  assert.equal(codeLanguageFromClass(undefined), '');
  assert.equal(codeLanguageLabel('ts'), 'TypeScript');
  assert.equal(codeLanguageLabel('json'), 'JSON');
  assert.equal(codeLanguageLabel('custom-lang'), 'CUSTOM-LANG');
  assert.equal(codeLanguageLabel(''), '代码');
  assert.equal(syntaxLanguage('ts'), 'typescript');
  assert.equal(syntaxLanguage('sh'), 'bash');
  assert.equal(syntaxLanguage('custom-lang'), 'plaintext');
});
