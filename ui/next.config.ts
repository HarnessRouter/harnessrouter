import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Blue-green deploys: each slot builds AND serves from its own dist dir, so a build never
  // clobbers the directory the live server is reading (mismatched-chunk 404s) and the new
  // slot boots fully before nginx flips — zero 502s during rollout.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Self-hosted ships as one container: emit a server bundle with only the modules it needs.
  output: "standalone",
  // V1C02-007: baseline browser security headers on every response — clickjacking defense
  // (frame-ancestors 'none' + X-Frame-Options DENY), HSTS, MIME-sniff off, tight referrer,
  // and a locked-down permissions policy. The console renders no third-party iframes and is
  // never meant to be embedded, so 'none' is safe and has no functional regression.
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
  webpack: (config) => {
    // NOTE: do NOT alias react/react-dom here — Next.js installs its own layer-aware react
    // aliases (RSC vs client) that must also apply to the out-of-root UI Core source; overriding
    // them breaks server prerender (`null.useContext`).
    // UI Core's CodeBlock lazy-imports highlight.js from outside the app root, where webpack's
    // node_modules walk-up can't find this app's copy. Append this app's node_modules as a
    // FALLBACK dir (not an alias — an alias would also hijack react-syntax-highlighter's nested
    // highlight.js@10 grammar imports, which need v10-only files v11 removed).
    config.resolve.modules = [...(config.resolve.modules ?? ["node_modules"]), path.resolve(__dirname, "node_modules")];
    return config;
  },
};

export default nextConfig;
