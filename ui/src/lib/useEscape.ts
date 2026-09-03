'use client';
import { useEffect } from 'react';

/**
 * Close a dialog with Escape.
 *
 * Every modal here can be dismissed by clicking its backdrop, which leaves anyone working from
 * the keyboard with no way out at all. `active` is the open flag, so the listener exists only
 * while the dialog does and a stack of dialogs closes innermost first.
 */
export function useEscape(active: boolean, onClose: () => void): void {
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
}
