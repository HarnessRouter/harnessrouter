import { redirect } from 'next/navigation';

// The docs live on the site (the console's menu links there). This route was an early stub that showed a
// request to an address that does not exist; it now sends anyone who opens it to the real docs.
export default function Docs() {
  redirect('https://harnessrouter.ai/docs');
}
