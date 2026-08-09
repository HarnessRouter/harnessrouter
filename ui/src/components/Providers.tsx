'use client';

import { DialogHost } from 'reifyui';

/** Client-side context that has to wrap the whole tree.
 *
 *  The root layout is a server component, so anything using React context lives here instead.
 *  DialogHost is what lets any page `await confirm(...)` for destructive actions — deleting a
 *  harness, deleting a task — without a browser popup. */
export function Providers({ children }: { children: React.ReactNode }) {
  return <DialogHost>{children}</DialogHost>;
}
