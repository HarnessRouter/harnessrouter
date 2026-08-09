import { redirect } from 'next/navigation';

// The console has two surfaces; harnesses is where you start (a task needs one to run on).
export default function Home() { redirect('/harnesses'); }
