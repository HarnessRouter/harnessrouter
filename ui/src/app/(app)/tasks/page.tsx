// Tasks are part of the Agent harnesses page now (v2): each harness lists its tasks, and a
// task opens in place. Old links, with their harness and session, land there.
import { redirect } from 'next/navigation';

export default async function TasksRedirect({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const q = new URLSearchParams();
  const h = typeof sp.h === 'string' ? sp.h : '';
  const sid = typeof sp.sid === 'string' ? sp.sid : '';
  if (h) q.set('h', h);
  if (sid) q.set('sid', sid);
  const qs = q.toString();
  redirect(qs ? `/harnesses?${qs}` : '/harnesses');
}
