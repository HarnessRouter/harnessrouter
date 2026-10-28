'use client';
// Deploy to Cloud: the setup page bar's second action, beside Connect your app (10-23: "one click
// deploy the local harness into HarnessRouter cloud"). One button, in the one place a setup's actions
// live, and it always says where the setup stands:
//   - Deploy to Cloud: never deployed. One click deploys it. The first time this instance has no cloud
//     workspace yet, so the click opens HarnessRouter Cloud's sign-in in a new tab (the same hand-off
//     Bring your own key's Get a key uses). The person signs in or up there, the key minted for their
//     workspace lands on this instance's server (never in this page), and the deploy goes on by itself.
//   - Update Cloud: deployed, and the setup changed since. One click replaces the cloud copy.
//   - In Cloud: deployed and current. Its menu opens the copy in HarnessRouter Cloud, deploys again, or
//     deploys to another workspace (the destinations this instance keeps: CloudUploadSheet).
// The cloud copy is one way: this instance stays the source, and every deploy replaces the copy under
// the same cloud id. What it says of the copy (deployed, changed since) is the server's own status.
import { useCallback, useEffect, useRef, useState } from 'react';
import { listTargets, pollDeploySignIn, startDeploySignIn, statusOne, uploadOne, type CloudStatus, type CloudTarget } from '@/lib/cloud-upload';
import { toast } from '../toast';
import { CloudUploadSheet } from './CloudUploadSheet';
import { plain } from './settingsModel';

const UP_IC = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 18a4.5 4.5 0 0 1-.9-8.9A6 6 0 0 1 17.6 8 4 4 0 0 1 17 18" /><path d="M12 12v8M9 15l3-3 3 3" /></svg>;
const OK_IC = <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 18a4.5 4.5 0 0 1-.9-8.9A6 6 0 0 1 17.6 8 4 4 0 0 1 17 18H7z" /><path d="M9.5 13.5l2 2 3.5-3.5" /></svg>;
/** Between reads of an open sign-in. */
export const SIGNIN_EVERY_MS = 2000;
/** A sign-in left open this long has ended on the hosted side (its code's lifetime). */
export const SIGNIN_MAX_MS = 30 * 60_000;

type Phase = 'idle' | 'signin' | 'deploying';

