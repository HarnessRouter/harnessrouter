// Which edition of the console this build is.
//
// This is the SAME console the hosted product runs — same components, same styles, same API
// client. It is not a fork or a reimplementation, because two consoles that drift are two
// products, and the whole point of open-core is that they are one.
//
// What differs self-hosted is only what a single box HAS. There is no accounts service, so there
// is no login; no billing service, so there are no credits; no marketplace and no analytics
// pipeline, so those surfaces have nothing behind them. Rather than delete that code (which is
// how a fork starts), this flag hides the surfaces whose backend isn't present. The routes still
// exist and still compile — they simply aren't reachable from the navigation.
//
// Set at build time so it can be tree-shaken and so a self-hosted image can never accidentally
// present a hosted-only surface.
export const SELF_HOSTED = process.env.NEXT_PUBLIC_HR_EDITION === 'selfhost';

/** The implicit single tenant of a self-hosted instance.
 *
 *  There is no login, but the gateway still scopes every record by org and member. Keeping real
 *  values (rather than empty ones) means the storage layout is identical to the hosted one, which
 *  is what makes promoting a harness to the cloud a copy rather than a translation. */
export const LOCAL_ORG = 'local';
export const LOCAL_MEMBER = 'local@localhost';

/** Sidebar entries a self-hosted box can actually serve. Everything else in the nav needs a
 *  service that isn't in the container.
 *
 *  Integrations is here because bring-your-own-key IS the self-hosted product: without it the
 *  box has no credentials and every turn fails. Hosted it stays a platform-admin surface, since
 *  there the routing config is global. */
export const SELF_HOSTED_NAV = ['/harnesses', '/tasks', '/integrations'];

/** Orgs allowed to see platform-admin surfaces (global model routing).
 *
 *  Read from the environment, never hardcoded: an org id is an internal identifier, and a
 *  deployment that doesn't set this simply has no platform admins. The gateway enforces the
 *  same list server-side (HR_INTEGRATIONS_ADMIN_ORGS) — this only decides what is shown. */
export const PLATFORM_ADMIN_ORGS: string[] =
  (process.env.NEXT_PUBLIC_HR_PLATFORM_ADMIN_ORGS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
