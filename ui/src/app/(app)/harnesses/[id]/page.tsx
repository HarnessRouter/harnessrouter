// Harness settings live inside the Agent harnesses page now (v2). Old links land there.
import { redirect } from 'next/navigation';

export default async function HarnessSettingsRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/harnesses?h=${encodeURIComponent(decodeURIComponent(id))}&view=settings`);
}
