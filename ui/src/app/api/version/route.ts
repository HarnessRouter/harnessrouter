// Deploy fingerprint for the console/BFF — binds this running build to the exact source
// commit it was built from, so release verification can confirm the live env matches the
// tested SHA. The SHA is baked at build time (scripts/vm-deploy.sh reads HR_BUILD_SHA from
// the deploying dev box, since the VM build tree has no .git). Read-only, no auth, no CORS.
export const dynamic = 'force-dynamic';

export async function GET() {
  return new Response(
    JSON.stringify({ build: process.env.HR_BUILD_SHA || 'unknown' }),
    { status: 200, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } },
  );
}
