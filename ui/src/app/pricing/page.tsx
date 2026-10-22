import { redirect } from 'next/navigation';

// Pricing lives on the site. This route was an early placeholder ("Details coming soon"); it now sends anyone
// who opens it to the real page.
export default function Pricing() {
  redirect('https://harnessrouter.ai/pricing');
}
