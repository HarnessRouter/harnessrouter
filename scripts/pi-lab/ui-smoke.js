// Run with playwright-cli run-code --filename scripts/pi-lab/ui-smoke.js after
// signing into a local UI build. API fixtures are local to this browser session.
async (page) => {
  const base = new URL(page.url()).origin;
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  let agent = { id: 'pi-lab-ui-test', name: 'Pi Lab experiment', base: 'pi-lab', baseLabel: 'Pi Lab',
    defaultModel: 'gpt-5.4', systemPrompt: '', skills: [], mcpServers: [], plugins: [], disabledTools: [], piLab: {} };
  let saved;
  await page.route('**/api/harness/**', async route => {
    const path = route.request().url().split('?')[0];
    let body = {};
    if (path.endsWith('/harnesses/pi-lab-ui-test')) {
      if (route.request().method() === 'PUT') {
        saved = route.request().postDataJSON();
        agent = { ...agent, piLab: saved.pi_lab };
      }
      body = agent;
    } else if (path.endsWith('/harnesses')) body = { harnesses: [agent] };
    else if (path.endsWith('/workspaces')) body = { workspaces: [{id: 'default', name: 'Local test'}], default_workspace_id: 'default' };
    else if (path.endsWith('/bases')) body = { bases: [{id: 'pi-lab', label: 'Pi Lab', tools: [], builtinSkills: []}], runtimeDefaults: { maxStep: 100, timeoutSeconds: 600 } };
    else if (path.endsWith('/traces')) body = { sessions: [], cursor: '' };
    await route.fulfill({ json: body });
  });
  await page.goto(`${base}/harnesses?h=pi-lab-ui-test&view=settings`);
  const fusion = page.getByRole('button', { name: 'Action Fusion', exact: true });
  await fusion.waitFor();
  if (await fusion.getAttribute('aria-pressed') !== 'true') throw new Error('Default switch not enabled');
  await fusion.click();
  await page.getByLabel('Cache write/read price ratio').fill('0');
  await page.getByLabel('Reducer model (optional)').fill('small-model');
  await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
  await page.waitForURL('**/harnesses?h=pi-lab-ui-test');
  if (saved?.base !== 'pi-lab' || saved?.pi_lab?.actionFusion !== false || saved?.pi_lab?.cacheWriteReadRatio !== 0 || saved?.pi_lab?.reducerModel !== 'small-model') {
    throw new Error('Pi Lab config did not survive form serialization');
  }
  await page.goto(`${base}/harnesses?h=pi-lab-ui-test&view=settings`);
  await fusion.waitFor();
  if (await fusion.getAttribute('aria-pressed') !== 'false') throw new Error('Saved switch did not reload');
  await page.getByRole('heading', { name: 'Mechanisms', exact: true }).scrollIntoViewIfNeeded();
  console.log('Pi Lab UI: independent base, defaults, toggle, zero ratio, reducer model, save and reload passed.');
  await page.goto(`${base}/harnesses?h=pi-lab&view=settings`);
  await page.getByRole('heading', { name: 'Mechanisms', exact: true }).waitFor();
  if (!(await fusion.isDisabled())) throw new Error('Built-in mechanisms must be read-only');
  if (await fusion.getAttribute('aria-pressed') !== 'true') throw new Error('Custom toggle leaked into built-in defaults');
  await page.getByRole('button', { name: 'Fork and Customize' }).waitFor();
}
