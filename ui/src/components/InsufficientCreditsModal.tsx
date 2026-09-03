'use client';
// The credit wall, surfaced as a dialog instead of a line of red text in the transcript.
//
// WHY A DIALOG. A run that stops for money is not an error the user can debug — it is a decision
// they have to make, and the only useful next move is a page they may not know exists. An inline
// "Error: insufficient credits" leaves them re-reading a transcript looking for a fix that isn't
// in it. This names the reason and hands them the door.
//
// It is DISMISSIBLE, unlike the onboarding wall: the user may well want to go back and read what
// their agent did before deciding to spend. Blocking that would be punishing them for running out.
import { useRouter } from 'next/navigation';
import { track } from '@/lib/analytics';

export function InsufficientCreditsModal({ balance, onClose }: {
  /** Live balance, or null when we don't have it — never invent a number on a money screen. */
  balance: number | null;
  onClose: () => void;
}) {
  const router = useRouter();
  return (
    <div className="welcome-overlay" role="dialog" aria-modal="true" aria-labelledby="oc-title"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="oc-card">
        <button className="welcome-wide-close" type="button" aria-label="Close" onClick={onClose}>
          <iconify-icon icon="tabler:x"></iconify-icon>
        </button>
        <div className="oc-badge"><iconify-icon icon="tabler:bolt-off"></iconify-icon></div>
        <h2 className="welcome-title" id="oc-title">Insufficient credits</h2>
        <p className="welcome-sub">
          Your run stopped because this workspace is out of credits.
          {balance != null ? <> Your balance is <b>{balance.toLocaleString()}</b>.</> : null}
          {' '}Top up and start it again. Nothing you have already done is lost.
        </p>
        <button className="welcome-cta oc-cta" type="button"
          onClick={() => { track('credits_checkout_started', { kind: 'out_of_credits_modal', package_id: '' });
                           router.push('/billing'); onClose(); }}>
          <iconify-icon icon="tabler:credit-card"></iconify-icon>Add Credits
        </button>
        <button className="welcome-later" type="button" onClick={onClose}>Not now</button>
      </div>
    </div>
  );
}