export function DeployCloud({ id, name }: { id: string; name: string }) {
  const [status, setStatus] = useState<CloudStatus | null>(null);
  // the destinations this instance keeps (null while read): known before the click, so the click
  // decides at once whether it deploys or opens the sign-in (a tab opened after a wait is blocked)
  const [targets, setTargets] = useState<{ list: CloudTarget[]; last: string } | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [signinUrl, setSigninUrl] = useState('');
  const [menu, setMenu] = useState(false);
  const [another, setAnother] = useState(false);
  const alive = useRef(true);
  const wrap = useRef<HTMLSpanElement | null>(null);
  useEffect(() => () => { alive.current = false; }, []);

  const readStatus = useCallback(() => {
    statusOne(id).then((s) => { if (alive.current) setStatus(s); }).catch(() => { /* the button says Deploy to Cloud */ });
  }, [id]);
  const readTargets = useCallback(() => {
    listTargets().then((r) => { if (alive.current) setTargets({ list: r.targets.filter((t) => !t.revoked), last: r.last }); })
      .catch(() => { if (alive.current) setTargets(null); });
  }, []);
  useEffect(() => { setStatus(null); readStatus(); readTargets(); }, [readStatus, readTargets]);

  // the menu closes on a click outside it and on Escape
  useEffect(() => {
    if (!menu) return;
    const down = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setMenu(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false); };
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [menu]);

  const deployTo = async (target: string) => {
    setPhase('deploying');
    try {
      const r = await uploadOne(id, target);
      if (!alive.current) return;
      if (!r.ok) { toast(plain(new Error(r.error || ''), `${name} could not be deployed. Try again.`)); return; }
      setStatus({ ...r.status, open_url: r.open_url || r.status?.open_url || '' });
      toast(r.action === 'create' ? `${name} is deployed to HarnessRouter Cloud.` : `${name} is updated in HarnessRouter Cloud.`);
    } catch (e) {
      if (alive.current) toast(plain(e, `${name} could not be deployed. Try again.`));
    } finally {
      if (alive.current) setPhase('idle');
    }
  };

  // the first deploy: sign in to HarnessRouter Cloud in a new tab, then deploy as soon as the key lands
  const signIn = async () => {
    // opened now, in the click itself, so the browser lets it open; pointed at the sign-in once known
    const tab = typeof window !== 'undefined' ? window.open('about:blank', '_blank') : null;
    if (tab) tab.opener = null;
    setPhase('signin');
    let code = '';
    try {
      const s = await startDeploySignIn();
      code = s.code;
      setSigninUrl(s.url);
      if (tab) tab.location.href = s.url;
    } catch (e) {
      tab?.close();
      if (alive.current) { setPhase('idle'); toast(plain(e, 'HarnessRouter Cloud could not be reached just now. Try again.')); }
      return;
    }
    const until = Date.now() + SIGNIN_MAX_MS;
    while (alive.current && Date.now() < until) {
      await new Promise((ok) => setTimeout(ok, SIGNIN_EVERY_MS));
      if (!alive.current) return;
      let got: CloudTarget | 'waiting';
      try { got = await pollDeploySignIn(code); }
      catch (e) { setPhase('idle'); setSigninUrl(''); toast(plain(e, 'The sign-in ended. Deploy again.')); return; }
      if (got === 'waiting') continue;
      setSigninUrl('');
      setTargets({ list: [got], last: got.id });
      await deployTo(got.id);
      return;
    }
    if (alive.current) { setPhase('idle'); setSigninUrl(''); toast('The sign-in ended. Deploy again.'); }
  };

  const deploy = () => {
    setMenu(false);
    if (phase === 'signin') { if (signinUrl) window.open(signinUrl, '_blank'); return; }
    if (phase !== 'idle') return;
    const pick = targets?.list.find((t) => t.id === targets.last) || targets?.list[0];
    if (pick) void deployTo(pick.id);
    else void signIn();
  };

  const deployed = !!status?.uploaded;
  const current = deployed && !status?.changed;
  const label = phase === 'deploying' ? 'Deploying…'
    : phase === 'signin' ? 'Finish signing in'
      : current ? 'In Cloud' : deployed ? 'Update Cloud' : 'Deploy to Cloud';
  const tip = phase === 'signin' ? 'Finish signing in to HarnessRouter Cloud in the tab it opened. The deploy goes on by itself.'
    : current ? `${name} is deployed to HarnessRouter Cloud${status?.target ? `, ${status.target}` : ''}.`
      : deployed ? `${name} changed since its deploy. Update the copy in HarnessRouter Cloud.`
        : `Deploy ${name} to HarnessRouter Cloud.`;
  return (
    <span ref={wrap} className="dc-w">
      <button type="button" className={`btn small ag-act dc-b${current ? ' on' : ''}`} aria-label={label} title={tip}
        aria-haspopup={current ? 'menu' : undefined} aria-expanded={current ? menu : undefined}
        aria-busy={phase !== 'idle' || undefined} disabled={phase === 'deploying'}
        onClick={() => (current && phase === 'idle' ? setMenu(!menu) : deploy())}>
        {current ? OK_IC : UP_IC}<span className="ag-act-l">{label}</span>
        {deployed && !current && phase === 'idle' ? <i className="dc-dot" aria-hidden="true" /> : null}
      </button>
      {menu ? (
        <span className="rng-pop dc-pop" role="menu" aria-label="In HarnessRouter Cloud">
          {status?.open_url ? (
            <button type="button" role="menuitem" onClick={() => { setMenu(false); window.open(status.open_url, '_blank', 'noopener'); }}>Open in HarnessRouter Cloud ↗</button>
          ) : null}
          <button type="button" role="menuitem" onClick={deploy}>Deploy again</button>
          <button type="button" role="menuitem" onClick={() => { setMenu(false); setAnother(true); }}>Deploy to another workspace…</button>
        </span>
      ) : null}
      {another ? (
        <CloudUploadSheet id={id} name={name} status={status} onClose={() => setAnother(false)}
          onDone={() => { readStatus(); readTargets(); }} />
      ) : null}
    </span>
  );
}
