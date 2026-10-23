// A file picked for a skill or a plugin package, read the way the server stores it. Shared by the
// skill editor (hrui/skills/SkillEditor) and a setup's Settings (installing a plugin package from a
// folder).

/** One file of a skill's folder, or of a plugin package: text as `content`, anything else as base64. */
export type SkillFile = { path: string; content?: string; content_b64?: string };

// Read an uploaded file as a skill file. Valid UTF-8 text (no NUL) is kept as editable `content`;
// anything else (binaries like .exe/.png, or text with embedded NULs) is base64-encoded into
// `content_b64`. This keeps binary bytes intact AND keeps NUL out of any JSON string: a literal NUL
// in skill content otherwise aborts the harness save at the store.
export async function readSkillUpload(file: File, path: string): Promise<SkillFile> {
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
      if (text.indexOf(String.fromCharCode(0)) === -1) return { path, content: text };
    } catch { /* not valid UTF-8 → binary */ }
    let bin = '';
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) bin += String.fromCharCode(...bytes.subarray(i, i + CH));
    return { path, content_b64: btoa(bin) };
  } catch {
    return { path, content: '' };
  }
}
